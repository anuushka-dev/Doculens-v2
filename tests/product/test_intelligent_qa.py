"""Tests for conversational follow-ups, concept retrieval, and grounded synthesis."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import pymupdf
from fastapi.testclient import TestClient

from app.adapters.llm.ollama_client import OllamaOutputValidationError
from app.api.routes import qa, workspace
from app.core.config import Settings
from app.main import app
from app.schemas.answer import (
    AnswerDraft,
    AnswerStatus,
    EvidenceAssessment,
    EvidenceQuoteDraft,
    GroundedSynthesis,
    StandaloneQuery,
)
from app.schemas.document import ExtractedPage
from app.services.answer_generation import AnswerGenerationService
from app.services.document_sessions import get_session_store
from app.services.hybrid_retrieval import HybridRetrievalPipeline


def _build_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a multi-page selectable-text PDF in memory for workspace integration tests."""

    pdf = pymupdf.open()
    try:
        for text in page_texts:
            page = pdf.new_page()
            page.insert_textbox((72, 72, 520, 720), text)
        return pdf.tobytes()
    finally:
        pdf.close()


def _extract_chunk_block(prompt: str, needle: str) -> tuple[str, str] | None:
    """Return (chunk_id, text) for the chunk block containing needle."""

    pattern = re.compile(
        r"\[chunk_id=([^\s\]]+)[^\]]*\]\n(.*?)(?=\n\[chunk_id=|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(prompt):
        cid, block_text = match.group(1), match.group(2).strip()
        if needle in block_text:
            return cid, block_text
    return None


class _FakeStructuredLLM:
    """Deterministic fake StructuredGenerator keyed by Pydantic response_model."""

    def __init__(self, handler: Callable[[str, type], object]) -> None:
        self.handler = handler
        self.calls: list[tuple[type, str]] = []

    async def generate_structured(
        self,
        *,
        prompt: str,
        response_model: type,
    ) -> object:
        self.calls.append((response_model, prompt))
        result = self.handler(prompt, response_model)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, Awaitable):
            return await result
        return result

    async def aclose(self) -> None:
        return None


def _sample_pages() -> list[ExtractedPage]:
    return [
        ExtractedPage(
            page_number=1,
            text=(
                "1. Problem Statement\n"
                "Engineers need cited answers from multi-page technical specifications "
                "without invented claims or opaque summaries."
            ),
        ),
        ExtractedPage(
            page_number=2,
            text=(
                "2. System Scope and Hard Boundary\n"
                "DocuLens restricts uploads to a maximum of 350 pages and 20 MiB per PDF."
            ),
        ),
        ExtractedPage(
            page_number=3,
            text=(
                "3. Phased Roadmap\n"
                "Phase 3 enforces evidence validation before displaying citations to users."
            ),
        ),
    ]


def test_lexical_concept_expansion_handles_limits_and_problem_statement_without_noise() -> None:
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(
        _sample_pages(),
        document_id="doc-intel-1",
        file_name="plan.pdf",
    )

    limit_hits = pipeline.search_evidence("what is doculens limit?", top_k=3)
    assert any(chunk.page_number == 2 for chunk in limit_hits.results)

    problem_hits = pipeline.search_evidence("what is the problem statement?", top_k=3)
    assert any(chunk.page_number == 1 for chunk in problem_hits.results)

    unrelated = pipeline.search_evidence("penguins volcanos", top_k=3)
    assert unrelated.results == ()


def test_resolve_question_rewrites_followups_and_handles_validation_failures() -> None:
    def handler(prompt: str, model: type) -> object:
        assert model is StandaloneQuery
        return StandaloneQuery(
            standalone_question="What is the hard boundary for DocuLens PDF uploads?"
        )

    fake_llm = _FakeStructuredLLM(handler)
    service = AnswerGenerationService(llm_client=fake_llm, top_k=4)

    # Empty history or clear new topic does not trigger an extra rewrite call.
    no_hist = asyncio.run(service.resolve_question(question="what is doculens limit?"))
    assert no_hist == "what is doculens limit?"
    assert len(fake_llm.calls) == 0

    topic_shift = asyncio.run(
        service.resolve_question(
            question="Explain the phased roadmap schedule cleanly",
            history=[("user", "what is doculens limit?")],
        )
    )
    assert topic_shift == "Explain the phased roadmap schedule cleanly"
    assert len(fake_llm.calls) == 0

    rewritten = asyncio.run(
        service.resolve_question(
            question="what about its hard boundary?",
            history=[
                ("user", "What is DocuLens?"),
                ("assistant", "A local PDF QA tool."),
            ],
        )
    )
    assert rewritten == "What is the hard boundary for DocuLens PDF uploads?"
    assert len(fake_llm.calls) == 1

    failing_service = AnswerGenerationService(
        llm_client=_FakeStructuredLLM(
            lambda _p, _m: OllamaOutputValidationError("bad json")
        ),
        top_k=4,
    )
    fallback = asyncio.run(
        failing_service.resolve_question(
            question="which page mentions it?",
            history=[("user", "What is the hard boundary?")],
        )
    )
    assert fallback == "which page mentions it?"


def test_grounded_synthesis_answers_naturally_and_blocks_hallucinated_numbers() -> None:
    pages = _sample_pages()
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(pages, document_id="doc-intel-2", file_name="plan.pdf")
    chunks = pipeline.search_evidence("what is doculens limit?", top_k=3).results
    target_quote = "DocuLens restricts uploads to a maximum of 350 pages and 20 MiB per PDF."

    def build_handler(*, synthesis_text: str) -> Callable[[str, type], object]:
        def handler(prompt: str, model: type) -> object:
            name = model.__name__
            if name == "AnswerDraft":
                found = _extract_chunk_block(prompt, target_quote)
                assert found is not None
                return AnswerDraft(
                    answer="Draft limit is 350 pages.",
                    evidence=(EvidenceQuoteDraft(chunk_id=found[0], quote=target_quote),),
                )
            if name == "EvidenceAssessment":
                return EvidenceAssessment(
                    reason="Verified against page 2.",
                    verdict="supported",
                    supporting_ids=("C1",),
                )
            if model is GroundedSynthesis:
                return GroundedSynthesis(
                    direct_answer=synthesis_text,
                    used_citation_ids=("C1",),
                )
            raise AssertionError(f"Unexpected model {model}")

        return handler

    good_service = AnswerGenerationService(
        llm_client=_FakeStructuredLLM(
            build_handler(
                synthesis_text=(
                    "DocuLens enforces a hard cap of 350 pages and 20 MiB per uploaded PDF."
                )
            )
        ),
        top_k=4,
    )
    good_resp = asyncio.run(
        good_service.answer_chunks(
            chunks=chunks,
            document_id="doc-intel-2",
            file_name="plan.pdf",
            question="what is doculens limit?",
            synthesize_answer=True,
        )
    )
    assert good_resp.status == AnswerStatus.ANSWERED
    assert good_resp.cited_pages == (2,)
    assert "350 pages" in good_resp.answer
    assert "Source: PDF page 2" in good_resp.answer

    # Hallucinated number (9999) in synthesis must be rejected -> quote-only fallback.
    hallucinating_service = AnswerGenerationService(
        llm_client=_FakeStructuredLLM(
            build_handler(
                synthesis_text="DocuLens allows 9999 pages for enterprise uploads."
            )
        ),
        top_k=4,
    )
    safe_resp = asyncio.run(
        hallucinating_service.answer_chunks(
            chunks=chunks,
            document_id="doc-intel-2",
            file_name="plan.pdf",
            question="what is doculens limit?",
            synthesize_answer=True,
        )
    )
    assert safe_resp.status == AnswerStatus.ANSWERED
    assert "9999" not in safe_resp.answer
    assert target_quote in safe_resp.answer
    assert safe_resp.cited_pages == (2,)

    # Hallucinated page reference (PDF page 9) must also fall back safely.
    bad_page_service = AnswerGenerationService(
        llm_client=_FakeStructuredLLM(
            build_handler(
                synthesis_text="On PDF page 9, DocuLens allows 350 pages."
            )
        ),
        top_k=4,
    )
    bad_page_resp = asyncio.run(
        bad_page_service.answer_chunks(
            chunks=chunks,
            document_id="doc-intel-2",
            file_name="plan.pdf",
            question="what is doculens limit?",
            synthesize_answer=True,
        )
    )
    assert "page 9" not in bad_page_resp.answer
    assert target_quote in bad_page_resp.answer


def test_workspace_intelligent_qa_multiturn_flow(monkeypatch) -> None:
    pdf_bytes = _build_pdf_bytes([page.text for page in _sample_pages()])
    synthesis_mode = {"hallucinate": False}

    def handler(prompt: str, model: type) -> object:
        name = model.__name__
        if model is StandaloneQuery:
            return StandaloneQuery(
                standalone_question="Which PDF page specifies the DocuLens page limit?"
            )
        if name == "AnswerDraft":
            found = _extract_chunk_block(prompt, "350 pages")
            if found is not None:
                cid, block_text = found
                quote = next(
                    (line.strip() for line in block_text.splitlines() if "350 pages" in line),
                    block_text,
                )
                return AnswerDraft(
                    answer="350 pages and 20 MiB per PDF.",
                    evidence=(EvidenceQuoteDraft(chunk_id=cid, quote=quote),),
                )
            return AnswerDraft(answer="Cannot answer.", abstain=True, evidence=())
        if name == "EvidenceAssessment":
            return EvidenceAssessment(
                reason="Page 2 explicitly states the 350-page limit.",
                verdict="supported",
                supporting_ids=("C1",),
            )
        if model is GroundedSynthesis:
            if synthesis_mode["hallucinate"]:
                return GroundedSynthesis(
                    direct_answer="DocuLens supports 9999 pages.",
                    used_citation_ids=("C1",),
                )
            if "just give that page" in prompt:
                assert "explicitly asked which PDF page(s)" in prompt
            return GroundedSynthesis(
                direct_answer=(
                    "PDF page 2 specifies the DocuLens upload cap of 350 pages "
                    "and 20 MiB."
                ),
                used_citation_ids=("C1",),
            )
        raise AssertionError(f"Unexpected model {model}")

    fake_llm = _FakeStructuredLLM(handler)
    service = AnswerGenerationService(llm_client=fake_llm, top_k=4)

    get_session_store().clear()
    monkeypatch.setattr(
        workspace,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            retrieval_mode="lexical",
            enable_grounded_synthesis=True,
        ),
    )

    async def override_service():
        yield service

    app.dependency_overrides[qa.get_answer_generation_service] = override_service
    try:
        with TestClient(app) as client:
            upload = client.post(
                "/api/documents",
                files={"file": ("plan.pdf", pdf_bytes, "application/pdf")},
            )
            assert upload.status_code == 201
            doc = upload.json()
            headers = {"X-Document-Token": doc["document_token"]}

            turn1 = client.post(
                f"/api/documents/{doc['document_id']}/ask",
                headers=headers,
                json={"question": "what is doculens limit?"},
            )
            assert turn1.status_code == 200
            data1 = turn1.json()
            assert data1["status"] == "answered"
            assert data1["cited_pages"] == [2]
            assert data1["resolved_question"] is None
            assert "350 pages" in data1["answer"]
            assert "Source: PDF page 2" in data1["answer"]

            turn2 = client.post(
                f"/api/documents/{doc['document_id']}/ask",
                headers=headers,
                json={
                    "question": "just give that page",
                    "history": [
                        {"role": "user", "content": "what is doculens limit?"},
                        {"role": "assistant", "content": data1["answer"]},
                    ],
                },
            )
            assert turn2.status_code == 200
            data2 = turn2.json()
            assert data2["status"] == "answered"
            assert data2["cited_pages"] == [2]
            assert (
                data2["resolved_question"]
                == "Which PDF page specifies the DocuLens page limit?"
            )
            assert "PDF page 2" in data2["answer"]

            synthesis_mode["hallucinate"] = True
            turn3 = client.post(
                f"/api/documents/{doc['document_id']}/ask",
                headers=headers,
                json={"question": "what is doculens limit?"},
            )
            assert turn3.status_code == 200
            data3 = turn3.json()
            assert data3["status"] == "answered"
            assert "9999" not in data3["answer"]
            assert "350 pages" in data3["answer"]
    finally:
        app.dependency_overrides.pop(qa.get_answer_generation_service, None)
        get_session_store().clear()


def test_grounded_synthesis_does_not_bypass_abstention() -> None:
    pages = _sample_pages()
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(pages, document_id="doc-intel-3", file_name="plan.pdf")
    chunks = pipeline.search_evidence("what is doculens limit?", top_k=3).results
    quote = "DocuLens restricts uploads to a maximum of 350 pages and 20 MiB per PDF."

    def handler(prompt: str, model: type) -> object:
        name = model.__name__
        if name == "AnswerDraft":
            found = _extract_chunk_block(prompt, quote)
            assert found is not None
            return AnswerDraft(
                answer="Not enough info.",
                evidence=(EvidenceQuoteDraft(chunk_id=found[0], quote=quote),),
            )
        if name == "EvidenceAssessment":
            return EvidenceAssessment(
                reason="Missing subscription pricing.",
                verdict="insufficient_evidence",
                supporting_ids=(),
            )
        raise AssertionError("Synthesis must never run after abstention.")

    llm = _FakeStructuredLLM(handler)
    service = AnswerGenerationService(llm_client=llm, top_k=4)
    resp = asyncio.run(
        service.answer_chunks(
            chunks=chunks,
            document_id="doc-intel-3",
            file_name="plan.pdf",
            question="How much does a subscription cost?",
            synthesize_answer=True,
        )
    )
    assert resp.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert resp.cited_pages == ()
    assert len(llm.calls) == 2

    # Missing requested quantity (e.g., currency amount for "price") still abstains.
    def missing_qty_handler(prompt: str, model: type) -> object:
        name = model.__name__
        if name == "AnswerDraft":
            found = _extract_chunk_block(prompt, quote)
            assert found is not None
            return AnswerDraft(
                answer="Limit is 350 pages.",
                evidence=(EvidenceQuoteDraft(chunk_id=found[0], quote=quote),),
            )
        if name == "EvidenceAssessment":
            return EvidenceAssessment(
                reason="Page 2 states limits.",
                verdict="supported",
                supporting_ids=("C1",),
            )
        raise AssertionError("Synthesis must never run without requested quantity.")

    qty_llm = _FakeStructuredLLM(missing_qty_handler)
    qty_service = AnswerGenerationService(llm_client=qty_llm, top_k=4)
    qty_resp = asyncio.run(
        qty_service.answer_chunks(
            chunks=chunks,
            document_id="doc-intel-3",
            file_name="plan.pdf",
            question="How much does a license cost in USD?",
            synthesize_answer=True,
        )
    )
    assert qty_resp.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert qty_resp.cited_pages == ()
    assert len(qty_llm.calls) == 2

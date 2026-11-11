"""Regressions for false grounding, insufficient context and adapter failures."""

import asyncio
import json

import httpx
import numpy as np
import pytest

from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.adapters.llm.ollama_client import (
    OllamaClient,
    OllamaContextLimitError,
    OllamaOutputValidationError,
    OllamaProtocolError,
)
from app.schemas.answer import (
    AnswerDraft,
    AnswerStatus,
    EvidenceAssessment,
    EvidenceQuoteDraft,
)
from app.schemas.document import ExtractedPage
from app.schemas.retrieval import RetrievedChunk
from app.services.answer_generation import AnswerGenerationService
from app.services.evidence_validator import EvidenceValidationError, EvidenceValidator
from app.services.hybrid_retrieval import HybridRetrievalPipeline


def chunk(text="Orion refunds require the original receipt and take 14 days.", **kw):
    data = dict(
        chunk_id="c1",
        document_id="doc",
        file_name="policy.pdf",
        page_number=1,
        chunk_index=0,
        start_char=0,
        end_char=len(text),
        text=text,
        score=0.8,
    )
    data.update(kw)
    return RetrievedChunk(**data)


class Generator:
    def __init__(
        self,
        quote=None,
        *,
        answers=True,
        sufficient=True,
        conflicts=False,
        answer="A fabricated answer claims 9999 days.",
        evidence_id="c1",
    ):
        self.quote = (
            quote or "Orion refunds require the original receipt and take 14 days."
        )
        self.review = EvidenceAssessment(
            verdict=(
                "conflicting_evidence"
                if conflicts
                else "supported"
                if answers and sufficient
                else "insufficient_evidence"
            ),
            reason="Fixture assessment",
            supporting_ids=("C1",) if answers and sufficient and not conflicts else (),
        )
        self.answer = answer
        self.evidence_id = evidence_id
        self.calls = []

    async def generate_structured(self, *, prompt, response_model):
        self.calls.append((response_model, prompt))
        if issubclass(response_model, EvidenceAssessment):
            return self.review
        return AnswerDraft(
            answer=self.answer,
            evidence=(EvidenceQuoteDraft(chunk_id=self.evidence_id, quote=self.quote),),
        )

    async def aclose(self):
        pass


def answer(
    generator, chunks=None, *, question="How long do Orion refunds take?", **kwargs
):
    return asyncio.run(
        AnswerGenerationService(llm_client=generator, **kwargs).answer_chunks(
            chunks=chunks or (chunk(),),
            document_id="doc",
            file_name="policy.pdf",
            question=question,
        )
    )


def test_real_quote_cannot_launder_fabricated_generated_prose():
    model = Generator()
    result = answer(model)
    assert result.status == AnswerStatus.ANSWERED
    assert "9999" not in result.answer
    assert "14 days" in result.answer
    assert result.citations[0].excerpt in result.answer
    assert len(model.calls) == 2
    # The independent reviewer is not shown the generator's proposed answer.
    assert "9999" not in model.calls[1][1]


@pytest.mark.parametrize(
    "review", [dict(answers=False), dict(sufficient=False), dict(conflicts=True)]
)
def test_irrelevant_incomplete_or_conflicting_evidence_abstains(review):
    result = answer(Generator(**review))
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.answer.startswith("Out of PDF content:")
    assert not result.citations


def test_model_cannot_cite_unseen_tail_of_truncated_passage():
    text = "A " * 350 + "Secret refund duration: 900 days."
    result = answer(
        Generator(quote="Secret refund duration: 900 days."),
        chunks=(chunk(text),),
        max_context_chars=500,
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


def test_model_cannot_cite_omitted_chunk_even_if_quote_is_real():
    result = answer(
        Generator(quote="Orion refunds take 900 days.", evidence_id="c2"),
        chunks=(
            chunk("A " * 400),
            chunk("Orion refunds take 900 days.", chunk_id="c2"),
        ),
        max_context_chars=500,
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


def test_low_scoring_evidence_cannot_pass_using_an_unused_high_scoring_hit():
    result = answer(
        Generator(evidence_id="weak"),
        chunks=(chunk(score=0.9), chunk(chunk_id="weak", score=0.01)),
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "source,quote",
    [("120 days", "20 days"), ("unauthorized", "authorized"), ("tokens", "token")],
)
def test_subword_or_partial_number_quote_is_rejected(source, quote):
    with pytest.raises(EvidenceValidationError):
        EvidenceValidator((chunk(source),)).verify_quote(chunk_id="c1", quote=quote)


def test_multiple_quotes_from_one_source_keep_the_intervening_context():
    class Multiple(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceAssessment):
                return self.review
            return AnswerDraft(
                answer="irrelevant prose",
                evidence=(
                    EvidenceQuoteDraft(chunk_id="c1", quote="Orion refunds"),
                    EvidenceQuoteDraft(chunk_id="c1", quote="14 days"),
                ),
            )

    result = answer(Multiple())
    assert (
        result.citations[0].excerpt
        == "Orion refunds require the original receipt and take 14 days."
    )


def test_keyword_search_finds_exact_identifiers_and_keeps_page_positions():
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(
        (
            ExtractedPage(page_number=1, text="NIST SP 800-63A-4 is about proofing."),
            ExtractedPage(page_number=2, text=""),
            ExtractedPage(
                page_number=3, text="NIST SP 800-63B-4 describes authentication."
            ),
        ),
        document_id="doc",
        file_name="policy.pdf",
    )
    found = pipeline.search("What is NIST SP 800-63B-4 about?")
    assert found.results[0].page_number == 3
    assert pipeline.search("penguins volcanos").results == ()


def test_hybrid_search_can_find_a_paraphrase_with_no_keyword_overlap():
    class Embedder:
        def embed_texts(self, texts):
            return np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

        def embed_query(self, query):
            return np.array([0.0, 1.0], dtype=np.float32)

    pipeline = HybridRetrievalPipeline(embedder=Embedder())
    pipeline.index_pages(
        (
            ExtractedPage(page_number=1, text="Shipping timetables."),
            ExtractedPage(page_number=2, text="Credentials expire monthly."),
        ),
        document_id="doc",
        file_name="policy.pdf",
    )
    assert (
        pipeline.search("How often must passwords be renewed?").results[0].page_number
        == 2
    )


def test_embedding_overflow_encodes_the_tail_instead_of_silently_truncating():
    class Tokenizer:
        def encode(self, text, **kwargs):
            return list(range(len(text.split())))

        def decode(self, ids):
            return " ".join(map(str, ids))

        def num_special_tokens_to_add(self, **kwargs):
            return 2

    class Encoder:
        max_seq_length = 40
        tokenizer = Tokenizer()

        def encode(self, texts, **kwargs):
            self.texts = texts
            return np.array(
                [[1.0, float(i + 1)] for i in range(len(texts))], dtype=np.float32
            )

    model = Encoder()
    vectors = SentenceTransformerEmbedder(model=model).embed_texts(["word " * 100])
    assert vectors.shape == (1, 2)
    assert len(model.texts) > 1
    assert model.texts[-1].endswith("99")
    assert max(len(t.split()) for t in model.texts) <= 38


@pytest.mark.parametrize(
    "body", [dict(done=False), dict(done=True, done_reason="length")]
)
def test_truncated_ollama_output_is_rejected_even_when_json_is_valid(body):
    async def scenario():
        body["response"] = json.dumps(
            {"answer": "test", "abstain": True, "evidence": []}
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))
        ) as client:
            adapter = OllamaClient(client=client)
            with pytest.raises(OllamaProtocolError):
                await adapter.generate_structured(
                    prompt="Question", response_model=AnswerDraft
                )

    asyncio.run(scenario())


def test_context_overflow_is_rejected_before_ollama_can_silently_drop_sources():
    async def scenario():
        def forbidden(request):
            pytest.fail("Oversized context must not be sent")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(forbidden)
        ) as client:
            adapter = OllamaClient(client=client, num_ctx=2000)
            with pytest.raises(OllamaContextLimitError):
                await adapter.generate_structured(
                    prompt="A" * 4000, response_model=AnswerDraft
                )

    asyncio.run(scenario())


def test_evidence_expansion_preserves_cross_page_continuation():
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(
        (
            ExtractedPage(
                page_number=1,
                text="Orion refunds are processed under the following conditions:",
            ),
            ExtractedPage(
                page_number=2,
                text="The original receipt is required. The deadline is fourteen days.",
            ),
        ),
        document_id="doc",
        file_name="policy.pdf",
    )
    assert any(
        c.page_number == 2 for c in pipeline.search_evidence("Orion refunds").results
    )


def test_overview_questions_include_abstract_context_even_when_keywords_differ():
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(
        (
            ExtractedPage(page_number=1, text="A handbook with a general title."),
            ExtractedPage(
                page_number=2,
                text="Abstract\nIdentity, credentials, and federation are discussed.",
            ),
            ExtractedPage(
                page_number=3, text="The following main areas contain extensive detail."
            ),
        ),
        document_id="doc",
        file_name="policy.pdf",
    )
    assert any(
        c.page_number == 2
        for c in pipeline.search_evidence(
            "Which main areas does this handbook cover?"
        ).results
    )


def test_short_quote_cannot_drop_a_source_negation_even_if_reviewer_approves():
    source = "Orion accounts are not eligible for a refund. The policy is binding."
    result = answer(Generator(quote="eligible for a refund"), chunks=(chunk(source),))
    assert result.status == AnswerStatus.ANSWERED
    assert "not eligible for a refund" in result.answer
    assert (
        result.citations[0].excerpt == "Orion accounts are not eligible for a refund."
    )


def test_conflicting_numbers_are_rejected_even_if_the_model_would_approve():
    source = "Orion policy\nThe Orion refund window is 14 days."
    other = "The Orion refund window is 7 days."
    result = answer(
        Generator(quote=other, evidence_id="c2"),
        chunks=(
            chunk(source),
            chunk(other, chunk_id="c2", page_number=2),
        ),
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "different numbers" in result.answer
    assert not result.citations


def test_different_entities_are_not_treated_as_a_numeric_conflict():
    source = "The Orion refund window is 14 days."
    other = "The Lyra refund window is 30 days."
    result = answer(
        Generator(quote=source), chunks=(chunk(source), chunk(other, chunk_id="c2"))
    )
    assert result.status == AnswerStatus.ANSWERED


def test_unrelated_numeric_disagreement_does_not_invalidate_a_supported_fact():
    source = "The Orion refund window is 14 days. The shipping fee is 5 dollars."
    other = "The shipping fee is 6 dollars."
    result = answer(
        Generator(quote="The Orion refund window is 14 days."),
        chunks=(chunk(source), chunk(other, chunk_id="c2")),
    )
    assert result.status == AnswerStatus.ANSWERED


def test_numbered_product_identifiers_remain_distinct_when_comparing_facts():
    from app.schemas.answer import Citation
    from app.services.fact_consistency import has_numeric_conflict

    one = chunk("The PlanA1 refund window is 14 days.")
    two = chunk("The PlanA2 refund window is 30 days.", chunk_id="c2")
    citation = Citation(
        citation_id="c1",
        chunk_id="c1",
        document_id="doc",
        file_name="policy.pdf",
        page_number=1,
        excerpt=one.text,
    )
    assert not has_numeric_conflict(
        citations=(citation,),
        chunks=(one, two),
        question="What is the PlanA1 refund window?",
    )


def test_unverifiable_model_quote_can_recover_only_by_selecting_a_real_source_span():
    from app.schemas.answer import EvidenceSpanSelection

    class Recovery(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceSpanSelection):
                return response_model(abstain=False, evidence_ids=("S001",))
            return await super().generate_structured(
                prompt=prompt, response_model=response_model
            )

    result = answer(Recovery(quote="A model paraphrase that is not in the PDF."))
    assert result.status == AnswerStatus.ANSWERED
    assert "14 days" in result.answer
    assert "paraphrase" not in result.answer


def test_recovery_cannot_invent_or_select_a_source_id_outside_the_catalog():
    from app.schemas.answer import EvidenceSpanSelection

    class Recovery(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceSpanSelection):
                return EvidenceSpanSelection(abstain=False, evidence_ids=("invented",))
            return await super().generate_structured(
                prompt=prompt, response_model=response_model
            )

    result = answer(Recovery(quote="Absent from source"))
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert not result.citations


def test_recovery_abstention_does_not_weaken_the_evidence_requirement():
    from app.schemas.answer import EvidenceSpanSelection

    class Recovery(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceSpanSelection):
                return response_model(abstain=True, evidence_ids=())
            return await super().generate_structured(
                prompt=prompt, response_model=response_model
            )

    result = answer(Recovery(quote="Absent from source"))
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


def test_review_keeps_only_evidence_that_directly_answers_the_question():
    class Focused(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceAssessment):
                return response_model(
                    reason="Only C1 answers the requested duration.",
                    verdict="supported",
                    supporting_ids=("C1",),
                )
            return AnswerDraft(
                answer="Unverified prose",
                evidence=(
                    EvidenceQuoteDraft(
                        chunk_id="c1", quote="The Orion refund window is 14 days."
                    ),
                    EvidenceQuoteDraft(
                        chunk_id="c2", quote="Shipping fees are paid separately."
                    ),
                ),
            )

    result = answer(
        Focused(),
        chunks=(
            chunk("The Orion refund window is 14 days."),
            chunk("Shipping fees are paid separately.", chunk_id="c2"),
        ),
    )
    assert result.status == AnswerStatus.ANSWERED
    assert len(result.citations) == 1
    assert "Shipping" not in result.answer


@pytest.mark.parametrize("ids", [(), ("unknown",)])
def test_review_cannot_approve_an_empty_or_invented_evidence_set(ids):
    class InvalidReview(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceAssessment):
                return EvidenceAssessment(
                    reason="Invalid review fixture.",
                    verdict="supported",
                    supporting_ids=ids,
                )
            return await super().generate_structured(
                prompt=prompt, response_model=response_model
            )

    result = answer(InvalidReview())
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert not result.citations


def test_identical_verified_excerpts_from_overlapping_chunks_display_once():
    class Duplicates(Generator):
        async def generate_structured(self, *, prompt, response_model):
            if issubclass(response_model, EvidenceAssessment):
                return response_model(
                    reason="The two excerpts repeat the same source fact.",
                    verdict="supported",
                    supporting_ids=("C1", "C2"),
                )
            return AnswerDraft(
                answer="Ignored prose",
                evidence=(
                    EvidenceQuoteDraft(
                        chunk_id="c1", quote="The Orion refund window is 14 days."
                    ),
                    EvidenceQuoteDraft(
                        chunk_id="c2", quote="The Orion refund window is 14 days."
                    ),
                ),
            )

    result = answer(
        Duplicates(),
        chunks=(
            chunk("The Orion refund window is 14 days."),
            chunk("The Orion refund window is 14 days.", chunk_id="c2"),
        ),
    )
    assert result.status == AnswerStatus.ANSWERED
    assert len(result.citations) == 1
    assert result.answer.count("14 days") == 1


@pytest.mark.parametrize(
    "error_type", [OllamaProtocolError, OllamaOutputValidationError]
)
def test_invalid_model_output_is_a_technical_error_not_a_missing_pdf_fact(error_type):
    class BrokenModel(Generator):
        async def generate_structured(self, **kwargs):
            raise error_type("Malformed or incomplete model output")

    with pytest.raises(error_type):
        answer(BrokenModel())


@pytest.mark.parametrize(
    "text",
    [
        "Orion refunds require the original receipt.",
        "The Orion refund window is 14 days.",
    ],
)
def test_price_question_cannot_be_answered_with_a_receipt_rule_or_duration(text):
    result = answer(
        Generator(quote=text),
        chunks=(chunk(text),),
        question="How many dollars does an Orion subscription cost?",
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.answer.startswith("Out of PDF content:")


@pytest.mark.parametrize(
    "text",
    [
        "The Orion subscription costs $29.",
        "The Orion subscription costs twenty dollars.",
        "The Orion subscription is free.",
    ],
)
def test_monetary_questions_accept_explicit_prices_or_explicitly_free_service(text):
    result = answer(
        Generator(quote=text),
        chunks=(chunk(text),),
        question="How many dollars does an Orion subscription cost?",
    )
    assert result.status == AnswerStatus.ANSWERED


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The Orion refund window is 14 days.", AnswerStatus.ANSWERED),
        ("The Orion refund window is 14 hours.", AnswerStatus.INSUFFICIENT_EVIDENCE),
    ],
)
def test_explicit_time_unit_must_be_supported_without_silent_conversion(text, expected):
    result = answer(
        Generator(quote=text),
        chunks=(chunk(text),),
        question="How many days is the Orion refund window?",
    )
    assert result.status == expected


@pytest.mark.parametrize(
    "text",
    ["The Orion subscription is not free.", "There are no free Orion subscriptions."],
)
def test_not_free_does_not_establish_a_subscription_price(text):
    result = answer(
        Generator(quote=text),
        chunks=(chunk(text),),
        question="How many dollars does an Orion subscription cost?",
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


def test_physical_pounds_cannot_be_answered_with_a_free_price_statement():
    text = "The Orion package is free."
    result = answer(
        Generator(quote=text),
        chunks=(chunk(text),),
        question="How many pounds does the Orion package weigh?",
    )
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "text,question,expected",
    [
        (
            "The Orion refund window is 14days.",
            "How many days is the Orion refund window?",
            AnswerStatus.ANSWERED,
        ),
        (
            "The Orion storage limit is 12Gb.",
            "How many gigabytes is the Orion storage limit?",
            AnswerStatus.INSUFFICIENT_EVIDENCE,
        ),
        (
            "The Orion storage limit is 12GB.",
            "How many gigabytes is the Orion storage limit?",
            AnswerStatus.ANSWERED,
        ),
    ],
)
def test_quantity_units_allow_attached_text_but_preserve_byte_bit_case(
    text, question, expected
):
    result = answer(Generator(quote=text), chunks=(chunk(text),), question=question)
    assert result.status == expected

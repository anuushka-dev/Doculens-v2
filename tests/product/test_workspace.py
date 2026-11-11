"""Real PDFs, isolated parsing, session authorization and HTTP adapter contracts."""

import json
import re
from uuid import uuid4

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.adapters.llm.ollama_client import OllamaClient
from app.api.routes import qa, workspace
from app.core.config import Settings
from app.main import app
from app.schemas.document import ExtractedPage, PDFExtractionResult
from app.services.answer_generation import AnswerGenerationService
from app.services.document_sessions import (
    DocumentSessionStore,
    SessionCapacityError,
    SessionNotFoundError,
)
from app.services.hybrid_retrieval import HybridRetrievalPipeline


def pdf(*texts, encrypted=False):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_textbox((50, 50, 550, 750), text, fontsize=11)
        if encrypted:
            return document.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
            )
        return document.tobytes()


@pytest.fixture
def client(monkeypatch):
    settings = Settings(_env_file=None, retrieval_mode="lexical")
    store = DocumentSessionStore()
    monkeypatch.setattr(workspace, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace, "get_session_store", lambda: store)
    monkeypatch.setattr(qa, "get_settings", lambda: settings)
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if "verdict" in payload["format"]["properties"]:
            value = dict(
                verdict="supported",
                supporting_ids=["C1"],
                reason="Test fixture",
            )
        else:
            chunk_id = re.search(r"\[chunk_id=([^ |]+)", payload["prompt"])[1]
            value = {
                "answer": "The model invented 9999 days.",
                "abstain": False,
                "evidence": [
                    {
                        "chunk_id": chunk_id,
                        "quote": "The Orion refund window is 14 days.",
                    }
                ],
            }
        return httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "response": json.dumps(value)},
        )

    async def answer_service():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            service = AnswerGenerationService(llm_client=OllamaClient(client=http))
            yield service
            await service.aclose()

    app.dependency_overrides[qa.get_answer_generation_service] = answer_service
    with TestClient(app) as test:
        test.model_calls = calls
        yield test
    app.dependency_overrides.clear()
    store.clear()


def upload(client, content=None):
    response = client.post(
        "/api/documents",
        files={
            "file": (
                "policy.pdf",
                content
                or pdf(
                    "The Orion refund window is 14 days.\nRefunds require the original receipt.",
                    "The Lyra refund window is 30 days.\nLyra accounts use a separate billing policy.",
                ),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def ask(client, session, question="What is the Orion refund window?", token=None):
    return client.post(
        f"/api/documents/{session['document_id']}/ask",
        headers={"X-Document-Token": token or session["document_token"]},
        json={"question": question},
    )


def test_upload_ask_twice_reuses_index_and_answers_with_real_pdf_evidence(
    client, monkeypatch
):
    indexed = []
    original = HybridRetrievalPipeline.index_pages

    def count(self, *args, **kwargs):
        indexed.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HybridRetrievalPipeline, "index_pages", count)
    session = upload(client)
    for _ in range(2):
        response = ask(client, session)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "answered"
        assert "14 days" in result["answer"] and "9999" not in result["answer"]
        assert result["citations"][0]["page_number"] == 1
        assert result["citations"][0]["document_id"] == session["document_id"]
    assert indexed == [True]
    assert len(client.model_calls) == 4


def test_unrelated_question_returns_out_of_pdf_content_without_model_call(client):
    session = upload(client)
    result = ask(client, session, "Who won Wimbledon?").json()
    assert result["status"] == "insufficient_evidence"
    assert result["answer"].startswith("Out of PDF content:")
    assert result["citations"] == []
    assert client.model_calls == []


def test_document_id_alone_does_not_grant_access_and_other_session_token_fails(client):
    first, second = upload(client), upload(client)
    assert ask(client, first, token=second["document_token"]).status_code == 404
    assert (
        client.post(
            f"/api/documents/{first['document_id']}/ask", json={"question": "refund"}
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/documents/{first['document_id']}/pages/1").status_code == 404
    )
    assert client.delete(f"/api/documents/{first['document_id']}").status_code == 404


def test_read_source_page_then_remove_document(client):
    session = upload(client)
    path = f"/api/documents/{session['document_id']}"
    headers = {"X-Document-Token": session["document_token"]}
    response = client.get(path + "/pages/2", headers=headers)
    assert response.status_code == 200
    assert "Lyra" in response.json()["text"]
    assert response.headers["cache-control"] == "no-store"
    assert client.get(path + "/pages/99", headers=headers).status_code == 404
    assert client.delete(path, headers=headers).status_code == 204
    assert ask(client, session).status_code == 404


@pytest.mark.parametrize("question", [" ", "x" * 2001, 1])
def test_invalid_question_is_rejected(client, question):
    assert ask(client, upload(client), question).status_code == 422


@pytest.mark.parametrize(
    "content,code",
    [
        (b"bad bytes", "invalid_pdf"),
        (pdf(""), "no_extractable_text"),
        (pdf("Private text", encrypted=True), "encrypted_pdf"),
    ],
)
def test_isolated_parser_rejects_unsupported_documents(client, content, code):
    response = client.post(
        "/api/documents", files={"file": ("bad.pdf", content, "application/pdf")}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_mixed_pdf_reports_unread_pages_without_shifting_page_numbers(client):
    session = upload(
        client,
        pdf(
            "The Orion refund window is 14 days.", "", "Third page has selectable text."
        ),
    )
    assert session["page_count"] == 3
    assert any("2" in warning for warning in session["warnings"])


def test_large_request_is_rejected_before_multipart_parsing(client):
    response = client.post(
        "/api/documents", headers={"Content-Length": str(22 * 1024 * 1024)}, content=b""
    )
    assert response.status_code == 413


def test_ui_and_assets_are_self_contained(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Ask DocuLens" in response.text
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in response.headers
    assert response.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    for path in [
        "/assets/styles.css",
        "/assets/styles/tokens.css",
        "/assets/styles/workspace.css",
        "/assets/src/main.js",
        "/assets/src/services/apiClient.js",
        "/assets/src/state/store.js",
        "/assets/src/utils/validation.js",
    ]:
        assert client.get(path).status_code == 200


def test_readiness_and_status_report_configured_limits(client, monkeypatch):
    from app import main as app_main

    async def fake_ready(_settings):
        return True, "Model is available."

    monkeypatch.setattr(app_main, "check_ollama_model_status", fake_ready)
    ready_ok = client.get("/ready")
    assert ready_ok.status_code == 200
    assert ready_ok.json()["status"] == "ready"

    async def fake_not_ready(_settings):
        return False, "Ollama offline."

    monkeypatch.setattr(app_main, "check_ollama_model_status", fake_not_ready)
    ready_fail = client.get("/ready")
    assert ready_fail.status_code == 503
    assert ready_fail.json()["status"] == "not_ready"

    monkeypatch.setattr(workspace, "check_ollama_model_status", fake_ready)
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["max_pdf_pages"] == 350
    assert body["max_extracted_chars"] == 4_000_000
    assert body["max_cached_documents"] == 8


def test_busy_service_returns_retryable_error_and_retains_healthy_session(client):
    session = upload(client)
    workspace._work_slots.acquire()
    workspace._work_slots.acquire()
    try:
        assert ask(client, session).status_code == 429
    finally:
        workspace._work_slots.release()
        workspace._work_slots.release()
    assert ask(client, session).status_code == 200


def session_objects():
    extraction = PDFExtractionResult(
        document_id=uuid4(),
        filename="test.pdf",
        sha256="a" * 64,
        pages=(ExtractedPage(page_number=1, text="Source content for session tests."),),
    )
    pipeline = HybridRetrievalPipeline(mode="lexical")
    pipeline.index_pages(
        extraction.pages, document_id=str(extraction.document_id), file_name="test.pdf"
    )
    return extraction, pipeline


def test_sessions_expire_and_cannot_be_accessed_with_an_old_token():
    now = [0.0]
    store = DocumentSessionStore(ttl=60, clock=lambda: now[0])
    extraction, pipeline = session_objects()
    token = store.add(extraction, pipeline)
    assert store.get(str(extraction.document_id), token).pipeline is pipeline
    now[0] = 60.0
    with pytest.raises(SessionNotFoundError):
        store.get(str(extraction.document_id), token)


def test_capacity_and_memory_budget_are_enforced_without_evicting_active_documents():
    store = DocumentSessionStore(capacity=1)
    extraction, pipeline = session_objects()
    token = store.add(extraction, pipeline)
    with pytest.raises(SessionCapacityError):
        store.add(*session_objects())
    assert store.get(str(extraction.document_id), token)
    with pytest.raises(SessionCapacityError):
        DocumentSessionStore(max_bytes=1).add(*session_objects())


def test_streamed_request_without_content_length_still_enforces_body_limit(
    client, monkeypatch
):
    from app.core import http_limits

    settings = Settings(_env_file=None, max_upload_bytes=1024)
    monkeypatch.setattr(http_limits, "get_settings", lambda: settings)
    chunks = iter(
        (
            b'--limit\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\n\r\n',
            b"x" * 100_000,
            b"\r\n--limit--\r\n",
        )
    )
    response = client.post(
        "/api/documents",
        content=chunks,
        headers={"Content-Type": "multipart/form-data; boundary=limit"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "REQUEST_TOO_LARGE"

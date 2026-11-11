"""Browser workspace: upload once, ask repeatedly, view source pages, remove."""

from __future__ import annotations

import asyncio
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.embeddings.sentence_transformer import EmbeddingError
from app.adapters.llm.ollama_client import OllamaClientError
from app.adapters.pdf.extractor import PDFExtractionError
from app.api.routes.documents import _read_upload_limited
from app.api.routes.qa import (
    _raise_llm_http_error,
    _raise_pdf_http_error,
    get_answer_generation_service,
)
from app.core.config import get_settings
from app.schemas.answer import AnswerResponse
from app.services.answer_generation import AnswerGenerationService
from app.services.document_sessions import (
    SessionCapacityError,
    SessionNotFoundError,
    get_session_store,
)
from app.services.hybrid_retrieval import HybridRetrievalPipeline
from app.services.isolated_ingestion import ingest_isolated

router = APIRouter(prefix="/api", tags=["workspace"])
_work_slots = BoundedSemaphore(2)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000, strict=True)

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The question must not be blank.")
        return value.strip()


def _session(document_id: UUID, token: str | None):
    try:
        return get_session_store().get(str(document_id), token)
    except SessionNotFoundError as error:
        raise HTTPException(
            404, detail={"code": "SESSION_UNAVAILABLE", "message": str(error)}
        ) from error


def _admit() -> None:
    if not _work_slots.acquire(blocking=False):
        raise HTTPException(
            429,
            detail={
                "code": "BUSY",
                "message": "The service is busy. Please try again shortly.",
            },
        )


@router.get("/status")
async def workspace_status() -> dict:
    settings = get_settings()
    ready = False
    message = "Start Ollama and pull the configured model to enable answers."
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            names = {
                m.get("name")
                for m in response.json().get("models", [])
                if isinstance(m, dict)
            }
            ready = (
                settings.ollama_model in names
                or settings.ollama_model + ":latest" in names
            )
            if ready:
                message = "Model is available. Answers use verified PDF excerpts."
            else:
                message = (
                    "Ollama is running. Pull the configured model to enable answers."
                )
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return {
        "model": settings.ollama_model,
        "model_ready": ready,
        "message": message,
        "retrieval_mode": settings.retrieval_mode,
        "max_upload_bytes": settings.max_upload_bytes,
        "max_pdf_pages": settings.max_pdf_pages,
        "session_ttl_seconds": settings.document_ttl_seconds,
    }


@router.post("/documents", status_code=201)
async def upload_document(file: Annotated[UploadFile, File()]) -> dict:
    settings = get_settings()
    admitted = False
    try:
        _admit()
        admitted = True
        content = await _read_upload_limited(file, settings.max_upload_bytes)
        extraction = await ingest_isolated(content, file.filename or "", settings)
        pipeline = HybridRetrievalPipeline(mode=settings.retrieval_mode)
        await asyncio.to_thread(
            pipeline.index_pages,
            extraction.pages,
            document_id=str(extraction.document_id),
            file_name=extraction.filename,
        )
        token = get_session_store().add(extraction, pipeline)
        warnings = []
        unread = sorted(
            set(extraction.empty_page_numbers + extraction.near_empty_page_numbers)
        )
        if unread:
            warnings.append(
                "Some pages contain little or no selectable text: "
                + ", ".join(map(str, unread))
                + ". OCR is not enabled; answers may be incomplete."
            )
        if settings.retrieval_mode == "lexical":
            warnings.append(
                "Keyword-only search is enabled; paraphrased questions may be missed."
            )
        return {
            "document_id": str(extraction.document_id),
            "document_token": token,
            "filename": extraction.filename,
            "page_count": extraction.page_count,
            "chunk_count": len(pipeline.records),
            "expires_in_seconds": settings.document_ttl_seconds,
            "warnings": warnings,
        }
    except PDFExtractionError as error:
        _raise_pdf_http_error(error)
    except TimeoutError as error:
        raise HTTPException(
            504,
            detail={
                "code": "PDF_TIMEOUT",
                "message": "The PDF took too long to process. Try a smaller document.",
            },
        ) from error
    except EmbeddingError as error:
        raise HTTPException(
            503,
            detail={
                "code": "EMBEDDING_UNAVAILABLE",
                "message": "The semantic search model could not load. Download the embedding model first or explicitly select lexical mode.",
            },
        ) from error
    except SessionCapacityError as error:
        raise HTTPException(
            503, detail={"code": "SESSION_CAPACITY", "message": str(error)}
        ) from error
    finally:
        await file.close()
        if admitted:
            _work_slots.release()


@router.post("/documents/{document_id}/ask", response_model=AnswerResponse)
async def ask_cached_document(
    document_id: UUID,
    body: Question,
    service: Annotated[AnswerGenerationService, Depends(get_answer_generation_service)],
    x_document_token: Annotated[str | None, Header(max_length=200)] = None,
) -> AnswerResponse:
    session = _session(document_id, x_document_token)
    _admit()
    try:
        chunks = await asyncio.to_thread(
            session.pipeline.search_evidence,
            body.question,
            top_k=get_settings().retrieval_top_k,
        )
        pages = {p.page_number: p.text for p in session.extraction.pages}
        if any(
            c.document_id != str(document_id)
            or c.file_name != session.extraction.filename
            or pages.get(c.page_number, "")[c.start_char : c.end_char] != c.text
            for c in chunks.results
        ):
            raise HTTPException(
                500,
                detail={
                    "code": "SOURCE_MISMATCH",
                    "message": "Source verification failed. Upload the PDF again.",
                },
            )
        return await service.answer_chunks(
            chunks=chunks.results,
            document_id=str(document_id),
            file_name=session.extraction.filename,
            question=body.question,
        )
    except OllamaClientError as error:
        _raise_llm_http_error(error)
    except EmbeddingError as error:
        raise HTTPException(
            503,
            detail={
                "code": "EMBEDDING_UNAVAILABLE",
                "message": "Semantic search is unavailable. Please retry.",
            },
        ) from error
    finally:
        _work_slots.release()


@router.get("/documents/{document_id}/pages/{page_number}")
def get_source_page(
    document_id: UUID,
    page_number: int,
    x_document_token: Annotated[str | None, Header(max_length=200)] = None,
) -> dict:
    session = _session(document_id, x_document_token)
    if not 1 <= page_number <= len(session.extraction.pages):
        raise HTTPException(
            404,
            detail={
                "code": "PAGE_UNAVAILABLE",
                "message": "This PDF page does not exist.",
            },
        )
    page = session.extraction.pages[page_number - 1]
    return {"page_number": page.page_number, "text": page.text}


@router.delete("/documents/{document_id}", status_code=204)
def remove_document(
    document_id: UUID,
    x_document_token: Annotated[str | None, Header(max_length=200)] = None,
) -> Response:
    _session(document_id, x_document_token)
    try:
        get_session_store().delete(str(document_id), x_document_token)
    except SessionNotFoundError:
        pass
    return Response(status_code=204)

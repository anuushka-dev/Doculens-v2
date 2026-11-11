"""Bounded, expiring document sessions for the local single-worker product."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock

from app.core.config import get_settings
from app.schemas.document import PDFExtractionResult
from app.services.hybrid_retrieval import HybridRetrievalPipeline


class SessionNotFoundError(LookupError):
    pass


class SessionCapacityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentSession:
    extraction: PDFExtractionResult
    pipeline: HybridRetrievalPipeline
    token_hash: bytes
    expires_at: float
    size_bytes: int


class DocumentSessionStore:
    def __init__(
        self,
        *,
        ttl: int = 3600,
        capacity: int = 8,
        max_bytes: int = 64 * 1024 * 1024,
        clock=time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.capacity = capacity
        self.max_bytes = max_bytes
        self.clock = clock
        self._items: dict[str, DocumentSession] = {}
        self._lock = RLock()

    def _purge(self) -> None:
        now = self.clock()
        for key in tuple(self._items):
            if self._items[key].expires_at <= now:
                del self._items[key]

    def add(
        self, extraction: PDFExtractionResult, pipeline: HybridRetrievalPipeline
    ) -> str:
        token = secrets.token_urlsafe(32)
        # Include duplicated overlapping chunk text and dense vectors in budget.
        size = sum(len(p.text.encode("utf-8")) for p in extraction.pages)
        size += sum(len(r.text.encode("utf-8")) for r in pipeline.records)
        size += getattr(pipeline.vectors, "nbytes", 0)
        with self._lock:
            self._purge()
            if (
                len(self._items) >= self.capacity
                or sum(x.size_bytes for x in self._items.values()) + size
                > self.max_bytes
            ):
                raise SessionCapacityError(
                    "Document capacity reached. Remove a document or try later."
                )
            key = str(extraction.document_id)
            if key in self._items:
                raise SessionCapacityError("This document session already exists.")
            self._items[key] = DocumentSession(
                extraction,
                pipeline,
                hashlib.sha256(token.encode()).digest(),
                self.clock() + self.ttl,
                size,
            )
        return token

    def get(self, document_id: str, token: str | None) -> DocumentSession:
        with self._lock:
            self._purge()
            item = self._items.get(document_id)
            if (
                item is None
                or token is None
                or not secrets.compare_digest(
                    item.token_hash, hashlib.sha256(token.encode()).digest()
                )
            ):
                raise SessionNotFoundError(
                    "Document unavailable or session expired. Upload the PDF again."
                )
            return item

    def delete(self, document_id: str, token: str | None) -> None:
        with self._lock:
            self.get(document_id, token)
            del self._items[document_id]

    def purge_expired(self) -> None:
        with self._lock:
            self._purge()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


@lru_cache(maxsize=1)
def get_session_store() -> DocumentSessionStore:
    settings = get_settings()
    return DocumentSessionStore(
        ttl=settings.document_ttl_seconds,
        capacity=settings.max_cached_documents,
        max_bytes=settings.max_cached_text_bytes,
    )

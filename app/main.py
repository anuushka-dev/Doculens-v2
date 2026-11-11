"""DocuLens local application: browser workspace and compatible HTTP APIs."""

import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.embeddings.sentence_transformer import EmbeddingError
from app.adapters.vectorstore.faiss_store import FaissStoreError
from app.api.routes.documents import router as documents_router
from app.api.routes.qa import router as qa_router
from app.api.routes.workspace import check_ollama_model_status
from app.api.routes.workspace import router as workspace_router
from app.core.config import get_settings
from app.core.http_limits import UploadBodyLimit
from app.core.logging import configure_logging
from app.core.paths import resolve_frontend_dir
from app.schemas.health import HealthResponse
from app.services.document_sessions import get_session_store

logger = logging.getLogger("app.main")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "DocuLens starting (env=%s, mode=%s, model=%s, max_pages=%d)",
        settings.environment,
        settings.retrieval_mode,
        settings.ollama_model,
        settings.max_pdf_pages,
    )

    async def reap():
        while True:
            await asyncio.sleep(30)
            get_session_store().purge_expired()

    cleanup = asyncio.create_task(reap())
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup
        get_session_store().clear()
        logger.info("DocuLens shutdown complete.")


app = FastAPI(
    title="DocuLens",
    description="PDF questions with verified source excerpts.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(UploadBodyLimit)
app.include_router(documents_router)
app.include_router(qa_router)
app.include_router(workspace_router)
FRONTEND_DIR = resolve_frontend_dir()
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


@app.middleware("http")
async def response_headers(request: Request, call_next):
    incoming_id = request.headers.get("X-Request-ID", "")
    request_id = (
        incoming_id if _SAFE_REQUEST_ID.match(incoming_id) else uuid4().hex
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-src blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
    return response


@app.get("/", include_in_schema=False)
def workspace():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Process liveness; model availability is reported separately by /ready and /api/status."""
    return HealthResponse(status="ok", service="doculens-api")


@app.get("/ready", tags=["health"])
async def readiness_check():
    """Deployment readiness check verifying Ollama and the configured model."""
    settings = get_settings()
    ready, message = await check_ollama_model_status(settings)
    if not ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "doculens-api",
                "model": settings.ollama_model,
                "retrieval_mode": settings.retrieval_mode,
                "message": message,
            },
        )
    return {
        "status": "ready",
        "service": "doculens-api",
        "model": settings.ollama_model,
        "retrieval_mode": settings.retrieval_mode,
    }


@app.exception_handler(EmbeddingError)
async def embedding_unavailable(request: Request, error: EmbeddingError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "EMBEDDING_UNAVAILABLE",
                "message": "The semantic search model is unavailable. Check the model setup and retry.",
            }
        },
    )


@app.exception_handler(FaissStoreError)
async def index_unavailable(request: Request, error: FaissStoreError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "INDEX_UNAVAILABLE",
                "message": "The document search index is unavailable. Please retry.",
            }
        },
    )

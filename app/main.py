"""DocuLens local application: browser workspace and compatible HTTP APIs."""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.embeddings.sentence_transformer import EmbeddingError
from app.adapters.vectorstore.faiss_store import FaissStoreError
from app.api.routes.documents import router as documents_router
from app.api.routes.qa import router as qa_router
from app.api.routes.workspace import router as workspace_router
from app.core.http_limits import UploadBodyLimit
from app.schemas.health import HealthResponse
from app.services.document_sessions import get_session_store


@asynccontextmanager
async def lifespan(application: FastAPI):
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
WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-src blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
    return response


@app.get("/", include_in_schema=False)
def workspace():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Process liveness; model availability is reported separately by /api/status."""
    return HealthResponse(status="ok", service="doculens-api")


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

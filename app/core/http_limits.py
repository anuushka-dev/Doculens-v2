"""Bound multipart requests before the parser spools an unbounded body."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.core.config import get_settings


class BodyLimitExceeded(MultiPartException):
    pass


class UploadBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        upload = scope["method"] == "POST" and (
            path
            in {
                "/api/documents",
                "/documents/ask",
                "/documents/extract",
                "/documents/extract-structured",
            }
        )
        limit = get_settings().max_upload_bytes + 65536 if upload else 65536
        bounded = upload or (scope["method"] == "POST" and path.startswith("/api/"))
        if not bounded:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        error = JSONResponse(
            {
                "detail": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": "The request exceeds the upload limit.",
                }
            },
            status_code=413,
        )
        if length > limit:
            return await error(scope, receive, send)
        total = 0
        exceeded = False
        error_sent = False

        async def limited_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    exceeded = True
                    raise BodyLimitExceeded(
                        "Request body exceeds the configured limit."
                    )
            return message

        async def limited_send(message):
            nonlocal error_sent
            # FastAPI may translate a body-reader exception into HTTP 400.
            # Preserve the accurate size error even when that happens.
            if exceeded:
                if not error_sent:
                    error_sent = True
                    await error(scope, receive, send)
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except BodyLimitExceeded:
            if not error_sent:
                await error(scope, receive, send)

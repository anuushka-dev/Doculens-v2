"""Parse each PDF in a child process; protect the event loop and parser state."""

import asyncio
import json
import sys

from app.adapters.pdf.extractor import PDFExtractionError, PDFTooLargeError
from app.core.config import Settings
from app.schemas.document import PDFExtractionResult


async def ingest_isolated(
    pdf_bytes: bytes, filename: str, settings: Settings
) -> PDFExtractionResult:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.services.pdf_worker",
        filename,
        str(settings.max_upload_bytes),
        str(getattr(settings, "max_pdf_pages", 350)),
        str(getattr(settings, "max_extracted_chars", 4_000_000)),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(pdf_bytes), timeout=60)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise PDFExtractionError("The PDF could not be processed safely.")
    try:
        body = json.loads(stdout)
        if "error" in body:
            detail = body["error"]
            cls = (
                PDFTooLargeError
                if detail["code"] in {"pdf_too_large", "pdf_page_limit_exceeded"}
                else PDFExtractionError
            )
            error = cls(detail["message"])
            error.code = detail["code"]
            raise error
        return PDFExtractionResult.model_validate(body["result"])
    except (ValueError, KeyError, TypeError) as error:
        raise PDFExtractionError(
            "The PDF parser returned an invalid result."
        ) from error

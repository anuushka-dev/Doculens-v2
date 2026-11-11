"""Isolated PDF parsing entry point; stdin is bytes, stdout is bounded JSON."""

import json
import sys

import pymupdf

from app.adapters.pdf.extractor import PDFExtractionError, extract_pdf_bytes


def main() -> None:
    filename, max_bytes, max_pages, max_chars = sys.argv[1:]
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        result = extract_pdf_bytes(
            sys.stdin.buffer.read(int(max_bytes) + 1),
            filename,
            max_upload_bytes=int(max_bytes),
            max_pdf_pages=int(max_pages),
            max_extracted_chars=int(max_chars),
        )
        output = {
            "result": {
                "document_id": str(result.document_id),
                "filename": result.filename,
                "sha256": result.sha256,
                "pages": [
                    {"page_number": p.page_number, "text": p.text} for p in result.pages
                ],
            }
        }
    except PDFExtractionError as error:
        output = {"error": {"code": error.code, "message": str(error)}}
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()

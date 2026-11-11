# DocuLens 0.2.0

Upload a PDF, ask a question, and inspect the exact passages and PDF pages behind the answer. Questions without sufficient document evidence return **“Out of PDF content”** rather than an answer from general knowledge.

This rebuild prioritizes traceable source text over fluent generated prose. Answers consist of **verified PDF excerpts**, selected by a model and checked by a separate relevance/sufficiency review. The review keeps only supporting citations. If a model miscopies a quote, one recovery attempt lets it select enumerated source-sentence IDs; the application supplies the original text. Model-written draft answers are never returned as document facts. This prevents fabricated prose from being attached to an otherwise genuine citation. It does not guarantee that retrieval or the model's relevance judgment is always correct.

## Start locally

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com/) (tested version 0.40.16). No paid API key is required. Python installs use CPU PyTorch wheels.

1. Stop any existing Ollama server or desktop instance, then start it in a separate terminal with bounded memory settings. For Linux/macOS:

   ```bash
   LLAMA_ARG_CACHE_RAM=0 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
   ```

   For Windows PowerShell:

   ```powershell
   $env:LLAMA_ARG_CACHE_RAM="0"
   $env:OLLAMA_NUM_PARALLEL="1"
   $env:OLLAMA_MAX_LOADED_MODELS="1"
   ollama serve
   ```

   These variables belong to the **Ollama server process**; putting them only in the API's `.env` does not configure an already running Ollama server.
2. Download the configured language model:

   ```bash
   ollama pull qwen3.5:4b
   ```

3. From this project's folder:

   ```bash
   cp .env.example .env
   uv sync --locked --dev
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
   ```

4. Open **http://127.0.0.1:8000**. The connection badge reports whether Ollama has the configured model. Upload a text-selectable PDF, then ask a specific question. Click a source card to see the highlighted extracted page or the original PDF.

CPU memory defaults are deliberately bounded: 16,384 context tokens, 8,000 source characters and a prompt batch of 128. Compose uses the tested Ollama image, runs one generation/model at a time, and disables the upstream host prompt cache. The startup commands above apply the same cache setting locally. Without this setting, repeated independent requests can accumulate several GiB of prompt snapshots on the tested Ollama version. Increasing context or batch sizes increases memory use; validate changes on your own machine. CPU checks can take several minutes.

The first hybrid-search upload downloads `sentence-transformers/all-MiniLM-L6-v2`. This is separate from the Ollama model. Internet is needed for these initial downloads; inference then runs locally. Do not close the terminal running the API. On Windows, copy `.env.example` to `.env` using Explorer or PowerShell instead of `cp` if necessary.

If the embedding model cannot download, the API gives a clear error. You can explicitly set `DOCULENS_RETRIEVAL_MODE=lexical` in `.env` and restart for keyword-only retrieval. The interface labels that mode; it is less suitable for paraphrased questions. Search never silently changes modes.

The default is `qwen3.5:4b`, exercised with real Ollama 0.40.16 on CPU. The original 2B model made an incorrect relevance judgment in live testing, so the rebuild uses the larger default and independent quantity/unit checks. The repair report contains the small acceptance-test and real-PDF results; these are not a broad accuracy benchmark. Test representative PDFs on your hardware before relying on model relevance decisions. `DOCULENS_OLLAMA_MODEL` must exactly match a model pulled into Ollama.

## Docker Compose

```bash
docker compose up -d --build
docker compose exec ollama ollama pull qwen3.5:4b
```

Open http://127.0.0.1:8000 (or `http://127.0.0.1:${DOCULENS_PORT}` if overridden in `.env`). If you change the model in `.env`, pull that same model name. Compose includes Ollama on an internal service address with a health check and a writable, persistent embedding cache. Only the browser API's localhost port is exposed. Model volumes persist; uploaded document sessions do not. `GET /health` checks process liveness, `GET /ready` checks Ollama/model readiness (`200` or `503`), and `/api/status` reports model availability and active limits.

## What is supported

- One English, text-selectable PDF per browser workspace; upload once and ask repeatedly.
- Default limits: 20 MiB, 350 pages and 4 million extracted characters.
- Semantic search plus BM25 keywords, with bounded adjacent-page and overview context.
- Exact source excerpts, original one-based PDF page positions, source-page text and a browser PDF viewer.
- Explicit abstention for missing or unverifiable evidence, including unrelated questions.
- Expiring sessions, document removal, source isolation and token-protected session APIs.
- The existing extraction and structured-metadata API routes remain available.

Scanned PDFs need OCR before upload. Image-only documents are rejected; mixed documents show warnings for empty or very short pages. Diagrams, mathematical layout and complex tables are not reliably interpreted. PDF page positions may differ from printed page numbers. Original-PDF display depends on browser PDF support; extracted-page text is also available. Each question is independent: use explicit names instead of “it” or “the previous answer.” Retrieval covers selected passages, so absence of an answer is not proof that the entire document lacks the information. Exhaustive requests may abstain.

Sessions expire after one hour by default, or on server restart. Expired access is denied immediately; a cleanup task releases expired sessions periodically. Closing/reloading the page loses its session key. Source files are held by the browser; extracted text and indexes are kept in bounded server memory. Run **one application worker**. This is a local application, without user accounts, shared persistent storage or public-service authentication.

## Verification

```bash
uv run pytest -q
uv run ruff check .
uv run python -m scripts.evaluate_retrieval --output data/retrieval-validation.json
```

Optional frontend syntax and DOM behavior tests require Node.js 20+:

```bash
npm ci --ignore-scripts
npm run check
npm test
```

The browser workspace lives in the modular [frontend/](frontend/index.html) package (`frontend/styles/` and `frontend/src/`). A comprehensive PDF guide covering architecture, design decisions, trade-offs, system flows, verification evidence, setup, and limit tuning is available in [documentation/DocuLens-v2-Technical-and-Operations-Guide.pdf](documentation/DocuLens-v2-Technical-and-Operations-Guide.pdf) (reproducible via `uv run python documentation/generate_guide_pdf.py`).

These are DOM tests, not a substitute for visual or real-browser acceptance testing. The included [repair report](docs/REPAIR-REPORT-v0.2.0.md) distinguishes completed tests from checks that were unavailable.

To evaluate the real language model after setup:

```bash
uv run python -m scripts.evaluate_product --output data/live-model-validation.json
```

This sends synthetic PDFs to the running local application and tests supported questions, unrelated/missing facts, prompt injection and conflicting evidence. Inspect the saved answers and citations manually too. The command exits unsuccessfully if a case or request fails. These are acceptance checks, not a general accuracy percentage. CPU model checks can take several minutes. The checked-in reports record the actual release validation.

## HTTP API

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Browser workspace |
| GET | `/health` | Process liveness |
| GET | `/ready` | Deployment readiness (Ollama + configured model) |
| GET | `/api/status` | Model availability and limits |
| POST | `/api/documents` | Upload PDF; return session ID and secret token |
| POST | `/api/documents/{id}/ask` | Ask `{"question":"..."}` using the existing index |
| GET | `/api/documents/{id}/pages/{n}` | Original extracted page text |
| DELETE | `/api/documents/{id}` | Remove a document session |
| POST | `/documents/extract` | Compatible page-text extraction endpoint |
| POST | `/documents/ask` | Compatible upload-per-question endpoint |
| POST | `/documents/extract-structured` | Compatible fixed-schema metadata extraction |

All cached-document routes require `X-Document-Token`, returned only at upload. A document ID alone grants no access. Keep tokens out of URLs and logs. Swagger API documentation is at `/docs`.

Configuration is documented in `.env.example`. Retrieval scores are ranking signals, never confidence percentages. Exact quote checking proves provenance against extracted text; the separate model review assesses relevance and sufficiency and can still make mistakes.

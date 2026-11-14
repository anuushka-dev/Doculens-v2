# DocuLens v2

**Evidence-first PDF Question Answering with Intelligent Retrieval and Verified Citations**

DocuLens is a locally hosted PDF question-answering application built with **Python, FastAPI, Ollama, FAISS, Sentence Transformers, and JavaScript**.

Upload a PDF, ask questions in natural language, and receive answers supported by document evidence, with references to the original PDF pages.

The application prioritizes source verification over unsupported model-generated answers.

## Features

- **PDF Question Answering:** Upload a text-selectable PDF and ask questions about its contents.
- **Intelligent Follow-up Questions:** Use recent conversation history to resolve references such as "it," "that," and "the previous answer."
- **Hybrid Retrieval:** Combine semantic similarity using Sentence Transformers and FAISS with BM25 keyword search.
- **Grounded Answer Synthesis:** Optionally generate concise answers from verified source passages, with validation and fallback to original excerpts.
- **Source Citations:** Inspect supporting excerpts and their PDF page numbers.
- **Hallucination Reduction:** Return "Out of PDF content" when sufficient evidence cannot be established.
- **Interactive Workspace:** Upload documents, view conversations, and navigate cited PDF pages.
- **Local AI Processing:** Run inference through Ollama without a paid cloud API key.
- **Docker Support:** Run the application and Ollama through Docker Compose.
- **Automated Testing:** Python, JavaScript, API, and retrieval tests.

Grounding and relevance checks reduce unsupported answers but do not guarantee complete factual accuracy.

---

## 1. Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| Web server | Uvicorn |
| Frontend | HTML, CSS, JavaScript |
| Language model | Ollama (`qwen3.5:4b`) |
| Embedding model | `all-MiniLM-L6-v2` |
| Vector search | FAISS |
| Keyword search | BM25 |
| PDF extraction | PyMuPDF |
| Package manager | uv |
| Testing | Pytest, Ruff, Node.js |
| Containers | Docker, Docker Compose |
| CI | GitHub Actions |

## 2. Prerequisites

Install the following tools before starting the project.

| Requirement | Version / Notes |
|---|---|
| Python | 3.12 |
| Git | Recent version |
| uv | Python package and environment manager |
| Ollama | Project tested with 0.40.16 |
| Node.js | 20+ for frontend tests |
| Docker | Optional, for container deployment |
| Docker Compose | Optional, for container deployment |

Official installation resources:

- [Python](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Ollama](https://ollama.com/download)
- [Node.js](https://nodejs.org/)
- [Docker](https://docs.docker.com/get-docker/)

Verify the required tools:

```bash
python3.12 --version
git --version
uv --version
ollama --version
```

On Windows, use `py -3.12 --version` if the Python launcher is installed.

## 3. Clone the Repository

Open a terminal and run:

```bash
git clone -b final-release https://github.com/anuushka-dev/Doculens-v2.git

cd Doculens-v2
```

Verify the checked-out branch:

```bash
git branch --show-current
```

Expected output:

```text
final-release
```

## 4. Create the Python Virtual Environment

The project uses `uv` for dependency management.

For this setup, the virtual environment is named **`doculens`** rather than the default `.venv`.

### Step 4.1 — Ignore the virtual environment

Before creating the environment, make sure both `.gitignore` and `.dockerignore` contain:

```gitignore
doculens/
```

This prevents Python dependencies from being committed to Git or included in Docker build contexts.

### Step 4.2 — Create the environment (Linux/macOS)

From the project root:

```bash
uv venv doculens --python 3.12
```

Activate:

```bash
source doculens/bin/activate
```

Your terminal should show something similar to:

```text
(doculens) user@machine:~/projects/Doculens-v2$
```

Check the Python executable:

```bash
python --version
which python
```

The Python executable should be inside the `doculens` virtual environment.

### Step 4.3 — Create the environment (Windows PowerShell)

```powershell
uv venv doculens --python 3.12
```

Activate it:

```powershell
.\doculens\Scripts\Activate.ps1
```

Check:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

If PowerShell blocks activation, consult Microsoft's execution-policy documentation. You can also run the environment's Python executable directly without activating it.

### Step 4.4 — Install dependencies

`uv` normally uses `.venv` for project commands. Explicitly select the named environment.

Linux/macOS:

```bash
export UV_PROJECT_ENVIRONMENT=doculens

uv sync --locked --dev
```

Windows PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT="doculens"

uv sync --locked --dev
```

This installs the project's locked dependencies and development tools into `doculens/`.

Verify the installation:

```bash
python -c "import fastapi, fitz, faiss; print('Dependencies installed successfully')"
```

**Important:** In every new terminal where you use `uv sync` or `uv run`, set `UV_PROJECT_ENVIRONMENT=doculens` again. Otherwise, `uv` may use or create `.venv`.

You can also run the installed Python tools directly from the activated environment.

## 5. Configure Environment Variables

Create the local configuration file.

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

The `.env` file contains local application configuration.

Important default settings include:

```dotenv
DOCULENS_ENVIRONMENT=development
DOCULENS_PORT=8000

DOCULENS_OLLAMA_BASE_URL=http://127.0.0.1:11434
DOCULENS_OLLAMA_MODEL=qwen3.5:4b

DOCULENS_RETRIEVAL_MODE=hybrid
DOCULENS_RETRIEVAL_TOP_K=8

DOCULENS_ENABLE_GROUNDED_SYNTHESIS=true

DOCULENS_MAX_UPLOAD_BYTES=20971520
DOCULENS_MAX_PDF_PAGES=350
DOCULENS_DOCUMENT_TTL_SECONDS=3600
```

You can change these values to match your local setup.

Do not commit `.env` to Git. Keep `.env.example` as the documented configuration template.

## 6. Install and Configure Ollama

DocuLens uses a locally running Ollama server for language-model inference.

Download and install Ollama from:

https://ollama.com/download

Check installation:

```bash
ollama --version
```

### Step 6.1 — Start the Ollama server

Open a **separate terminal**.

On Linux/macOS:

```bash
LLAMA_ARG_CACHE_RAM=0 \
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
ollama serve
```

On Windows PowerShell:

```powershell
$env:LLAMA_ARG_CACHE_RAM="0"
$env:OLLAMA_NUM_PARALLEL="1"
$env:OLLAMA_MAX_LOADED_MODELS="1"

ollama serve
```

These settings limit Ollama's model concurrency and memory-related behavior.

If Ollama is already running as a background service, avoid launching a second server on the same port. Stop or reconfigure the existing server when the documented settings are needed.

The Ollama server normally listens at:

```text
http://127.0.0.1:11434
```

Keep this server running while using DocuLens.

### Step 6.2 — Download the language model

Open another terminal:

```bash
ollama pull qwen3.5:4b
```

Verify:

```bash
ollama list
```

The downloaded model name must match `DOCULENS_OLLAMA_MODEL` in `.env`.

The initial download requires an internet connection.

### Step 6.3 — Verify Ollama

```bash
ollama ps
```

This displays currently loaded models. A model may be installed without being loaded.

You can also inspect available models:

```bash
curl http://127.0.0.1:11434/api/tags
```

## 7. Run DocuLens Locally

At this point:

- The Python environment is created.
- Project dependencies are installed.
- `.env` is configured.
- Ollama is running.
- The configured Ollama model is downloaded.

Open a terminal in the project directory.

### Linux/macOS

```bash
cd Doculens-v2

source doculens/bin/activate

export UV_PROJECT_ENVIRONMENT=doculens
```

Start the FastAPI application:

```bash
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

### Windows PowerShell

```powershell
cd Doculens-v2

.\doculens\Scripts\Activate.ps1

$env:UV_PROJECT_ENVIRONMENT="doculens"

uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

### Expected output

You should see output resembling:

```text
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**Open the application:**

http://127.0.0.1:8000

The browser interface is served directly by FastAPI. A separate frontend development server is not required.

Keep the API terminal running while using the application.

Use **one application worker**, because document sessions and indexes are stored in process memory.

## 8. How to Use DocuLens

1. Open the application in your browser.
2. Confirm that the connection indicator reports the configured Ollama model as available.
3. Upload a supported, text-selectable PDF.
4. Allow the application to extract the text and create its retrieval index.
5. Enter a question about the document.
6. Read the answer and inspect the cited PDF pages.
7. Ask follow-up questions using the same document session.
8. Open source cards to inspect the extracted passages or original PDF.
9. Clear the conversation or remove the document when finished.

Example questions:

```text
What is the main objective of this document?

What are the key requirements?

What limitations are described?

Which PDF pages support that answer?

Explain those requirements in more detail.
```

### Intelligent Question Answering

For follow-up questions, DocuLens can use recent conversation history to generate a standalone retrieval query.

For example:

```text
User: What are the document's limitations?

User: Which pages mention them?
```

The second question can be resolved using the earlier conversation.

The system then retrieves relevant passages and verifies supporting evidence.

When grounded synthesis is enabled, the application may produce a concise direct answer from verified citations. If synthesis validation fails, it falls back to verified source excerpts.

If adequate evidence cannot be established, the application abstains instead of generating an unsupported answer.

## 9. PDF Requirements and Limitations

Default supported limits:

| Parameter | Default |
|---|---|
| PDF files per browser workspace | 1 |
| Maximum upload size | 20 MiB |
| Maximum pages | 350 |
| Maximum extracted characters | 4,000,000 |
| Session lifetime | 1 hour |
| Application workers | 1 |

DocuLens is designed primarily for English, text-selectable PDFs.

Scanned or image-only PDFs require OCR before upload.

Complex tables, diagrams, mathematical notation, and image-based information may not be interpreted reliably.

PDF page positions may differ from page numbers printed inside the document.

Retrieval examines selected evidence passages, so an unanswered question does not necessarily mean that the requested information is absent from the entire PDF.

The application is intended for local use. It does not provide user accounts, shared document storage, or public-service authentication.

## 10. Running with Docker Compose

Docker Compose is an alternative to the manual Python and Ollama setup.

It runs the API and Ollama in separate containers.

### Step 10.1 — Verify Docker

```bash
docker --version
docker compose version
```

### Step 10.2 — Build and start

From the project root:

```bash
docker compose up -d --build
```

### Step 10.3 — Download the Ollama model

```bash
docker compose exec ollama ollama pull qwen3.5:4b
```

### Step 10.4 — Check container status

```bash
docker compose ps
```

### Step 10.5 — View logs

```bash
docker compose logs -f api ollama
```

Open:

http://127.0.0.1:8000

If `DOCULENS_PORT` has been changed in `.env`, open the corresponding localhost port instead.

### Stop the containers

```bash
docker compose down
```

### Rebuild after code changes

```bash
docker compose up -d --build
```

Docker Compose manages its own Python environment and Ollama service. The host `doculens` virtual environment is not required for this method.

The configured Docker volumes preserve downloaded model data and embedding caches, but browser document sessions are not persistent across application restarts.

## 11. Run Automated Tests

Activate your environment and select the named `uv` project environment.

Linux/macOS:

```bash
source doculens/bin/activate
export UV_PROJECT_ENVIRONMENT=doculens
```

Windows PowerShell:

```powershell
.\doculens\Scripts\Activate.ps1
$env:UV_PROJECT_ENVIRONMENT="doculens"
```

### Python tests

```bash
uv run pytest -q
```

### Code linting

```bash
uv run ruff check .
```

### Retrieval evaluation

```bash
uv run python -m scripts.evaluate_retrieval \
  --output data/retrieval-validation.json
```

### Frontend tests

Node.js 20+ is required.

Install test dependencies:

```bash
npm ci --ignore-scripts
```

Check JavaScript syntax:

```bash
npm run check
```

Run browser DOM tests:

```bash
npm test
```

These are automated DOM/module tests, not a substitute for testing the application in a real browser.

### Live model evaluation

Start Ollama and the DocuLens API before running:

```bash
uv run python -m scripts.evaluate_product \
  --output data/live-model-validation.json
```

This evaluation exercises the application with synthetic PDFs and checks supported questions, missing facts, prompt injection, and conflicting evidence.

It requires the configured local language model and may take several minutes on CPU hardware.

Review the generated answers and source citations manually.

## 12. API Endpoints

FastAPI automatically generates interactive API documentation.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Browser workspace |
| GET | `/health` | API process health |
| GET | `/ready` | Ollama and model readiness |
| GET | `/api/status` | Model availability and application limits |
| POST | `/api/documents` | Upload a PDF |
| POST | `/api/documents/{id}/ask` | Ask a question using an uploaded PDF |
| GET | `/api/documents/{id}/pages/{n}` | Get extracted PDF page text |
| DELETE | `/api/documents/{id}` | Delete a document session |
| POST | `/documents/extract` | Extract document text |
| POST | `/documents/ask` | Compatible upload-per-question endpoint |
| POST | `/documents/extract-structured` | Extract structured metadata |

The cached-document question endpoint accepts a JSON payload such as:

```json
{
  "question": "What is the main purpose of the document?",
  "history": [],
  "synthesize": true
}
```

The `history` and `synthesize` fields are optional.

Document-session API requests require the `X-Document-Token` header returned when the PDF is uploaded.

### API documentation

http://127.0.0.1:8000/docs

### Health check

```bash
curl http://127.0.0.1:8000/health
```

### Readiness check

```bash
curl http://127.0.0.1:8000/ready
```

A `200` readiness response indicates that Ollama and the configured model are available. A `503` indicates the application is not ready.

## 13. Troubleshooting

### `ModuleNotFoundError`

Ensure that the correct Python environment is active and dependencies are installed.

```bash
source doculens/bin/activate
export UV_PROJECT_ENVIRONMENT=doculens
uv sync --locked --dev
```

On Windows, use the PowerShell activation and environment commands from Section 4.

### `uv` creates `.venv` instead of `doculens`

Project operations use `.venv` by default.

Linux/macOS:

```bash
export UV_PROJECT_ENVIRONMENT=doculens
```

Windows PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT="doculens"
```

Then rerun the relevant `uv` command.

### Ollama connection failure

Check that the Ollama server is running at:

```text
http://127.0.0.1:11434
```

Verify the installed model:

```bash
ollama list
```

Ensure that the model name matches the value configured in `.env`.

### Port 8000 is already in use

Stop the application already using port 8000, or change the application's listening port and corresponding browser URL.

Do not change the container's internal service port without also updating the Docker configuration.

### Embedding model download failure

Hybrid retrieval initially downloads:

```text
sentence-transformers/all-MiniLM-L6-v2
```

Check your internet connection.

For a keyword-only fallback, change `.env` to:

```dotenv
DOCULENS_RETRIEVAL_MODE=lexical
```

Restart the application afterward.

Lexical retrieval may be less effective for paraphrased questions.

### PDF upload fails

Check whether:

- The file is a valid PDF.
- The PDF contains selectable text.
- The file is within the configured size limit.
- The document is within the supported page limit.
- The document session has not expired.

### Answer returns "Out of PDF content"

Try asking a more specific question using terminology from the document.

DocuLens abstains when retrieved evidence is insufficient or cannot be verified. This does not establish that the answer is absent from the entire PDF.

### Docker build takes too long

The first build downloads Python dependencies, including CPU machine-learning packages.

Confirm that `doculens/`, `.venv/`, and other local build artifacts are excluded in `.dockerignore`.

Check available disk space and Docker logs.

## 14. Project Documentation

Additional project documentation:

- [Technical and Operations Guide](documentation/DocuLens-v2-Technical-and-Operations-Guide.pdf)
- [Repair Report](docs/REPAIR-REPORT-v0.2.0.md)
- [Frontend Workspace](frontend/index.html)
- [Environment Configuration](.env.example)

Regenerate the technical PDF guide:

```bash
uv run python documentation/generate_guide_pdf.py
```

## 15. Development and GitHub Actions

The repository contains GitHub Actions workflows for linting, testing, and Docker builds.

The current workflows are configured for pushes and pull requests involving `main`. The main DocuLens CI workflow also supports manual triggering.

To run the GitHub Actions checks against `final-release`, open a pull request targeting `main`, or adjust the workflow triggers to include the release branch.

GitHub Actions:

https://github.com/anuushka-dev/Doculens-v2/actions

For local development, always run the Python and frontend checks before pushing changes.

## 16. Stopping the Application

To stop the local FastAPI server, press:

```text
Ctrl+C
```

Stop the manually started Ollama server similarly, if appropriate.

To deactivate the Python environment:

```bash
deactivate
```

To stop a Docker deployment:

```bash
docker compose down
```

## 17. Quick Start — Linux/macOS

After installing Python 3.12, uv, and Ollama, these are the essential commands.

**Terminal 1 — Ollama**

```bash
LLAMA_ARG_CACHE_RAM=0 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

**Terminal 2 — Initial project setup**

```bash
git clone -b final-release https://github.com/anuushka-dev/Doculens-v2.git
cd Doculens-v2

# Add doculens/ to .gitignore and .dockerignore first.

uv venv doculens --python 3.12
source doculens/bin/activate

export UV_PROJECT_ENVIRONMENT=doculens
uv sync --locked --dev

cp .env.example .env
ollama pull qwen3.5:4b
```

**Terminal 2 — Run application**

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

**Browser**

```text
http://127.0.0.1:8000
```

For later sessions, you don't need to reinstall everything. Start Ollama if it isn't running, activate `doculens`, set `UV_PROJECT_ENVIRONMENT=doculens`, and run the FastAPI command.

---

**DocuLens v2 — Ask questions, verify evidence, and explore your PDFs locally.**

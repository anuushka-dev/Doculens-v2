# DocuLens 0.2.0 — repair and validation report

Prepared 11 November 2026 from the supplied `Doculens.zip` (application version 0.1.0). This release is a complete source project, with setup instructions, locked dependencies, tests and a browser interface.

## Product behavior

Upload a PDF once, ask independent questions and inspect exact source excerpts with physical PDF page numbers. The application returns `insufficient_evidence` with an “Out of PDF content” message if it cannot establish sufficient support. It never switches to general-knowledge answers.

**Accuracy choice:** generated prose is discarded. The displayed answer is assembled from verified original source excerpts, with surrounding sentence context retained where available. A separate model call reviews relevance, sufficiency, conditions and contradictions before the excerpts are returned. Exact text provenance is checked in application code; semantic relevance is still a model judgment. Neither a genuine quote nor a high retrieval score proves an answer is correct. Model transport, truncation and schema failures are reported as technical errors rather than evidence that a PDF fact is absent.

## Findings and fixes

| Priority | Problem found | Implemented change |
|---|---|---|
| Critical | A real quote could accompany an invented answer; the answer's claims were never checked. | Return only verified source excerpts. Run a separate question/evidence review. Never expose generated draft prose as a document fact. |
| Major | Live testing exposed excessive refusals from an over-broad full-document sufficiency rule and inconsistent review flags. | Scope the review to the actual question and require one explained verdict. Specific facts do not require the entire PDF. |
| Major | Live testing exposed a model accepting one of two incompatible numerical statements. | Add a deterministic check for matching, question-relevant statements with different numbers. Preserve distinct alphanumeric product identifiers and normalize simple plural question terms. This is a narrow guard, not detection of every semantic contradiction. |
| Major | Genuine questions could fail because the model paraphrased a quote or copied an ID incorrectly. | Allow one recovery attempt that selects only enumerated, application-owned sentence IDs. The application supplies their exact source text and re-runs validation/review; approximate quotes are never accepted. |
| Major | A collectively supported answer could still display unrelated or duplicate supporting passages. | The independent review now selects the smallest supporting subset using enumerated citation labels. Empty or invented approvals fail closed; unrelated proposed quotes are not automatically displayed. |
| Major | The small original model could treat a receipt rule as an answer to a subscription-price question. | Use the tested 4B default and reject approved evidence that lacks an explicitly requested quantity/unit. Price questions cannot be answered with durations or non-numerical eligibility conditions. Explicit free pricing is supported; unit conversions are not inferred. |
| Major | A partial quote could omit a negation or subject and change the apparent meaning. | Expand Q&A citations to surrounding visible source sentences before review and display. Added a regression where “eligible” occurs inside “not eligible.” |
| Major | The model saw truncated context, but citations were validated against all original retrieved chunks. | Shared context fitting returns the exact visible source spans. Q&A and structured extraction validate only those spans. Unseen chunks and unseen tails cannot support a response. |
| Major | A strong unused search hit allowed weak quoted evidence to pass the score gate. | Apply the minimum ranking threshold to each candidate source before generation. |
| Major | Dense-only retrieval missed identifiers, rare keywords, overview material and facts continuing on the following page. | Add BM25 plus semantic retrieval, shorter overlapping windows, bounded overview context and adjacent-page expansion. |
| Major | 220-word windows could exceed MiniLM's token limit and silently lose their tails. | Encode overflow token windows and pool their vectors. The product also uses 100-word windows with 25-word overlap. |
| Major | Every question rebuilt the index and could reload embedding weights. | Share CPU embedding weights with serialized inference; upload once into a bounded, expiring per-document index. |
| Major | No usable browser product was supplied. | Add a responsive upload/chat workspace, source cards, highlighted extracted-page text, original-PDF viewing, loading/error states and document removal. |
| Major | Async upload routes parsed PDFs synchronously on the event loop. Concurrent PyMuPDF use also needed isolation. | Parse PDFs in separate child processes, bound processing time, and terminate a child on timeout/cancellation. Existing upload APIs use this boundary too. |
| Major | Limits were applied after multipart parsing; small compressed files could also expand into excessive text. | Bound complete request bodies, including streamed bodies without Content-Length. Bound extracted characters, uploaded bytes and page counts. Limit concurrent workspace jobs and cached memory. |
| Major | Default dependency resolution downloaded multi-gigabyte CUDA packages for a CPU application. | Configure a CPU PyTorch package source and regenerate `uv.lock`; remove GPU dependency downloads from the Linux CPU install. |
| Major | Production LLM transport relied on HTTPX being present transitively/development-only. | Declare HTTPX as a runtime dependency, including SOCKS support for environments that require it. The local Ollama client does not inherit proxy variables. |
| Major | Compose did not connect Ollama, and read-only containers could not download embedding weights to a writable cache. | Add an internal Ollama service and persistent writable model volumes. Forward model, context, retrieval and session configuration. |
| Major | Repeated questions accumulated host prompt-cache snapshots until the local model worker was killed, even after lowering context/batch. | Pin the tested Ollama release, disable the upstream host prompt cache, and document equivalent local-server settings. Repeated live validation is recorded below. |
| Major | Installed wheels assumed a repository `pyproject.toml` existed above site-packages. | Fall back to the working directory for optional configuration/data when running an installed wheel. |
| Moderate | Substrings such as `20 days` inside `120 days` could pass quote checks. | Require character boundaries for quote matches; preserve original typographic source text. |
| Moderate | Additional valid quotes from the same chunk were checked but discarded from the returned evidence. | Preserve the full intervening source span when combining quotes from one chunk, with bounded citation lengths. |
| Moderate | Truncated model responses and oversized input context could be treated as complete. | Reject explicit incomplete/token-limit finishes. Enforce a conservative input budget before sending the full prompt/schema to Ollama. |
| Moderate | Document IDs alone would be an unsafe session boundary for a reusable index. | Use random session secrets, store only their hashes, require a header token for questions/pages/removal, and check page-text/offset provenance before answering. |
| Moderate | Client text could become executable markup if rendered as HTML. | Use text nodes for filenames, answers and citations. Add same-origin security headers and no-store responses for session APIs. |
| Moderate | Blank-question cleanup, session-expiry UI handling and setup documentation were incomplete or stale. | Close rejected uploads, allow expired sessions to be cleared, reap expired indexes, and rewrite setup/API documentation around actual implemented behavior. |

## Completed validation

| Check | Result | What it establishes |
|---|---|---|
| Python test suite | **667 passed** | Includes the original 600 tests, updated where the answer contract intentionally changed, plus 67 product/accuracy regressions. |
| Frontend DOM tests | **6 passed** | Upload/question/source/removal flows, abstention display, expired sessions, upload errors and literal rendering of hostile markup. APIs are mocked for these frontend tests. |
| Ruff | Passed | Source and test lint checks. |
| JavaScript syntax | Passed | `node --check app/web/app.js`. |
| Real PDF integration | Passed | Real PyMuPDF-generated PDFs travel through isolated parsing, indexing and question APIs; model HTTP responses are mocked. |
| Real CPU semantic retrieval | Passed; detailed results below | Actual MiniLM inference on the supplied NIST PDF, without a mocked embedding model. |
| Python source/wheel build | Passed | Python package creation and inclusion of browser assets. |
| Docker/CI runtime | Not executed | Docker is unavailable in this environment; workflow configuration is provided. |
| Rendered browser/visual QA | Not completed | Local Chromium could not launch under the environment's process/socket restrictions; the cloud browser could not access the workspace preview and blocked file-URL previews. DOM tests were used for interface behavior. Desktop/mobile visual acceptance remains necessary. |
| Live Ollama answer checks | Completed; see the checked-in live reports | Real Ollama 0.40.16 with `qwen3.5:4b`, using the production hybrid pipeline on CPU. The reports distinguish synthetic acceptance cases from real-PDF spot checks. |

The mocked-model tests verify the application enforces its output rules when a model returns fabricated prose, an invalid quote, a negative review, a conflict, incomplete support or a truncated response. They do **not** establish how often a real model will make correct relevance judgments. Real-model checks were also run separately; their narrow scope is documented in the raw reports. Model configuration and artifact digests are recorded in [validation-environment.json](validation-environment.json).

## Real retrieval benchmark

The existing dataset has 30 labelled NIST SP 800-63-4 questions. These labels were used during development; this is a development fixture, not a held-out benchmark. The checked-in [JSON report](retrieval-validation.json) contains the PDF digest, individual questions, expected pages and actual retrieved/visible pages.

| Current pipeline | Labelled page in raw top 5 | Labelled page in raw top 8 | Labelled page in final bounded context |
|---|---:|---:|---:|
| Retained dense comparator, 220 words | 17/30 | 22/30 | 20/30 |
| Product hybrid search, 100 words | 27/30 | 27/30 | **30/30** |
| Explicit keyword-only mode, 100 words | 25/30 | 27/30 | 29/30 |

“Final bounded context” includes the configured threshold, overview/adjacent-page expansion and the 8,000-character budget. The comparator uses the current parser and overflow-safe embedding adapter; it is not a rerun of the original historical implementation. **30/30 context coverage is not 100% answer accuracy.** It only means at least one labelled source page was available in each question's selected context. The separate answer reviewer and the eventual user still need to assess whether the cited passage answers the question correctly and completely.

## Live language-model results

With the final `qwen3.5:4b` CPU configuration:

- **11/11 synthetic acceptance cases passed**, including missing prices, unrelated questions, user/document injection and conflicting numerical statements.
- **5/5 NIST spot-check answers contained the requested facts**, with every excerpt checked against its reported original PDF page. See [the content review](LIVE-ANSWER-REVIEW-v0.2.0.md) and [raw NIST responses](live-nist-validation.json).
- Original annotated-page matches and manual semantic review are deliberately distinguished; the original annotations do not list every valid evidence page.

The final defaults use 16,384 context tokens, an 8,000-character source budget and a 128-token prompt batch. Repeated long-document testing exposed accumulating host prompt-cache snapshots in the tested Ollama runner. Lowering context/batch alone did not resolve it. Disabling the upstream host prompt cache (`LLAMA_ARG_CACHE_RAM=0`) resolved the observed repeated-request failure in the complete spot-check and acceptance runs. Compose pins Ollama 0.40.16, applies this setting, and restricts it to one parallel generation and one loaded model; the README provides equivalent local-server commands.

These small development checks do not establish general answer accuracy. They do verify that the actual application, actual PDF parser, actual embedding model and actual language model worked together on these cases. Raw model transport/schema failures are technical errors, not classified as missing PDF information.

## What still needs validation before relying on the product

1. For your deployment, start Ollama, pull the configured model and run `uv run python -m scripts.evaluate_product`. Review the answers and citations manually. It exercises 11 synthetic supported, missing, unrelated, injection and conflicting-evidence cases and fails rather than counting request errors as successes.
2. Test representative PDFs from your actual use case, including negative questions, tables, awkward layout, cross-page facts and scanned pages. Calibrate the model and retrieval settings using separate evaluation documents.
3. Complete visual desktop/mobile browser acceptance and run Docker Compose on the deployment machine.

The application supports English selectable text. OCR, diagram understanding, reliable complex-table structure, exhaustive whole-document reasoning and public multi-tenant hosting are outside this release. Structured metadata retains schema validation and literal value provenance checks; those checks alone do not prove a value has the correct semantic field role.

## Reproduce the checks

```bash
uv sync --locked --dev
uv run pytest -q
uv run ruff check .
node --check app/web/app.js
npm ci --ignore-scripts
npm test
uv build
uv run python -m scripts.evaluate_retrieval --output data/retrieval-validation.json
```

After the local application and Ollama are running:

```bash
uv run python -m scripts.evaluate_product --output data/live-model-validation.json
```

The ZIP excludes virtual environments, installed JavaScript packages, model weights, private environment files, runtime data, Git internals and Windows metadata sidecars. It includes all application source, existing sample PDFs, retained experiments/tests, the new test suites, setup documentation and this report.

## Implementation references

- [Ollama generation protocol](https://docs.ollama.com/api/generate)
- [PyMuPDF process-isolation guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html)
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [uv CPU PyTorch configuration](https://docs.astral.sh/uv/guides/integration/pytorch/)

- [Upstream prompt-cache environment setting](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#server-specific-params)
- [Ollama prompt-cache memory report](https://github.com/ollama/ollama/issues/17351)

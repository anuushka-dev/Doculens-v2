# DocuLens documentation

Current release: **0.2.0**. The browser workspace, grounded extractive Q&A, source citations, abstention, structured metadata extraction and reusable document sessions are implemented.

- [Setup, supported inputs, API and limitations](../README.md)
- [Repair findings and validation boundaries](REPAIR-REPORT-v0.2.0.md)
- [Real CPU embedding retrieval results](retrieval-validation.json)
- [Live model acceptance responses](live-model-validation.json)
- [Live NIST answers and source review](LIVE-ANSWER-REVIEW-v0.2.0.md)
- [Historical Phase 2 dataset review](phase2/retrieval_dataset_review.md)

The historical Phase 2 review describes the earlier retrieval implementation and its original benchmark. It is not the result for the rebuilt product. The new retrieval report records the actual current source digest and per-question results. The dataset was used during development and is not an independent held-out accuracy test.

The product uses FastAPI, PyMuPDF, Pydantic, local MiniLM embeddings and an Ollama adapter. The framework-free HTML/CSS/JavaScript interface is served by the same application. The earlier FAISS retrieval pipeline and experiment scripts remain available for comparison; the browser workspace uses the hybrid pipeline.

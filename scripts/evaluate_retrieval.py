"""Evaluate product retrieval with real CPU embeddings and existing page labels.

Run: uv run python -m scripts.evaluate_retrieval --output docs/retrieval-validation.json
This measures evidence retrieval, not the correctness of generated answers.
"""

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.adapters.pdf.extractor import extract_pdf_bytes
from app.core.config import get_settings
from app.services.hybrid_retrieval import HybridRetrievalPipeline, shared_embedder
from app.services.retrieval_pipeline import RetrievalPipeline
from app.services.source_context import fit_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("data/retrieval-validation.json")
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = [
        json.loads(line)
        for line in (root / "tests/phase2/fixtures/retrieval_eval.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]
    source = root / cases[0]["document_path"]
    extraction = extract_pdf_bytes(
        source.read_bytes(),
        source.name,
        max_upload_bytes=20 * 1024 * 1024,
        max_pdf_pages=350,
    )
    context_budget = get_settings().max_context_chars
    results = {}
    pipelines = {
        "dense_baseline_220_words": RetrievalPipeline(embedder=shared_embedder().model),
        "hybrid_100_words": HybridRetrievalPipeline(),
        "lexical_100_words": HybridRetrievalPipeline(mode="lexical"),
    }
    for name, pipeline in pipelines.items():
        started = perf_counter()
        pipeline.index_pages(
            extraction.pages,
            document_id=str(extraction.document_id),
            file_name=extraction.filename,
        )
        indexing_seconds = perf_counter() - started
        rows = []
        for case in cases:
            started = perf_counter()
            raw_chunks = pipeline.search(case["query"], top_k=8).results
            search = getattr(pipeline, "search_evidence", pipeline.search)
            chunks = search(case["query"], top_k=8).results
            _, visible = fit_context(
                tuple(c for c in chunks if c.score >= 0.25), context_budget
            )
            expected = set(case["relevant_page_numbers"])
            row = {
                "id": case["question_id"],
                "question": case["query"],
                "expected_pages": sorted(expected),
                "pages_at_8": [c.page_number for c in raw_chunks],
                "visible_pages": [c.page_number for c in visible],
                "hit_at_5": any(c.page_number in expected for c in raw_chunks[:5]),
                "hit_at_8": any(c.page_number in expected for c in raw_chunks),
                "context_hit": any(c.page_number in expected for c in visible),
                "query_ms": round((perf_counter() - started) * 1000, 2),
            }
            rows.append(row)
        results[name] = {
            "questions": len(rows),
            "indexing_seconds": round(indexing_seconds, 2),
            **{
                key: sum(r[key] for r in rows)
                for key in ["hit_at_5", "hit_at_8", "context_hit"]
            },
            "cases": rows,
        }
    report = {
        "scope": "30 labelled NIST questions; page-hit rates, not answer accuracy.",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "source_sha256": extraction.sha256,
        "gating_threshold": 0.25,
        "context_budget_chars": context_budget,
        "pipelines": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, result in results.items():
        print(
            name,
            {
                key: result[key]
                for key in ["questions", "hit_at_5", "hit_at_8", "context_hit"]
            },
        )


if __name__ == "__main__":
    main()

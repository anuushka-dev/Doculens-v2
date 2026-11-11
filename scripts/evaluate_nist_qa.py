"""Live-model spot checks on five supplied NIST questions.

Page agreement and verbatim citations do not establish semantic correctness.
The report retains full responses and annotation notes for manual review.
"""

import argparse
import json
from pathlib import Path

import httpx

CHECK_IDS = {"Q001", "Q002", "Q006", "Q007", "Q008"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output", type=Path, default=Path("data/live-nist-validation.json")
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dataset = root / "tests/phase2/fixtures/retrieval_eval.jsonl"
    cases = [
        json.loads(line) for line in dataset.read_text().splitlines() if line.strip()
    ]
    cases = [row for row in cases if row["question_id"] in CHECK_IDS]
    rows, session = [], None
    with httpx.Client(base_url=args.base_url, timeout=400, trust_env=False) as client:
        try:
            pdf = root / cases[0]["document_path"]
            response = client.post(
                "/api/documents",
                files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
            )
            response.raise_for_status()
            session = response.json()
            for case in cases:
                response = client.post(
                    f"/api/documents/{session['document_id']}/ask",
                    headers={"X-Document-Token": session["document_token"]},
                    json={"question": case["query"]},
                )
                response.raise_for_status()
                result = response.json()
                match = any(
                    c["page_number"] in case["relevant_page_numbers"]
                    for c in result["citations"]
                )
                rows.append(
                    {
                        "id": case["question_id"],
                        "question": case["query"],
                        "expected_pages": case["relevant_page_numbers"],
                        "annotation": case["annotation_note"],
                        "citation_page_match": match,
                        "response": result,
                    }
                )
                print(
                    f"{case['question_id']}: {result['status']}; annotated page cited: {match}",
                    flush=True,
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        {
                            "scope": "Live NIST spot checks; manual semantic review required.",
                            "expected_cases": len(cases),
                            "completed_cases": len(rows),
                            "cases": rows,
                        },
                        indent=2,
                    )
                    + "\n"
                )
        finally:
            if session:
                client.delete(
                    f"/api/documents/{session['document_id']}",
                    headers={"X-Document-Token": session["document_token"]},
                )
    print(
        f"{sum(r['citation_page_match'] for r in rows)}/{len(rows)} annotated-page matches; inspect {args.output}"
    )


if __name__ == "__main__":
    main()

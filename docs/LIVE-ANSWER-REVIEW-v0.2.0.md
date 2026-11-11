# Live NIST answer review — DocuLens 0.2.0

The five spot-check answers were reviewed against the supplied NIST PDF. Each
returned excerpt is an exact substring of its reported extracted source page.
The answers contain the requested facts listed below. This is development
validation on five questions, not a held-out or universal accuracy benchmark.

| Case | Cited PDF pages | Content review | Outcome |
|---|---|---|---|
| Q001 | 1 | The cover evidence contains both the publication identifier and title. | Verified |
| Q002 | 5 | The abstract explicitly names identity proofing, authentication and federation. | Verified |
| Q006 | 18 | The cited notation states strict requirements with no permitted deviation. | Verified |
| Q007 | 21, 75 | The cited text explicitly lists know/have/are. The glossary on page 75 is valid additional evidence beyond the original page-21 annotation. | Verified |
| Q008 | 24 | The cited federation benefit describes pseudonymous identifiers and derived attribute values instead of copying account values. | Verified |

The original retrieval labels are not exhaustive. In particular, page 75's
`authentication factor` glossary definition supports Q007 as well as page 21.
A correct page-75 answer can therefore miss the original page-21-only metric.
The raw report retains that metric unchanged; semantic correctness is assessed
separately here. Some quotations retain headings or neighboring source context.

The synthetic acceptance suite separately checks missing facts, unrelated
questions, prompt injection and incompatible numerical statements. Its raw
responses are in `live-model-validation.json`.

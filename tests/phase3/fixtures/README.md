# Phase 3 evaluation fixtures

The active November 5 `qa_eval.jsonl` (30 reviewed questions) was not recovered as a file. The archived November 4 candidate snapshot is in `archive/`; its 10 unanswerable rows remain `pending_review` and must not be treated as a fully reviewed gold set.

The final `extraction_eval.jsonl` used for the November 5 v6 pilot (5 reviewed records) was not recovered as a file. A 20-row earlier annotation worksheet was described in the project guide, but the actual bytes were not recovered. Do not invent expected metadata or page annotations to recreate it.

The evaluation scripts default to the expected active fixture paths. They will stop with a clear missing-file error until the correct reviewed fixtures are restored.

# Task: packaging and quality

1. Add `py.typed`, type hints everywhere, `mypy --strict` clean on `src/`.
2. `ruff` config (lint + format) and fix findings.
3. GitHub Actions: Python 3.10–3.13, pytest, mypy, ruff. Full-corpus tests run only if the Tanzil files are available as a cached artifact; never commit them without checking Tanzil's terms (verbatim copy + attribution are required).
4. A JSON Schema for `DetectionResult.to_dict()` in `schema/detection.schema.json`, validated in tests; add `schema_version` to the output.
5. CLI: `--format json|jsonl|text`, `--min-status`, reading many files.
6. README: installation, data download, API, statuses, limitations, attribution.

# Task (only after 04 and 05, and only if error analysis justifies it): intent tagger

Do not start this task unless the evaluation report shows that a meaningful share of missed quotes are **intended but heavily altered** quotes (as in LLM hallucinations), or that common phrases cause false positives that rules cannot fix. First produce that error analysis and stop for my approval.

If approved:
- Token-classification (BIO) model for "this span is intended as a Quran quote", trained on IslamicEval 1A train data + synthetic data. Splits by source document; hold out one LLM family entirely.
- It may only (a) propose spans for the deterministic matcher to examine, or (b) downgrade common-phrase matches to `candidate`. It can never produce `verified`.
- Lives in an optional extra (`pip install quran-detector[neural]`); core stays zero-dependency.
- Cascade: run it only on spans the deterministic matcher could not settle; report the latency impact.
- Report IslamicEval 1A Quran-class char macro-F1 with bootstrap 95% CIs before/after.

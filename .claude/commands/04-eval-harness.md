# Task: evaluation harness (must exist before any threshold tuning or ML)

Create `evaluation/` (optional extra, not imported by the core).

## 1. Gold format (`.jsonl`, one document per line)
`{"id", "text", "source": "synthetic|llm|ocr|manual", "spans": [{"start", "end", "status", "locations": [[["s","a","w1","w2"],...]], "intended": true}]}`
A document with `"spans": []` is a negative.

## 2. Synthetic generator `evaluation/synth.py` (seeded, deterministic)
- Sample spans from the corpus stream: lengths 2–40 words, partial ayahs, whole ayahs, multi-ayah runs; also short and formulaic ones.
- Perturbations, each recorded in the gold label: strip/keep diacritics, drop hamzas, ى↔ي, ة→ه, substitute a word with a word from a **similar ayah** (share a 3-gram elsewhere in the corpus; these imitate LLM mix-ups), delete a word, insert a word, splice two spans from different places, add ayah numbers like (12) between ayahs.
- Embed into Arabic filler text from a file I provide (`evaluation/filler/*.txt`); if none exists, stop and ask me. Add context markers («قال تعالى»، ﴿﴾) only in a controlled fraction.
- Hard negatives from `evaluation/negatives/*.txt` (hadith, du'a, fiqh, poetry) that I will supply; never generate fake hadith.
- Gold locations for exact spans must list **all** occurrences (use `Corpus.find_all`).

## 3. Metrics `evaluation/run_eval.py`
- Span P/R/F1 with exact boundaries and with IoU ≥ 0.5.
- Character-level macro-F1 (IslamicEval 1A style).
- Reference accuracy (predicted location set == gold set), ambiguity coverage (location-set recall and precision).
- F1 for `altered` and `spliced`.
- **Precision of `verified`** with a 95% Clopper–Pearson upper bound on the error rate. Implement the bound in pure Python (beta inverse via bisection), test it against known values.
- Latency p50/p95.
- Output: `evaluation/reports/<timestamp>.json` and a markdown table; a `--compare old.json` flag prints deltas.

## 4. IslamicEval 2025 Task 1 adapter
I will put the official dev files in `evaluation/islamiceval/`. Read their format first, then write the adapter; do not guess the schema. Report 1A (char macro-F1, Quran class), 1B (accuracy), 1C (accuracy). Note that IslamicEval uses its own Uthmani Quran text, where diacritics count; use their text for 1B/1C if their rules require it.

## Acceptance
`python evaluation/run_eval.py --data evaluation/data/synth_dev.jsonl` runs end to end; unit tests for every metric, including edge cases (no predictions, no gold).

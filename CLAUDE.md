# quran-detector — project context for Claude Code

## What this is
A library that finds Quran quotes inside arbitrary Arabic text (articles, LLM
answers, OCR output), grounds each one to every possible location in the
Mushaf, and verifies it (exact / spelling variant / altered / spliced /
ambiguous). **Accuracy is the top priority; speed is second.** The product KPI
is precision of `verified` matches (target ≥ 99%, measured with a confidence
bound, not claimed).

## Non-negotiable rules
1. **The Quran text comes only from the Tanzil files in `data/`.** Never type
   Quran text from memory into source code, fixtures or docs. Test fixtures
   must be copied programmatically from the Tanzil files (see
   `.claude/commands/01-full-corpus.md`). The current
   `tests/fixtures/mini_simple.txt` was typed by hand and must be regenerated
   and diffed against Tanzil before anything else.
2. **Tanzil text stays verbatim.** Never modify the downloaded files. Derived
   forms (normalized, indexes, caches) live in memory or in clearly separate
   cache files. Keep the attribution in `Corpus.source`.
3. **`verified` is decided only by deterministic gates** in
   `detector.py::_build_match`. No model, LLM, embedding or score may promote a
   match to `verified`. Neural components may only propose candidates or rank
   them.
4. **Never loosen a gate or threshold to make a test pass.** If a test fails,
   find the cause. Threshold changes require an evaluation run (see
   `05-tune-thresholds`) and a before/after metrics table in your report.
5. **Every behaviour change ships with tests**: at least one positive and one
   negative case (a text that must NOT match or must NOT be verified).
6. **Core stays zero-dependency** (pure Python ≥ 3.10). Evaluation, fuzzy or
   neural extras go behind optional extras in `pyproject.toml`.
7. Character offsets are Python string indices (Unicode code points). Keep it
   that way and document it if you add any other API.
8. Changing the output fields of `QuranMatch` / `DetectionResult` means:
   update README, bump `__version__`, and keep `to_dict()` JSON-serializable.

## Layout
```
src/quran_detector/
  normalizer.py  LIGHT / STRICT / AGGRESSIVE token normalization
  tokenizer.py   Arabic word tokens with offsets; Latin = barrier; digits/punct skipped
  corpus.py      Tanzil loader, continuous word stream, bigram/trigram index, refs()
  detector.py    seed → extend (MEMs) → chain → weighted interval scheduling
                 → align/diff → grounding (all locations) → gates → splice marking
  citations.py   parses writer-given references ([البقرة: 153], (2:153), ...)
  models.py      Status, Ref, DiffOp, QuranMatch, DetectionResult
  cli.py         python -m quran_detector ... detect|verify
tests/           pytest; fixtures/ (subset of Tanzil, test-only)
data/            Tanzil files (not committed if license/size is a concern)
```

## Commands
```bash
python -m pytest -q                                   # all tests
PYTHONPATH=src python -m quran_detector --simple data/quran-simple.txt detect file.txt
PYTHONPATH=src python -m quran_detector --simple data/quran-simple.txt verify "..."
```

## Key design facts (read before changing the detector)
- Matching uses the **Tanzil Simple (Imlaei)** text. Uthmani is display-only
  today; its rasm differs (الصلوة/الصلاة, يأيها/يا أيها), so it cannot be
  matched by stripping diacritics.
- The Quran is one stream; a `SURAH_BREAK` sentinel stops matches across surahs.
- Exact spans are re-searched in the whole corpus → multiple locations →
  `ambiguous` unless a citation resolves it.
- Formulaic phrases and short spans need context (﴿﴾, «قال تعالى», a citation).
- `score` is a ranking heuristic, not a probability. Do not call it confidence
  until it is calibrated.

## Definition of done for any task
- `python -m pytest -q` green, including the full-corpus tests when `data/` exists.
- New tests for the change (positive + negative).
- If detection behaviour changed: run `evaluation/run_eval.py` (once it exists)
  and paste the metrics delta into your final message.
- README updated if the public behaviour or output changed.
- Short final report: what changed, what you measured, what is still open.

## Working style
- Start non-trivial tasks in plan mode; state assumptions before coding.
- Prefer small, reviewable commits, one concern each.
- When something is ambiguous about Quran text or Islamic conventions
  (e.g. whether a du'a that is a verse counts as a quote), stop and ask; do not guess.

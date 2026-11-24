# Prompt package

Each file here is a Claude Code slash command (`/00-orient`, `/01-full-corpus`, ...).
Project rules live in `CLAUDE.md` at the repo root and apply to every task.

Order:
1. `00-orient`: read, run tests, no changes
2. `01-full-corpus`: real Tanzil data, regenerate fixture, stats, benchmark
3. `02-uthmani-matching`
4. `03-diacritics-check`
5. `04-eval-harness`: must exist before 05 and 09
6. `05-tune-thresholds`
7. `06-ocr-fuzzy`
8. `07-tokenization-edge-cases`
9. `08-packaging-quality`
10. `09-neural-intent-tagger`: optional, gated on error analysis

One task per session. Start each in plan mode, review the plan, then let it run.

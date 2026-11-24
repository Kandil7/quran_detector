# Task: fuzzy matching for OCR text (ASR is a separate later task)

Exact word seeds fail when many words carry OCR errors. Add an optional OCR mode.

## Requirements
1. `Level.SKELETON` normalization: map letters to their dotless rasm (ب ت ث and medial ن ي → one class; ج ح خ; د ذ; ر ز; س ش; ص ض; ط ظ; ع غ; ف ق (consider position); final ن/ي separately). Write the table in one place, document it, and test it.
2. Candidate generation for OCR mode: word n-gram index over skeleton forms + character 4-gram index over STRICT forms. Gather candidate windows, then align with a word-level DP whose substitution cost is the character edit distance between words, cheaper for dot-confusions.
3. New `Status.NEEDS_REVIEW` (or `match_level="fuzzy"`, decide and justify). Fuzzy matches are **never** `verified`.
4. Enabled only with `Config(mode="ocr")`; default behaviour and latency unchanged (prove with the benchmark).

## Tests
Synthetic OCR noise (dot swaps, merged/split words) on quotes from the file → found with the right refs; ordinary noisy text → nothing above `needs_review`.

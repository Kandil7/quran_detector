# Task: verify diacritics (tashkeel)

Today a quote with wrong diacritics is still `verified`. LLMs often produce fully diacritized but wrong text, and benchmarks such as IslamicEval 2025 count wrong diacritics as an error.

## Requirements
1. New `Config.diacritics`: `"off"` (default, today's behaviour), `"report"`, `"strict"`.
2. For each matched word whose input contains harakat, compare letter by letter with the reference word (Simple; Uthmani when the match came from the Uthmani stream, after task 02):
   - Only compare marks the writer actually wrote (partial diacritization is fine).
   - Canonicalize mark order (NFC handles shadda/vowel order; verify with a test).
   - Treat equivalent encodings as equal (e.g. Uthmani open tanween U+08F0–U+08F2 vs standard tanween; Uthmani sukun U+06E1 vs U+0652). Write the equivalence table explicitly and test it.
3. Output: new diff op `"diacritic"` with `got`, `expected`, and the letter index; `QuranMatch.diacritics_ok: bool | None`.
   - `"report"`: status unchanged, flag set.
   - `"strict"`: a `verified` match with diacritic errors becomes `altered`.
4. No effect when the input has no diacritics.

## Tests
- Correctly diacritized quote (copied from the file) → ok in all modes.
- One wrong vowel → `diacritic` op; `altered` only in strict.
- Partially diacritized correct quote → ok.
- Uthmani-encoded marks vs Simple reference → ok (equivalence table).

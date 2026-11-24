# Task: run on the full Tanzil corpus and replace the hand-typed fixture

Precondition: `data/quran-simple.txt` and `data/quran-uthmani.txt` exist (Tanzil, `surah|ayah|text`). If not, stop and ask me.

## Steps
1. **Regenerate the fixture from Tanzil.** Write `scripts/make_fixture.py` that copies these ayahs verbatim from `data/quran-simple.txt` (and the Uthmani file into `tests/fixtures/mini_uthmani.txt`):
   1:1–7, 2:153–156, 8:46, 27:30, 55:13, 55:16, 103:1–3, 112:1–4.
   Diff the result against the current hand-typed `tests/fixtures/mini_simple.txt` and report every difference. Replace the fixture with the generated one. Keep the header comment saying it is a test-only subset.
2. **Full-corpus tests** in `tests/test_full_corpus.py`, skipped with `pytest.mark.skipif` when `data/` files are missing:
   - 6236 ayahs, 114 surahs; spot-check ayah counts: surah 2 = 286, surah 9 = 129, surah 112 = 4.
   - «إن الله مع الصابرين» with context → `ambiguous`, locations include 2:153 and 8:46.
   - «فبأي آلاء ربكما تكذبان» with context → `ambiguous` with 31 locations, all in surah 55.
   - The whole of Al-Fatiha (copied from the file, then stripped of diacritics in the test) → `verified`, locations 1:1–1:7.
   - A long paragraph of ordinary Arabic news text (write it yourself, no Quran) → no matches.
   - Test-input strings that contain Quran text must be read from the Tanzil file inside the test, not typed.
3. **Statistics script** `scripts/corpus_stats.py`: total words, vocabulary size, the 30 most frequent bigrams with counts, how many bigrams exceed `Config.frequent_bigram`. Use it to check that the threshold (300) is sensible; propose a value if not, with numbers.
4. **Benchmark** `scripts/bench.py`: corpus build time, and p50/p95 detect latency over 50 runs on a ~1000-word mixed text (Arabic filler + 10 quotes sampled from the corpus with a fixed seed). If build time > 0.5 s, add an optional cache (pickle keyed by the SHA-256 of the input files, stored outside `data/`), with a test that a changed file invalidates it.

## Acceptance
- All tests green with and without `data/`.
- Report: fixture diff, stats summary, benchmark numbers, any threshold proposal.

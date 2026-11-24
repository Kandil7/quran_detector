Read CLAUDE.md and README.md, then every file in src/quran_detector/ and tests/.

Then:
1. Run `python -m pytest -q` and report the result.
2. Check whether `data/quran-simple.txt` and `data/quran-uthmani.txt` exist. If not, stop and tell me exactly which files to download from https://tanzil.net/download/ (format "Text (with aya numbers)", i.e. `surah|ayah|text` lines; Simple = Imlaei with diacritics; Uthmani).
3. Summarize in ≤ 15 lines: the pipeline, where the status gates live, and the known limitations listed in the README.

Do not change any code in this step.

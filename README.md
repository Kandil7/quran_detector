# quran-detector

Detect, ground and verify Quran quotes inside any Arabic text (articles, LLM
answers, OCR output). For every quote the library returns its exact span in the
input, every location in the Mushaf it can come from, a word-level diff against
the reference text, and a status decided by explicit rules, not by a score.

Pure Python 3.10+, no dependencies.

## Data

Download the Tanzil text in **"Text (with aya numbers)"** format
(`surah|ayah|text` per line) from <https://tanzil.net/download/>:

- `quran-simple.txt`: **Simple** (Imlaei) text with diacritics. Required; used for matching.
- `quran-uthmani.txt`: **Uthmani** text. Optional; only returned for display.

Put them in `data/`. Tanzil allows verbatim copying only and requires
attribution with a link to tanzil.net. The library never modifies the files;
normalized forms are derived in memory, and the attribution is included in
every result under `source`.

## Usage

```python
from quran_detector import Corpus, QuranDetector, Status

corpus = Corpus.from_tanzil("data/quran-simple.txt", "data/quran-uthmani.txt")
det = QuranDetector(corpus)          # HIGH_PRECISION by default

res = det.detect("قال تعالى: ﴿إن الله مع الصابرين﴾ [الأنفال: 46]")
for m in res.matches:
    print(m.status, m.text, m.locations, m.claimed_ref, m.citation_correct)
# verified  إن الله مع الصابرين  [[8:46[10-13]]]  8:46  True

det.verify("اللَّهُ الصَّمَدُ")      # caller asserts the string is a quote
```

CLI:

```bash
python -m quran_detector --simple data/quran-simple.txt detect article.txt
python -m quran_detector --simple data/quran-simple.txt verify "قل هو الله أحد"
```

## Statuses

| status | meaning |
|---|---|
| `verified` | identical to the Quran text after normalization (spelling variants such as ة/ه allowed and listed in `diff`), long enough or quoted explicitly, and in one location |
| `ambiguous` | identical, but the same words occur in several places; all are in `locations`. A citation next to the quote resolves it |
| `altered` | clearly intended quote with substituted, inserted or missing words; see `diff` |
| `spliced` | joined directly to another quote from a non-adjacent place; see `spliced_with` |
| `candidate` | real Quran words but too short or too common (e.g. «إن شاء الله»). Hidden in `HIGH_PRECISION`, shown in `BALANCED` |
| `needs_review` | OCR mode only: a match that uses a corrected word. Never `verified`. |

Every match also has `start_char`/`end_char` (Python string indices),
`reference_text` (Tanzil Simple words), `reference_uthmani` (whole ayahs) and
`score` (a ranking heuristic, **not** a calibrated probability).

`Ref.word_start`/`word_end` count words of the Tanzil Simple text, 1-based
(e.g. «يا أيها» is two words there).

## How it works

1. The whole Quran is one continuous word stream, so a quote may run across
   consecutive ayahs; a sentinel blocks matches across surahs.
2. Input bigrams (trigrams for very frequent bigrams) are looked up in an
   in-memory index, then extended into maximal exact matches.
3. Nearby matches (gap ≤ 3 words) are chained into one alignment; the gaps
   become `variant` / `substitute` / `insert` / `delete` operations.
4. Weighted interval scheduling picks non-overlapping spans.
5. An exact span is searched again across the whole corpus to report every
   location.
6. Rules (length, context such as «قال تعالى» or ﴿ ﴾, citation, formulaic
   phrases) set the status.

Normalization: diacritics, Quranic marks, dagger alef, tatweel, bidi marks and
presentation forms are removed or folded; أ إ آ ٱ → ا and ى → ي. Teh marbuta,
waw/yeh hamza and bare hamza are folded only to label a differing word as a
spelling `variant`.

## Options (`Config`)

| option | default | effect |
|---|---|---|
| `diacritics` | `"off"` | `"report"`: compare the marks the writer wrote with the reference; sets `diacritics_ok` and adds `diacritic` diff ops. `"strict"`: as report, and a `verified` match with a wrong mark becomes `altered`. Partial diacritization is fine; Uthmani mark encodings are equivalent to the standard ones. |
| `join_conjunctions` | `False` | joins a detached «و» / «ف» to the next word («و الله» → «والله») |
| `join_lam` | `False` | joins «ل الله» to «لله» |
| `split_merged` | `False` | splits an unknown merged word into two Quran-attested words («ياأيها» → «يا أيها») |
| `include_candidates` | `False` | also return `candidate` matches (`BALANCED` preset) |
| `strict_context` | `False` | a quotation marker («قال تعالى») counts only in the last 6 words of the same sentence. Dev: removes the short false positives; costs about 0.2% span recall. |
| `orth_variants` | `False` | three narrow spelling variants count as `variant`, not an edit: a missing alef beside a hamza («مئة» / «مائة»), a final alef for ى, and one hamza letter for another. Dev: +14 correct verified matches, no new errors. |
| `join_conjunctions` | `False` | (token rule) see above; dev: +5 correct verified, no errors |
| `split_merged` | `False` | (token rule) dev: merge recall 0.45 → 0.75, no precision loss |
| `mode` | `"exact"` | `"ocr"`: unknown words are corrected to the nearest Quran word within `ocr_max_edits` (dot confusions cost 0.5). Matches that use a correction are `needs_review`, never `verified`. Slower: about 0.5 s per 300-word text. |
| `uthmani` | `True` | when an Uthmani file was loaded, words written in Uthmani spelling are resolved to the Simple words they correspond to; the match then reports `script: "uthmani"` and the matched Uthmani words in `reference_uthmani` |

The three token rules are off by default because their effect on `verified`
precision has to be measured on the evaluation set first. Markdown wrapping
(`**`, `>`, `-`), ZWNJ inside words and Persian letters (ی, ک) are handled
without any option.

## Output

`DetectionResult.to_dict()` carries `"schema_version": "4"` and validates
against [`schema/detection.schema.json`](schema/detection.schema.json).
Version 2 added `diacritics_ok`, the `diacritic` diff operation and its
`letter_index`. Version 3 added `script` (`"simple"` or `"uthmani"`). Version 4 adds
the `needs_review` status.

CLI:

```bash
python -m quran_detector --simple data/quran-simple.txt detect a.txt b.txt
python -m quran_detector --simple data/quran-simple.txt --format jsonl detect a.txt
python -m quran_detector --simple data/quran-simple.txt --format text --min-status altered detect -
```

`--format` is `json` (default), `jsonl` (one line per match) or `text`
(tab-separated). `--min-status` keeps that status and stronger ones, in the
order verified, ambiguous, altered, spliced, candidate.

## Installation

```bash
pip install -e ".[dev]"     # tests, mypy, ruff, jsonschema
python -m pytest -q
mypy --strict src
ruff check src tests scripts evaluation
```

The package is typed (`py.typed`).

## Evaluation harness

`evaluation/` is not part of the core and needs no extra dependencies.

Synthetic data (`evaluation/synth.py`): quotes sampled from the Tanzil text,
perturbed (diacritics, spelling, orthographic variants, detached or merged words,
substitutions, insertions, deletions, splices, ayah numbers), and embedded in
filler from real books that contain no Quran text. Books are split into dev and
test by a hash of the file name. Generated files go to `evaluation/data/`, which is
git-ignored because they contain book text.

```bash
python evaluation/synth.py --books "<books folder>" --split dev  --out evaluation/data/synth_dev.jsonl
python evaluation/synth.py --books "<books folder>" --split test --out evaluation/data/synth_test.jsonl
python evaluation/run_eval.py --data evaluation/data/synth_dev.jsonl --set orth_variants=true
python evaluation/tune.py --data evaluation/data/synth_dev.jsonl --out evaluation/reports/tune_dev.jsonl
```

`tune.py` refuses test files. Metric conventions: a prediction matches a gold span
only in the same document; a verified prediction is correct when its words lie
inside a gold location (a fragment of a quote is correct); a verified prediction
inside an altered quote is reported separately as `inside_altered`.

```bash
python evaluation/run_eval.py --simple data/quran-simple.txt --data evaluation/data/dev.jsonl
python evaluation/run_eval.py ... --compare evaluation/reports/OLD.json
```

It reports exact and IoU ≥ 0.5 span P/R/F1, character macro-F1, reference
accuracy, ambiguity coverage, F1 for `altered` and `spliced`, latency, and the
precision of `verified` with a one-sided 95% Clopper–Pearson upper bound on the
error rate. Undefined ratios are reported as `n/a`, not as 0 or 1.

## Known limitations

- **Uthmani input**: resolved through a dictionary learned from aligning the two
  Tanzil texts ayah by ayah. On every 8th ayah, 100% of Uthmani ayahs are found
  (61.8% without it). 53 doubtful alignments (hamza and ya/waw spelling variants,
  such as «رَءَا» → «راي» and «يَبْنَؤُمَّ» → «يا ابن ام») were reviewed and accepted.
  Alignments are 1:1, 1:2 or 1:3 Uthmani-to-Simple words; a 2:1 alignment would
  be reported rather than used. Remaining review items are listed in
  `evaluation/reports/uthmani_alignment.txt`.
- The alignment and dictionary are built when the corpus is loaded (about 8 s
  cold, cached with `cache_dir`).
- **OCR**: `mode="ocr"` corrects single words and splits merged ones. It does not
  yet handle a word split into two wrong pieces, and it is not tuned on real scans.
- Synthetic evaluation is the only accuracy measure so far. It has 253 verified
  matches on dev, so the 95% error bound on precision stays above 1% (about 3%).
  A 1% bound needs several thousand matches.
- Gold labels for quotes of 4 words or fewer without context follow the gate
  (not intended); this policy should be confirmed before comparing to other systems.
- Thresholds in `Config` are defaults, not tuned on real data. Tune them on a
  labelled evaluation set (e.g. IslamicEval 2025 Task 1) before relying on the
  numbers.
- `score` is a ranking heuristic, not a probability.

## Full-corpus tests and data

`data/` is not in the repository. Download `quran-simple.txt` (and optionally
`quran-uthmani.txt`) from <https://tanzil.net/download/> ("Text (with aya
numbers)"), place them in `data/`, and run `python -m pytest`. Without them the
full-corpus tests are skipped. `python scripts/make_fixture.py --dry-run` shows
how the test fixture differs from Tanzil; `scripts/corpus_stats.py` and
`scripts/bench.py` need the same files.

## Attribution

Quran text: Tanzil Project, <https://tanzil.net>. The library never modifies the
Tanzil files, and the attribution is included in every result under `source`.

## Tests

```bash
python -m pytest
```

`tests/fixtures/mini_simple.txt` is a small subset of ayahs used only by the
tests; it is not a substitute for the full Tanzil file.

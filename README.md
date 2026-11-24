# quran-detector

Detect, ground and verify Quran quotes inside Arabic text: articles, book pages, LLM
answers and OCR output. For every quote the library returns:

- its exact character span in the input,
- every location in the Quran it can come from (surah, ayah, word range),
- a word-level diff against the reference text,
- a status decided by explicit, documented rules. No score or model decides the status.

Pure Python 3.10+, no runtime dependencies. Typed (`py.typed`, `mypy --strict` clean).

Version 0.5.0 · output schema 5 · 200 tests · see [Status](#status) for what is done and what is not.

---

## Contents

1. [Quick start](#quick-start)
2. [Data: Tanzil texts](#data-tanzil-texts)
3. [Installation](#installation)
4. [Python API](#python-api)
5. [Command line](#command-line)
6. [Statuses](#statuses)
7. [Output](#output)
8. [How detection works](#how-detection-works)
9. [Configuration reference](#configuration-reference)
10. [Presets](#presets)
11. [Uthmani script](#uthmani-script)
12. [OCR mode](#ocr-mode)
13. [Evaluation](#evaluation)
14. [Performance](#performance)
15. [Known limitations and open issues](#known-limitations-and-open-issues)
16. [Status](#status)
17. [Repository layout](#repository-layout)
18. [Development](#development)
19. [Changelog](#changelog)
20. [Attribution](#attribution)

---

## Quick start

```bash
pip install -e ".[dev]"
# put quran-simple.txt (and optionally quran-uthmani.txt) in data/  (see Data)
python -m pytest -q
```

```python
from quran_detector import Corpus, QuranDetector

corpus = Corpus.from_tanzil("data/quran-simple.txt", "data/quran-uthmani.txt")
det = QuranDetector(corpus)                       # HIGH_PRECISION by default

res = det.detect("قال تعالى: ﴿إن الله مع الصابرين﴾ [الأنفال: 46]")
for m in res.matches:
    print(m.status.value, m.text, m.claimed_ref, m.citation_correct)
# verified إن الله مع الصابرين 8:46 True
```

---

## Data: Tanzil texts

The library needs the Tanzil Quran text in **"Text (with aya numbers)"** format
(one `surah|ayah|text` line per ayah) from <https://tanzil.net/download/>.

| file | required | used for |
|---|---|---|
| `quran-simple.txt` | yes | Simple (Imlaei) text with diacritics. All matching. |
| `quran-uthmani.txt` | no | Uthmani text. Enables Uthmani-spelled input (see [Uthmani script](#uthmani-script)). |

Put them in `data/`. Recommended download options: pause marks, sajdah signs and
tatweel included (the defaults on the Tanzil page).

Notes on the data:

- The Tanzil files are **not** in this repository. Tanzil allows verbatim copying and
  requires attribution with a link to tanzil.net. Do not commit them to a public repository.
- The library never modifies the files. Normalized forms are derived in memory.
- The basmala is part of the first ayah of 113 of the 114 surahs in the Tanzil text
  (surah 9 has none). Word positions in `Ref` count these words.
- Corpus sources are recorded under `source` in every result, with SHA-256 hashes of
  the input files and the Tanzil attribution.

---

### Metadata (optional)

The Tanzil text has no surah names, revelation place or page numbers. These come from
a separate file, `data/quran_meta.json`, which the library reads only to describe where
a match is. Matching never uses it, so results are the same with or without it.

Build the file from a Bayan-schema SQLite database (`surahs` and `ayahs` tables):

```bash
python scripts/import_metadata.py --from "<path to quran.db>"
```

The importer opens the database read-only, reads no text columns, and refuses to write
unless every check passes: 114 surahs, the ayah list equal to the Tanzil list (same
pairs, same order), each surah's `ayah_count` equal to the Tanzil count, and juz, hizb,
rub, page and manzil within their standard ranges and non-decreasing in ayah order.
A corrupted copy is refused with a message such as `page out of range 1..604: 1..999`
and no file is written.

Use the metadata with `--metadata data/quran_meta.json`. Each location then gets
`location_meta` (see [Output](#output)). The database that the sample metadata came from
records no licence, so the file is git-ignored and never committed.

### Provenance checks

`scripts/verify_sources.py` records and checks the data files:

```bash
python scripts/verify_sources.py --init --cross-db "<path to quran.db>"   # write data/SOURCES.json
python scripts/verify_sources.py --cross-db "<path to quran.db>"          # check
```

Three checks, all reported:

1. **Integrity.** The Tanzil files have the hashes recorded in `data/SOURCES.json`, and
   the Tanzil text has 114 surahs and 6236 ayahs.
2. **Structure.** The metadata file matches the Tanzil ayah list and per-surah counts.
3. **Text cross-check** (only with `--cross-db`). The Tanzil text is compared ayah by
   ayah with a second database after folding: the dagger alef is read as an alef, and
   AGGRESSIVE normalization is applied. Only the agreement count is checked against the
   baseline recorded at `--init`, so a known set of differences does not block the run.
   The list of differing ayahs is written to `evaluation/reports/source_crosscheck.md`.

On the current data, the cross-check agrees on 6121 of 6236 Simple ayahs (98.2%).
Of the 115 that differ, 112 are the basmala at ayah 1: Tanzil includes it in the text,
and the other database stores it separately. The other 3 each differ by a single «ي».

A tampered copy fails: a changed digit gives `FAIL integrity`, and a changed character
gives `FAIL sha256 changed`. Exit code is 0 only when every check passes.

## Installation

```bash
pip install -e ".[dev]"    # adds pytest, mypy, ruff, jsonschema
```

Runtime needs only the Python standard library. The `dev` extra is for tests and
checks.

Corpus loading takes about 1 s the first time and about 0.3 s with `cache_dir`
(see [Performance](#performance)).

---

## Python API

```python
from quran_detector import (
    BALANCED, HIGH_PRECISION, Config, Corpus, Level, QuranDetector, Status, normalize,
)

corpus = Corpus.from_tanzil(
    "data/quran-simple.txt",
    "data/quran-uthmani.txt",     # optional
    require_complete=True,        # False only for partial test corpora
    cache_dir=".cache",           # optional: SQLite store keyed by the SHA-256 of the inputs (no pickle)
)

det = QuranDetector(corpus)                          # HIGH_PRECISION
det_b = QuranDetector(corpus, BALANCED)              # also returns candidates
det_x = QuranDetector(corpus, Config(strict_context=True, orth_variants=True))

result = det.detect(text)              # DetectionResult
result.matches                         # list[QuranMatch]
result.to_dict()                       # JSON-serializable, schema_version 4

m = det.verify("اللَّهُ الصَّمَدُ")     # caller asserts the string is a quote
m.status, m.locations                  # verified, [[112:2[1-2]]]; None if no match
```

`verify()` returns the match that covers the most words, or `None`. Compare
`m.text` with the input to see whether the whole string matched.

Helpers exported: `normalize(text, level)` and `Level.LIGHT | STRICT | AGGRESSIVE |
SKELETON`, for applying the same normalization to your own strings.

---

## Command line

```bash
python -m quran_detector --simple data/quran-simple.txt detect article.txt
python -m quran_detector --simple data/quran-simple.txt detect a.txt b.txt
python -m quran_detector --simple data/quran-simple.txt --format jsonl detect a.txt
python -m quran_detector --simple data/quran-simple.txt --format text --min-status altered detect -
python -m quran_detector --simple data/quran-simple.txt verify "قل هو الله أحد"
```

| option | meaning |
|---|---|
| `--simple PATH` | Tanzil Simple text (required) |
| `--uthmani PATH` | Tanzil Uthmani text (optional) |
| `--mode high_precision\|balanced` | preset (default `high_precision`) |
| `--metadata PATH` | `quran_meta.json` (see [Metadata](#metadata-optional)): adds `location_meta` to each location |
| `--allow-partial-corpus` | accept a corpus that is not the full Quran (tests only) |
| `--format json\|jsonl\|text` | output format (default `json`) |
| `--min-status STATUS` | keep this status and the stronger ones: verified, ambiguous, altered, spliced, candidate. See [Known limitations](#known-limitations-and-open-issues) for `needs_review`. |
| `detect PATH...` | one or more files; `-` reads stdin |
| `verify QUOTE` | check one quote string |

`--format`:

- `json`: one file gives the result object. Several files give a list of
  `{"path", "result"}` objects.
- `jsonl`: one line per match, `{"path", "schema_version", "match"}`.
- `text`: tab-separated `path, start, end, status, text`.

---

## Statuses

| status | meaning |
|---|---|
| `verified` | the words are identical to the Quran text after normalization (spelling variants are allowed and listed in `diff`), the span is long enough or has a quotation context, and it occurs in one location. |
| `ambiguous` | identical, but the same words occur in several places. All locations are listed. A citation next to the quote can resolve it. |
| `altered` | a clearly intended quote with substituted, inserted or missing words. The differences are in `diff`. |
| `spliced` | joined directly to another quote from a non-adjacent place. `spliced_with` lists the other part. |
| `candidate` | real Quran words, but too short or too common to call a quote (e.g. «إن شاء الله»). Hidden in `HIGH_PRECISION`, shown in `BALANCED`. |
| `needs_review` | OCR mode only: a match that uses a corrected word. Never `verified`. |

Gate summary (defaults; the full list is in [Configuration reference](#configuration-reference)):

- An exact span is `verified` if it has at least 5 words, or at least 3 words with a
  quotation context. A context is a quotation marker («قال تعالى», «سبحانه», …) or the
  span is wrapped in ﴿ ﴾, « », or quotes.
- A span of 3 or fewer words is never verified without context.
- An altered match needs at least 5 matched words and at least 60% of the words matched.
- A formulaic phrase («الحمد لله رب العالمين», «إنا لله وإنا إليه راجعون») is a
  candidate unless it has context.

A `candidate` is hidden by default. It is returned only with `include_candidates=True`
or the `BALANCED` preset.

---

## Output

### `QuranMatch` fields

| field | type | meaning |
|---|---|---|
| `start_char`, `end_char` | int | span in the input (Python string indexes, code points) |
| `text` | str | the input text of the span |
| `status` | str | one of the statuses above |
| `locations` | list of list of `Ref` | every location; a location is a list of per-ayah refs (multi-ayah quotes) |
| `word_count` | int | words of the input span |
| `matched_words` | int | words equal or variant to the Quran |
| `score` | float | ranking heuristic. **Not** a probability. |
| `diff` | list of `DiffOp` | differences from the reference |
| `reference_text` | str | Simple words of the matched location |
| `reference_uthmani` | list of str | Uthmani words (whole ayahs for Simple matches; matched words for Uthmani matches) |
| `has_context` | bool | whether a quotation context was found |
| `claimed_ref` | str or null | a citation found next to the quote, e.g. `8:46` |
| `citation_correct` | bool or null | whether the citation matches the located ayah |
| `spliced_with` | list of int | indexes of the spliced partner matches |
| `diacritics_ok` | bool or null | with `diacritics != "off"`: whether the marks the writer wrote agree with the reference |
| `script` | str | `"simple"` or `"uthmani"` |
| `location_meta` | list of dict | one entry per location, in the same order as `locations`: `surah_name_ar`, `surah_name_en`, `revelation_place`, `page_start`, `page_end`, `juz_start`, `juz_end`. Empty unless `--metadata` (or a metadata object) is given. |

`Ref`: `surah`, `ayah`, `word_start`, `word_end` (1-based, inclusive, counted in the
Simple text). `str(ref)` gives `8:46[10-13]`.

`DiffOp`: `op` (`variant`, `substitute`, `insert`, `delete`, `diacritic`), `got`,
`expected`, `input_start`, `input_end`, `letter_index` (diacritic ops only).

### Schema history

`DetectionResult.to_dict()` is validated by
[`schema/detection.schema.json`](schema/detection.schema.json).

| version | change |
|---|---|
| 1 (implicit) | the 0.1.0 layout, without a `schema_version` field |
| 2 | first `schema_version` field; `diacritics_ok`, the `diacritic` diff op and `letter_index` |
| 3 | `script` |
| 4 | the `needs_review` status |
| 5 | `location_meta`; `metadata_sha256` in `source` when metadata is used |

---

## How detection works

1. **Tokenize.** Arabic words become tokens with their character offsets. Latin
   words act as barriers, so a quote cannot run across them. Digits, punctuation,
   Quran pause marks, ayah-end glyphs and Markdown symbols are skipped, so
   `**﴿…﴾**`, `> …`, `- …` and ayah numbers inside a quote do not break the span.
2. **Normalize.** Each word has three forms: STRICT (diacritics, tatweel and bidi
   marks removed; أ إ آ ٱ → ا; ى → ي; Persian ی ک → ي ك), AGGRESSIVE (STRICT plus
   ة → ه, ؤ → و, ئ → ي, ء removed) and SKELETON (dot-confusion classes, used by OCR).
   Only STRICT is used for seeding.
3. **Optional token rules** (off by default): join a detached «و» / «ف» (`join_conjunctions`),
   join «ل الله» (`join_lam`), split a merged word (`split_merged`). See [Config](#configuration-reference).
4. **Uthmani resolution** (when an Uthmani file is loaded): words in Uthmani spelling are
   mapped to the Simple words they correspond to (see [Uthmani script](#uthmani-script)).
5. **Seed and extend.** Every input bigram (trigram for very frequent bigrams) is looked
   up in an index over the continuous Quran word stream. Each seed is extended to a
   maximal exact match. Matches never cross a surah boundary.
6. **Chain.** Matches separated by at most `max_gap` words on both sides are chained
   into one alignment. The gaps become `variant`, `substitute`, `insert` or `delete`
   operations, from a word-level edit alignment.
7. **Select.** Weighted interval scheduling chooses non-overlapping spans, so a text
   is not reported twice.
8. **Ground.** An exact span is searched again over the whole corpus. Every location of
   the same words is reported. More than one location makes it `ambiguous`.
9. **Decide.** The gates set the status (see [Statuses](#statuses)). Nothing is
   `verified` on a score. The optional OCR pass (`mode="ocr"`) can only lower a status to
   `needs_review`.
10. **Splice.** Two adjacent matches from non-adjacent places, with no quotation
    marks between them, are marked `spliced`.

---

## Configuration reference

All fields are in `quran_detector.Config`, a frozen dataclass. Defaults are the
`HIGH_PRECISION` values.

### Gates and thresholds

| field | default | meaning |
|---|---|---|
| `min_words` | 5 | an exact span needs this many words to be `verified` without context |
| `min_words_with_context` | 3 | the same, with a quotation context |
| `min_candidate_words` | 3 | exact spans shorter than this are dropped |
| `max_gap` | 3 | words that may be bridged inside one chain |
| `min_altered_matched` | 5 | an altered match needs at least this many matched words |
| `min_altered_ratio` | 0.6 | … and at least this fraction of its words matched |
| `frequent_bigram` | 300 | bigrams more frequent than this are seeded by trigrams |
| `context_window` | 40 | characters searched for a quotation context |
| `citation_window` | 60 | characters searched for a citation after the quote |

### Context and variants

| field | default | meaning |
|---|---|---|
| `strict_context` | `False` | a quotation marker counts only if it is in the last 6 words of the same sentence. The sentence-local check removes false short matches (see [Evaluation](#evaluation)). **Recommended on; not yet the default, pending a decision.** |
| `orth_variants` | `False` | three narrow spelling variants count as `variant` instead of an edit: a missing alef beside a hamza (مئة / مائة), a final alef for ى (أقصا / أقصى), and one hamza-family letter for another (يسئل / يسأل). Words that differ in a middle weak letter (قول / قال) are not variants. |
| `include_candidates` | `False` | also return `candidate` matches |

### Diacritics

| field | default | meaning |
|---|---|---|
| `diacritics` | `"off"` | `"report"`: compare the marks the writer wrote with the reference. Sets `diacritics_ok` and adds `diacritic` diff ops. `"strict"`: as report, and a `verified` match with a wrong mark becomes `altered`. Partial diacritization is fine. Letters the writer left unmarked are not errors. |

### Token rules (off by default)

| field | default | effect |
|---|---|---|
| `join_conjunctions` | `False` | «و الله» → «والله», «ف الله» → «فالله». Skipped when the split pair occurs in the Quran. |
| `join_lam` | `False` | «ل الله» → «لله» |
| `split_merged` | `False` | an unknown merged word splits into two Quran-attested words («ياأيها» → «يا أيها») |

### Uthmani

| field | default | meaning |
|---|---|---|
| `uthmani` | `True` | resolve Uthmani-spelled words when the corpus has an Uthmani file. No effect without one. |

### OCR

| field | default | meaning |
|---|---|---|
| `mode` | `"exact"` | `"ocr"` enables the OCR correction pass (see [OCR mode](#ocr-mode)) |
| `ocr_max_edits` | 2.0 | the largest weighted edit distance accepted for a correction |

### Validation

Invalid values raise `ValueError` at construction: `diacritics` must be `off`,
`report` or `strict`; `mode` must be `exact` or `ocr`.

---

## Presets

| preset | differences from `Config()` | use |
|---|---|---|
| `HIGH_PRECISION` | none (the defaults) | production default |
| `BALANCED` | `min_words=4`, `include_candidates=True` | returns candidates; for review, not for automatic use |

---

## Uthmani script

Uthmani text (Madina Mushaf) spells many words differently from the Imlaei text. Three
differences matter, all found in the Tanzil data:

- U+0670 (dagger alef) is an alef that Imlaei either omits («الرَّحْمَٰنِ» → «الرحمن») or
  writes in full («ٱلْعَٰلَمِينَ» → «العالمين»).
- U+06E5 / U+06E6 (small waw / small yeh) are dropped in pronoun suffixes («بِهِۦ» → «به»),
  but in «وَلِىِّۦ» → «وَلِيِّي» the small yeh is a real letter. Both readings are kept.
- Hamza written on its own line («ءَامَنُوا» → «امنوا») and ة written as و + dagger
  («ٱلصَّلَوٰةَ» → «الصلاة») are orthographic.

How it works: each Uthmani word has three STRICT keys. Each ayah's Uthmani words are
aligned to its Simple words by dynamic programming over 1:1, 1:2 and 1:3 blocks, so
«يَٰٓأَيُّهَا» aligns to «يا أيها» and «يَبْنَؤُمَّ» to «يا ابن ام». Blocks with an
alignment cost up to 0.25 are accepted; 1:1 and 1:3 blocks up to 0.5 were reviewed by
hand and accepted (53 blocks). A dictionary maps each key to its Simple word. A key
that maps to two different words is removed. Exact alignments always take precedence
over reviewed ones.

Results:

- Recall on every 8th Uthmani ayah: 780 of 780 (100%). Without Uthmani resolution:
  482 of 780 (61.8%).
- Simple input is unaffected: 0 differences across 1,559 sampled Simple ayahs with
  resolution on and off.
- Matches made through Uthmani text report `script: "uthmani"`, and
  `reference_uthmani` holds the matched Uthmani words.

Remaining items are in `evaluation/reports/uthmani_alignment.txt`. The alignment
checker is `scripts/check_uthmani_alignment.py`.

---

## OCR mode

`Config(mode="ocr")` corrects unknown words in noisy scanned text.

For each word with no exact match in the Quran:

1. A merged word that splits into two known words is split («ياايها» → «يا ايها»).
2. Otherwise the nearest Quran word is taken if it is within `ocr_max_edits`. A
   substitution inside one dot-class costs 0.5 (ب ت ث and so on); any other edit costs 1.
   A tie between two different words is left alone.

Candidates come from a skeleton index (words with the same dot-class skeleton) and a
character 4-gram index. Corrections are cached per corpus.

A match that uses a correction is `needs_review`, never `verified`.

Measured:

- Clean synthetic dev text: no precision loss against the default (verified precision
  0.980 in both; 5 errors in each). Span recall is slightly higher (0.840 vs 0.830).
- Speed: median 152 ms per document, against about 4 ms by default.
- Not measured on real scans. Synthetic OCR noise is covered by unit tests only.

---

## Evaluation

Everything in this section is measured on **synthetic** data. It is a controlled test,
not a measure of real-world accuracy.

### Synthetic data

`evaluation/synth.py` builds documents from two sources:

- **Quotes**: spans of 2 to 30 words sampled from the Tanzil Simple text, each perturbed
  by one of these kinds:

  | kind | perturbation | gold status |
  |---|---|---|
  | `exact` | none | verified / ambiguous |
  | `strip_marks` | all diacritics removed | verified / ambiguous |
  | `spelling` | ة → ه, أ → ا in one word | verified / ambiguous |
  | `orth` | a narrow orthographic variant (see `orth_variants`) | verified / ambiguous |
  | `detach` | «و» split from its word | verified |
  | `merge` | two words joined | verified |
  | `ayah_num` | an ayah number inside the quote | verified |
  | `substitute` | one word replaced by a word with different consonants | altered |
  | `delete` | one interior word removed | altered |
  | `insert` | one ordinary word inserted | altered |
  | `splice` | two exact quotes placed next to each other | spliced |
  | `subrun` | exact halves of an altered quote, context only (not scored as intended) | verified |

  An altered quote is discarded if its changed text still occurs in the Quran.
- **Filler**: passages from real books (the books folder you provide). A passage is used
  only if the detector finds no Quran text in it, even in BALANCED mode.
- Quotes of 3 words or fewer are intended only with a quotation context. Without context
  they are negatives, so a `verified` match on them counts as an error.
- Dev and test sets come from different books (split by a hash of the file name).

Gold offsets are checked against the Quran words at each gold location. 709 of 714
exact spans matched exactly; the 5 others are the intended spelling variants.

### Metrics

| metric | definition |
|---|---|
| span P/R/F1 (IoU ≥ 0.5) | one-to-one greedy matching within each document. A prediction matches when the intervals overlap with IoU ≥ 0.5. Candidates are not positive predictions. |
| verified precision | share of `verified` predictions whose words lie inside a gold location of a matched intended span. A fragment of a gold quote counts as correct. |
| inside_altered | `verified` predictions covering ≥ 80% of an intended altered quote. Exact Quran text inside a damaged quote: reported, not scored. |
| error bound | one-sided 95% Clopper–Pearson upper bound on the error rate (pure Python, tested against closed forms) |
| negative FP docs | documents with no intended quote that get a positive prediction |
| recall by kind | span recall per perturbation kind |

### Results

All runs use the default settings unless stated. A setting is shown as its `Config`
change.

**Dev set** (400 documents, seed 1, used for tuning):

| setting | span recall | verified precision | verified errors / n | error bound |
|---|---|---|---|---|
| default | 0.830 | 0.980 | 5 / 253 | 0.041 |
| `strict_context` | 0.828 | 0.984 | 4 / 251 | — |
| `orth_variants` | 0.830 | 0.981 | 5 / 267 | — |
| `strict_context` + `orth_variants` | 0.828 | 0.985 | 4 / 265 | 0.034 |

**Test set A** (400 documents, seed 1, run once):

| setting | span recall | span precision | verified errors / n | error bound | negative FP docs |
|---|---|---|---|---|---|
| default | 0.814 | 1.000 | 0 / 243 | 0.012 | 0 |
| rule-selected (see below) | 0.901 | 0.988 | 1 / 273 | 0.017 | 0 |

**Test set B** (3,000 documents, seed 2, fresh, run once):

| setting | span recall | span precision | verified errors / n | error bound | negative FP docs |
|---|---|---|---|---|---|
| default | 0.813 | 0.994 | 11 / 1754 | 0.0104 | 0 |
| `strict_context=True` | 0.812 | 0.995 | 8 / 1735 | 0.0083 | 0 |
| rule-selected | 0.894 | 0.989 | 2 / 1909 | 0.0033 | 3 |

The rule-selected setting is `min_words=4`, `min_words_with_context=4`,
`min_altered_matched=4`, `min_altered_ratio=0.5`, `max_gap=2`. It was chosen on dev by a
grid search over 648 configurations (`evaluation/tune.py`), with the rule "highest recall
at verified precision ≥ 0.99 and no extra negative false positives".

Set A was the basis for the earlier decision to keep the defaults. Set B, which is three
times larger, showed 11 verified errors with the defaults. Nine of them are matches of
3 words. `strict_context` removes 3 of the 11 and leaves 8. Set B is the better guide.

**Token rules (dev):**

| setting | merge recall | span recall | verified precision |
|---|---|---|---|
| default | 0.45 | 0.830 | 0.980 |
| `split_merged` | 0.75 | 0.842 | 0.981 |
| `join_conjunctions` | 0.45 | 0.830 | 0.981 (+5 verified, 0 new errors) |

**OCR mode (clean dev):** verified precision 0.980 (5 errors); span recall 0.840.

### Reproducing the evaluation

```bash
# data (book folder is yours; it is never committed)
python evaluation/synth.py --books "<books folder>" --split dev  --n 400  --seed 1 --out evaluation/data/synth_dev.jsonl
python evaluation/synth.py --books "<books folder>" --split test --n 400  --seed 1 --out evaluation/data/synth_test.jsonl

# one configuration
python evaluation/run_eval.py --simple data/quran-simple.txt --data evaluation/data/synth_dev.jsonl \
    --set strict_context=true --out-dir evaluation/reports

# compare two runs
python evaluation/run_eval.py ... --compare evaluation/reports/OLD.json

# grid search on dev (refuses test files)
python evaluation/tune.py --data evaluation/data/synth_dev.jsonl --out evaluation/reports/tune_dev.jsonl
```

`run_eval.py --set NAME=VALUE` overrides one `Config` field (repeatable). Reports go to
`evaluation/reports/` as JSON and Markdown.

### How to read the error bound

With n verified matches and k errors, the 95% upper bound on the error rate is roughly
3/n when k = 0. Reaching a 1% bound needs several thousand verified matches with no
errors. The dev set (253) cannot do it. Set B (about 1,750) gets to about 0.8–1.0%.

---

## Performance

Measured on the bench text (1,166 words, 10 sampled quotes, seed 1), default settings:

| operation | median | p95 |
|---|---|---|
| detect | 16 ms | 26 ms |

Corpus loading (Simple + Uthmani):

| case | time |
|---|---|
| cold build | about 1 s (Simple only); about 8 s with Uthmani alignment |
| warm cache (`cache_dir`) | about 0.3–0.5 s |

The cache is a SQLite file (`corpus-<key>.sqlite`), keyed by the SHA-256 of the Tanzil
input bytes and the cache version. It holds plain data only: text, integers, and raw
array bytes. Loading it runs no code, unlike the pickle cache used before 0.5.0. Warm
load is about 0.3–0.5 s on the full corpus. A file that is missing, corrupt, from another
version or built from other inputs is rebuilt. The cache is derived from the Tanzil
files, which remain the source of truth.

OCR mode: about 150 ms median per document (about 300 words).

The `score` field is not a performance measure.

Run the benchmark: `python scripts/bench.py`.

---

## Known limitations and open issues

**Accuracy**

- The verified-precision target (≥ 99%) is not confirmed. The current defaults show
  11 errors in 1,754 verified matches on set B; the 95% bound is about 1%. The
  rule-selected setting has fewer errors but produces false matches in 3 negative
  documents.
- The 95% bound on the defaults reaches 1% only on the largest test set. More data
  is needed for a firm claim.
- Synthetic gold is the only accuracy measure. Real quotations differ: they are
  paraphrased, mistyped, cited with varying formats, and often embedded in long
  commentary. The synthetic set does not capture those cases.
- The gold rule for quotes of 4 words or fewer without context affects all recall
  figures. A different policy would move them.
- Formulaic phrases (for example «الحمد لله رب العالمين») are candidates without context.
  The formulaic list is small. It is not evaluated on a formulaic-phrase test set.

**Behaviour**

- `--min-status` (CLI) does not know `needs_review` and drops those matches. Decide
  where `needs_review` ranks, then add it to the CLI ordering.
- A quotation marker counts within 40 characters in the default mode. This is why
  `strict_context` is recommended (see [Evaluation](#evaluation)).
- A damaged quote is usually reported as one `altered` match. Its exact halves are
  usually not reported as separate matches.
- The Uthmani dictionary is built from the aligned Tanzil texts. Words not in the
  corpus are not resolved. 2:1 alignments (two Uthmani words for one Simple word) are
  reported, not used.

**OCR**

- Not tuned on real scans. Not evaluated on noisy text except in unit tests.
- Does not correct a word split into two wrong pieces.
- Clean spelling variants can be flagged `needs_review`; this is by design, but it
  should be reviewed on real data.

**Scope**

- Only the Quran is matched. Hadith, poetry and other Arabic texts are not separate
  sources; a hadith that quotes a verse is matched as a verse.
- No neural component. Task 09 (neural intent tagger) is not started. It needs an
  explicit decision after error analysis, which is in
  `evaluation/reports/error_analysis_09.md`. The current evidence does not show a need.
- No IslamicEval 2025 adapter. The official dev files are not in the project.

---

## Status

| step | state |
|---|---|
| Core detector, citations, diacritics, Uthmani, token rules, OCR mode | implemented, tested |
| Synthetic evaluation data and harness | implemented |
| Threshold grid search on dev | done (648 configurations) |
| Gate defaults | **open decision** (see [Evaluation](#evaluation)) |
| IslamicEval adapter | blocked: dev files not in the project |
| Neural intent tagger | not started; needs approval |
| Packaging, CI, JSON Schema | implemented; CI workflow not run from this environment |
| Metadata import, provenance checks, SQLite cache | implemented; the metadata source database has no recorded licence, so its file is not committed |
| `CLAUDE.md` rule 1 mention of metadata | **not done**: needs your OK (it edits the project instructions) |

---

## Repository layout

```
src/quran_detector/
    normalizer.py     STRICT / AGGRESSIVE / SKELETON normalization
    tokenizer.py      Arabic word tokens with offsets; Latin = barrier
    corpus.py         Tanzil loader, word stream, bigram/trigram index, Uthmani dictionary, cache
    detector.py       seed → extend → chain → select → ground → decide → splice
    rules.py          optional token rules (join_conjunctions, join_lam, split_merged)
    uthmani.py        Uthmani keys, alignment, token resolution
    variants.py       narrow orthographic variants (orth_variants)
    ocr.py            OCR correction pass (mode="ocr")
    diacritics.py     diacritic comparison and Uthmani equivalences
    citations.py      parses writer-given references ([البقرة: 153], (2:153), ...)
    tanzil.py         Tanzil reader (order and uniqueness checked); default data folder
    store.py          SQLite corpus store (replaces the pickle cache)
    metadata.py       surah names, revelation place, juz, page; validated Bayan importer
    sources.py        provenance: hashes, structure, text cross-check (fold)
    models.py         Status, Ref, DiffOp, QuranMatch, DetectionResult, SCHEMA_VERSION
    cli.py            command line
evaluation/
    stats.py          Clopper–Pearson bound (pure Python)
    metrics.py        span, status, verified precision, breakdowns
    gold.py           gold file reader with validation
    synth.py          synthetic data generator
    run_eval.py       evaluation runner, --set and --compare
    tune.py           dev-only grid search
    reports/          generated (git-ignored)
    data/             generated (git-ignored; contains book text)
scripts/
    make_fixture.py   regenerate the test fixture from Tanzil
    corpus_stats.py   corpus statistics
    bench.py          build and detect latency
    check_uthmani_alignment.py   alignment review list
    scan_books.py    run the detector over a folder of books (summaries only)
    import_metadata.py   build data/quran_meta.json from a Bayan-schema database (validated)
    verify_sources.py    integrity, structure and text cross-check of the data files
schema/detection.schema.json    JSON Schema for to_dict()
tests/                            unit, full-corpus (skipped without data/), evaluation tests
.github/workflows/ci.yml          lint, types, tests on Python 3.10–3.13
```

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q                        # 200 tests
ruff check src tests scripts evaluation
ruff format --check src tests scripts evaluation
mypy --strict src
```

Full-corpus tests run when `data/quran-simple.txt` exists and are skipped otherwise.

Conventions:

- A behaviour change ships with at least one positive and one negative test.
- A change to a gate or threshold needs an evaluation run and a before/after table.
  Dev is for tuning; the test set is used once per decision.
- Output fields change only with a schema version bump and a README update.
- Quran text in tests is read from the Tanzil files or the fixture. It is not typed by hand.

---

## Changelog

| version | changes |
|---|---|
| 0.1.0 | exact matching, grounding, ambiguity, altered and spliced statuses, citations, CLI |
| 0.2.0 | diacritics (`report`/`strict`), `diacritic` diff op, schema 2 |
| 0.3.0 | Uthmani resolution with reviewed alignments, `script` field, schema 3 |
| 0.4.0 | token rules, `strict_context`, `orth_variants`, OCR mode, `needs_review`, schema 4, synthetic evaluation, dev-only grid search, metric fixes |
| 0.5.0 | SQLite corpus store replaces the pickle cache (`CACHE_VERSION` 8); one validated Tanzil reader with order checks; optional metadata (`location_meta`, schema 5) from a validated Bayan-schema import; provenance checks (`verify_sources.py`); surah names verified against the metadata |

---

## Attribution

Quran text: Tanzil Project, <https://tanzil.net>. Tanzil allows verbatim copying with
attribution and a link to tanzil.net. The library never modifies the Tanzil files, and
the attribution is included in every result under `source`.

The synthetic evaluation uses passages from books supplied by the user. Those books are
not part of this repository, and their text must not be committed.

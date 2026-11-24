"""Tests for the optional token rules (rules.py) and text robustness (task 07).

All Quran text is read from the fixture corpus and modified programmatically
here; the only typed Arabic is ordinary (non-Quran) text.
"""

import re
from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.normalizer import normalize
from quran_detector.rules import apply_token_rules
from quran_detector.tokenizer import tokenize

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"
HARAKAT = "[ً-ْ]"


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


def ayah(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].simple_text


def det(corpus, **flags):
    return QuranDetector(corpus, Config(**flags))


def only_match(d, text):
    ms = d.detect(text).matches
    assert len(ms) == 1, [m.status for m in ms]
    return ms[0]


# ------------------------------------------------------ join_conjunctions
def test_detached_conjunction_joined_when_enabled(corpus):
    v = ayah(corpus, 2, 153)
    words = v.split()
    idx = next(i for i, w in enumerate(words) if normalize(w).startswith("وال"))
    words[idx] = re.sub("^و" + HARAKAT + "*", "و ", words[idx])  # «وَالصَّلَاةِ» → «و الصَّلَاةِ»
    detached = " ".join(words)
    assert detached != v
    on = only_match(det(corpus, join_conjunctions=True), detached)
    assert on.status is Status.VERIFIED and on.diff == []
    off = det(corpus).detect(detached).matches
    assert not any(m.status is Status.VERIFIED and m.word_count == 11 for m in off)


def test_conjunction_not_joined_when_joined_form_unknown(corpus):
    # «و» + a word whose joined form is not in the Quran: the tokens stay apart
    toks = tokenize("و ذهب")
    out = apply_token_rules("و ذهب", toks, corpus, Config(join_conjunctions=True))
    assert len(out) == 2


# ------------------------------------------------------------- join_lam
def test_lam_prefix_joined_when_enabled(corpus):
    # 1:2 has «لِلَّهِ»; write it as «ل الله» (alef of الله written, «لله» → «ل ال»+«له»)
    v = ayah(corpus, 1, 2)
    words = v.split()
    idx = next(i for i, w in enumerate(words) if re.sub(HARAKAT, "", w) == "لله" or w.startswith("لِ"))
    raw = words[idx]
    detached = "ل ال" + raw[1:]
    words[idx] = detached
    text = "قال تعالى: ﴿" + " ".join(words) + "﴾"
    on = only_match(det(corpus, join_lam=True), text)
    assert on.status is Status.VERIFIED and on.diff == []
    off = det(corpus).detect(text).matches
    assert not any(m.status is Status.VERIFIED and m.word_count == len(words) for m in off)


# ---------------------------------------------------------- split_merged
def test_merged_words_split_when_enabled(corpus):
    v = ayah(corpus, 2, 153)
    words = v.split()
    merged = words[0] + words[1]  # «يَا أَيُّهَا» → «يَاأَيُّهَا»
    text = " ".join([merged] + words[2:])
    on = only_match(det(corpus, split_merged=True), text)
    assert on.status is Status.VERIFIED
    off = det(corpus).detect(text).matches
    assert not any(m.status is Status.VERIFIED and m.word_count == 11 for m in off)


def test_unknown_plain_word_is_not_split(corpus):
    # an ordinary word that does not split into two Quran-attested words stays whole
    toks = tokenize("ذهبت إلى المدرسة")
    out = apply_token_rules("ذهبت إلى المدرسة", toks, corpus, Config(split_merged=True))
    assert len(out) == len(toks)


def test_rules_off_by_default(corpus):
    cfg = Config()
    assert not (cfg.join_conjunctions or cfg.join_lam or cfg.split_merged)
    toks = tokenize("و ذهب")
    assert apply_token_rules("و ذهب", toks, corpus, cfg) is toks


# ------------------------------------------------- markdown from LLM output
@pytest.mark.parametrize(
    "wrap",
    ["**﴿{}﴾**", "> ﴿{}﴾", "- ﴿{}﴾", "**«{}»**", "* «{}» *"],
)
def test_markdown_wrapping_does_not_break_span(corpus, wrap):
    v = ayah(corpus, 2, 153)
    text = "قال تعالى: " + wrap.format(v)
    m = only_match(det(corpus), text)
    assert m.status is Status.VERIFIED
    assert m.text == v
    assert "*" not in m.text and ">" not in m.text
    assert text[m.start_char : m.end_char] == m.text


def test_markdown_without_quran_gives_nothing(corpus):
    assert det(corpus).detect("**عنوان**\n- بند أول\n> ملاحظة عامة").matches == []


# ------------------------------------------- presentation forms and ZWNJ
def test_zwnj_inside_words_is_ignored(corpus):
    v = ayah(corpus, 2, 153)
    zw = " ".join(w[:2] + "‌" + w[2:] if len(w) > 3 else w for w in v.split())
    m = only_match(det(corpus), zw)
    assert m.status is Status.VERIFIED and m.diff == []


def test_persian_letters_fold_to_arabic(corpus):
    v = ayah(corpus, 2, 153)
    persian = v.replace("ي", "ی").replace("ك", "ک")
    assert persian != v
    m = only_match(det(corpus), persian)
    assert m.status is Status.VERIFIED and m.diff == []


def test_latin_separator_still_breaks_match(corpus):
    v = ayah(corpus, 2, 153).split()
    text = " ".join(v[:5] + ["hello"] + v[5:])
    ms = det(corpus).detect(text).matches
    assert ms and all("hello" not in m.text for m in ms)
    assert not any(m.word_count > 6 for m in ms)  # no run across the barrier

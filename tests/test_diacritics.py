"""Diacritic (tashkeel) checking: modes off / report / strict.

Quran text is read from the fixture corpus inside the tests, never typed here.
Unit tests on the comparison use only harakat combined with a single letter.
"""

import re
from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.diacritics import compare

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"
FATHA = "َ"
KASRA = "ِ"
SHADDA = "ّ"
MARKS = re.compile("[ً-ْ]")


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


@pytest.fixture(scope="module")
def verse(corpus):
    """2:153 as written in the corpus, with its full diacritics."""
    return corpus.ayahs[corpus.ayah_index[(2, 153)]].simple_text


def detector(corpus, mode):
    return QuranDetector(corpus, Config(diacritics=mode))


def test_config_rejects_unknown_mode():
    with pytest.raises(ValueError):
        Config(diacritics="maybe")


# ------------------------------------------------------------ positive cases
@pytest.mark.parametrize("mode", ["off", "report", "strict"])
def test_correct_diacritics_ok_in_every_mode(corpus, verse, mode):
    [m] = detector(corpus, mode).detect(verse).matches
    assert m.status is Status.VERIFIED
    assert m.diacritics_ok is (None if mode == "off" else True)
    assert not [d for d in m.diff if d.op == "diacritic"]


def test_partial_diacritization_is_ok(corpus, verse):
    # keep only shadda: every mark the writer wrote is also in the reference
    partial = "".join(ch for ch in verse if ch == SHADDA or not MARKS.match(ch))
    assert MARKS.search(partial)  # some marks remain
    [m] = detector(corpus, "report").detect(partial).matches
    assert m.status is Status.VERIFIED
    assert m.diacritics_ok is True


def test_uthmani_encodings_match_simple_reference():
    assert compare("بࣰ", "بً") == (True, [])  # open fathatan
    assert compare("بࣱ", "بٍ") == (True, [])  # open kasratan
    assert compare("بࣲ", "بٌ") == (True, [])  # open dammatan
    assert compare("بۡ", "بْ") == (True, [])  # small high sukun


def test_mark_order_is_canonical():
    # shadda + fatha in either order is the same letter
    assert compare("ب" + SHADDA + FATHA, "ب" + FATHA + SHADDA) == (True, [])


# ------------------------------------------------------------ negative cases
def test_wrong_vowel_is_a_diacritic_error(corpus, verse):
    idx = verse.index(FATHA)
    wrong = verse[:idx] + KASRA + verse[idx + 1 :]
    det_report = detector(corpus, "report").detect(wrong).matches
    [m] = det_report
    assert m.status is Status.VERIFIED  # report mode: status unchanged
    assert m.diacritics_ok is False
    [d] = [d for d in m.diff if d.op == "diacritic"]
    assert isinstance(d.letter_index, int)
    assert d.got and d.expected and d.got != d.expected
    assert d.input_start is not None and d.input_end is not None


def test_wrong_vowel_is_altered_only_in_strict(corpus, verse):
    idx = verse.index(FATHA)
    wrong = verse[:idx] + KASRA + verse[idx + 1 :]
    [m] = detector(corpus, "strict").detect(wrong).matches
    assert m.status is Status.ALTERED
    assert m.diacritics_ok is False


def test_wrong_vowel_not_reported_when_off(corpus, verse):
    idx = verse.index(FATHA)
    wrong = verse[:idx] + KASRA + verse[idx + 1 :]
    [m] = detector(corpus, "off").detect(wrong).matches
    assert m.status is Status.VERIFIED
    assert m.diacritics_ok is None
    assert not [d for d in m.diff if d.op == "diacritic"]


def test_wrong_vowel_unit():
    assert compare("بِ", "بَ") == (True, [0])


def test_no_diacritics_in_input_means_no_check(corpus, verse):
    bare = MARKS.sub("", verse)
    [m] = detector(corpus, "strict").detect(bare).matches
    assert m.status is Status.VERIFIED
    assert m.diacritics_ok is None
    assert not [d for d in m.diff if d.op == "diacritic"]


def test_marks_not_in_reference_are_errors():
    # the reference has no shadda here, the input adds one
    assert compare("بّ", "ب") == (True, [0])

"""Uthmani matching (task 02), on the fixture corpus.

Quran text is read from the fixture files inside the tests. The few typed words are
ordinary Arabic used as negatives.
"""

from pathlib import Path

import pytest

from quran_detector import Config, Corpus, Level, QuranDetector, Status, normalize
from quran_detector.uthmani import ACCEPT_COST, align_ayah, uthmani_keys

FIX = Path(__file__).parent / "fixtures"
SIMPLE = FIX / "mini_simple.txt"
UTHMANI = FIX / "mini_uthmani.txt"


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(SIMPLE, UTHMANI, require_complete=False)


@pytest.fixture(scope="module")
def det(corpus):
    return QuranDetector(corpus)


def uthmani_ayah(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].uthmani_text


def simple_ayah(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].simple_text


def refs(m):
    return [[(r.surah, r.ayah, r.word_start, r.word_end) for r in loc] for loc in m.locations]


# ---------------------------------------------------------------- keys
def test_dagger_alef_key_depends_on_the_word(corpus):
    # 1:2 has «ٱلْعَٰلَمِينَ»: Imlaei writes an alef there, so key2 (dagger as alef) is right
    words = [w for w in uthmani_ayah(corpus, 1, 2).split() if "ٰ" in w]
    assert words
    k1, k2, _ = uthmani_keys(words[0])
    assert k2 == "العالمين" and k1 != k2


def test_small_marks_are_counted_in_the_letter_variant(corpus):
    # property over the real Uthmani words: k3 has one letter per small waw/yeh
    checked = 0
    for ay in corpus.ayahs:
        for w in (ay.uthmani_text or "").split():
            small = sum(ch in "ۥۦ" for ch in w)
            if small:
                k1, _, k3 = uthmani_keys(w)
                assert len(k3) == len(k1) + small
                checked += 1
    assert checked > 0


def test_plain_word_has_identical_keys():
    assert uthmani_keys("كتاب") == ("كتاب", "كتاب", "كتاب")


# ------------------------------------------------------------ alignment
def test_one_uthmani_word_aligns_to_two_simple_words(corpus):
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    u = [w for w in ay.uthmani_text.split() if any(c.isalpha() for c in w)]
    s = [corpus.raw_words[p] for p in range(ay.start, ay.end)]
    s = [normalize(w, Level.STRICT) for w in s]
    blocks = align_ayah(u, s)
    assert any((b.u1 - b.u0, b.s1 - b.s0) == (1, 2) for b in blocks)
    assert all(b.cost <= ACCEPT_COST for b in blocks if b.u1 - b.u0 == 1 and b.s1 - b.s0 == 2)


def test_unrelated_words_are_not_accepted_by_alignment():
    # negative: ordinary words that are not the same word
    [b] = [b for b in align_ayah(["مدرسة"], ["البيت"]) if b.u1 - b.u0 == 1]
    assert b.cost > ACCEPT_COST


def test_uthmani_dictionary_has_no_colliding_keys(corpus):
    # every key in the dictionary maps to one Simple word (or one 1:2 pair)
    assert all(isinstance(v, tuple) and len(v) in (1, 2) for v in corpus.uthmani_map.values())


# -------------------------------------------------------------- matching
def test_uthmani_quote_verified_with_script_and_uthmani_refs(corpus, det):
    text = uthmani_ayah(corpus, 2, 153)
    [m] = det.detect(text).matches
    assert m.status is Status.VERIFIED
    assert m.script == "uthmani"
    assert refs(m) == [[(2, 153, 1, 11)]]
    lettered = [w for w in uthmani_ayah(corpus, 2, 153).split() if any(c.isalpha() for c in w)]
    assert m.reference_uthmani == lettered  # the matched Uthmani words, one per block


def test_simple_text_still_reports_simple_script(corpus, det):
    [m] = det.detect(simple_ayah(corpus, 2, 153)).matches
    assert m.status is Status.VERIFIED and m.script == "simple"


def test_uthmani_resolution_can_be_switched_off(corpus):
    off = QuranDetector(corpus, Config(uthmani=False))
    ms = off.detect(uthmani_ayah(corpus, 2, 153)).matches
    assert not any(m.status is Status.VERIFIED and m.script == "uthmani" for m in ms)


def test_replaced_uthmani_word_is_altered_with_uthmani_expected(corpus, det):
    words = uthmani_ayah(corpus, 2, 153).split()
    original = words[5]
    words[5] = uthmani_ayah(corpus, 8, 46).split()[0]
    text = " ".join(words)
    [m] = [x for x in det.detect(text).matches if x.word_count >= 5]
    assert m.status is Status.ALTERED and m.script == "uthmani"
    [d] = m.diff
    assert d.op == "substitute"
    assert d.expected == original  # the expected word is the Uthmani word


def test_ordinary_text_with_quranic_looking_words_does_not_match(det):
    # negative: plain sentence that contains «العلمين» and «الكتب» as ordinary words
    assert det.detect("كان الكتب مرتبا على الرف والعلمين في المكتبة").matches == []

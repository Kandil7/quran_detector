"""Orthographic variants (variants.py, Config.orth_variants).

The word pairs are single lexical items used to test the rule itself. The detector
test reads its Quran text from the fixture corpus.
"""

from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.variants import orth_variant

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


@pytest.mark.parametrize(
    "a,b",
    [
        ("مئه", "مائه"),  # R1: missing alef beside a hamza carrier
        ("اقصا", "اقصي"),  # R2: final alef for alef maqsura
        ("يسئل", "يسال"),  # R3: hamza-on-yeh for hamza-on-alef
        ("يسال", "يسال"),  # identical
    ],
)
def test_orthographic_variants_accepted(a, b):
    assert orth_variant(a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("قول", "قال"),  # a different verb form, not a spelling choice
        ("من", "مان"),  # a middle letter added without a hamza carrier
        ("قال", "قول"),
        ("ذهب", "ذهبت"),  # different word
        ("ابن", "ابنه"),  # ta marbuta is not an R1/R2/R3 change
        ("كتب", "كتاب"),  # two letters differ
    ],
)
def test_other_differences_rejected(a, b):
    assert not orth_variant(a, b)


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


def test_middle_letter_change_is_still_an_edit(corpus):
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    words = ay.simple_text.split()
    i = next(i for i, w in enumerate(words) if "ا" in w[1:-1])
    w = words[i]
    j = next(k for k in range(1, len(w) - 1) if w[k] == "ا")
    words[i] = w[:j] + "و" + w[j + 1 :]
    text = " ".join(words)
    on = QuranDetector(corpus, Config(orth_variants=True)).detect(text).matches
    assert not any(m.status is Status.VERIFIED and m.word_count >= 5 for m in on)

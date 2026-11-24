"""OCR mode (ocr.py, Config(mode="ocr")).

Quran text is read from the fixture corpus. The noisy ordinary sentences are typed
on purpose: they are negatives.
"""

from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.ocr import best_candidate, weighted_edit

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


def refs(m):
    return [[(r.surah, r.ayah, r.word_start, r.word_end) for r in loc] for loc in m.locations]


def test_mode_is_validated():
    with pytest.raises(ValueError):
        Config(mode="fuzzy")


def test_dot_confusion_costs_half_an_edit():
    assert weighted_edit("ب", "ت") == 0.5  # same dot-class
    assert weighted_edit("ب", "ك") == 1.0  # different class
    assert weighted_edit("كتاب", "كتاب") == 0.0


def test_best_candidate_corrects_a_dot_swap(corpus):
    assert best_candidate("تالصبر", corpus, 2.0) == corpus.word_id("بالصبر")


def test_unrelated_word_has_no_candidate(corpus):
    # negative: an ordinary word far from every Quran word
    assert best_candidate("مدرسة", corpus, 1.0) is None


def test_ocr_noise_on_a_quote_needs_review_and_is_never_verified(corpus):
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    noisy = ay.simple_text.replace("ب", "ت")  # every «ب» read as «ت»
    assert noisy != ay.simple_text
    exact = QuranDetector(corpus, Config()).detect(noisy).matches
    assert not any(m.status is Status.VERIFIED for m in exact)

    ms = QuranDetector(corpus, Config(mode="ocr")).detect(noisy).matches
    [m] = [m for m in ms if m.word_count >= 5]
    assert m.status is Status.NEEDS_REVIEW
    assert refs(m) == [[(2, 153, 1, 11)]]
    assert not any(x.status is Status.VERIFIED for x in ms)


def test_ocr_mode_leaves_clean_quotes_as_verified(corpus):
    # a clean quote is still verified in OCR mode: no corrections are needed
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    [m] = [x for x in QuranDetector(corpus, Config(mode="ocr")).detect(ay.simple_text).matches]
    assert m.status is Status.VERIFIED


def test_ordinary_noisy_text_gives_nothing_substantial(corpus):
    # negative: ordinary text with dot-noise must not produce a quote-sized match
    text = "دهبت الى السوق صباحا واشتريت الخبز والحليب ثم عدت الى البيت"
    ms = QuranDetector(corpus, Config(mode="ocr")).detect(text).matches
    assert not any(m.word_count >= 5 for m in ms)
    assert not any(m.status is Status.VERIFIED for m in ms)

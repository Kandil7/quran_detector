import unicodedata
from pathlib import Path

import pytest

from quran_detector import BALANCED, Corpus, QuranDetector, Status, normalize
from quran_detector.citations import find_citation
from quran_detector.tokenizer import tokenize

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


@pytest.fixture(scope="module")
def det(corpus):
    return QuranDetector(corpus)


def refs(m):
    return [[(r.surah, r.ayah, r.word_start, r.word_end) for r in loc] for loc in m.locations]


# ------------------------------------------------------------------ corpus
def test_corpus_requires_complete_by_default():
    with pytest.raises(ValueError):
        Corpus.from_tanzil(FIXTURE)


def test_pause_marks_are_not_words(corpus):
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    assert ay.word_count == 11


# -------------------------------------------------------------- normalizer
@pytest.mark.parametrize(
    "a,b",
    [
        ("إِنَّ اللَّهَ", "ان الله"),
        ("الرَّحْمَٰنِ", "الرحمن"),
        ("ٱلْحَمْدُ", "الحمد"),
        ("على", "علي"),
        ("كـــتـــاب", "كتاب"),
    ],
)
def test_strict_normalization(a, b):
    assert " ".join(normalize(w) for w in a.split()) == b


def test_presentation_forms_are_folded():
    def isolated(ch):
        try:
            return unicodedata.lookup(unicodedata.name(ch) + " ISOLATED FORM")
        except KeyError:
            return ch

    pres = "".join(isolated(c) for c in "قل")
    assert pres != "قل"
    assert normalize(pres) == "قل"


def test_tokenizer_offsets_and_skips_numbers():
    text = "قال: ﴿قل هو الله أحد (1)﴾"
    toks = tokenize(text)
    assert [text[t.start : t.end] for t in toks] == ["قال", "قل", "هو", "الله", "أحد"]


# --------------------------------------------------------------- detection
def test_negative_plain_text(det):
    assert det.detect("ذهبت إلى السوق صباحا واشتريت الخبز والحليب").matches == []


def test_exact_verified_with_offsets(det):
    text = "في مقال عن الصبر: يا أيها الذين آمنوا استعينوا بالصبر والصلاة إن الله مع الصابرين. انتهى"
    [m] = det.detect(text).matches
    assert m.status is Status.VERIFIED
    assert refs(m) == [[(2, 153, 1, 11)]]
    assert text[m.start_char : m.end_char] == m.text
    assert m.text.startswith("يا أيها") and m.text.endswith("الصابرين")


def test_repeated_phrase_is_ambiguous(det):
    [m] = det.detect("قال تعالى: إن الله مع الصابرين").matches
    assert m.status is Status.AMBIGUOUS
    assert sorted(loc[0].surah for loc in m.locations) == [2, 8]


def test_longer_context_resolves_repetition(det):
    [m] = det.detect("واصبروا إن الله مع الصابرين").matches
    assert m.status is Status.VERIFIED
    assert refs(m) == [[(8, 46, 9, 13)]]


def test_citation_resolves_ambiguity(det):
    [m] = det.detect("قال تعالى: ﴿إن الله مع الصابرين﴾ [الأنفال: 46]").matches
    assert m.status is Status.VERIFIED
    assert m.claimed_ref == "8:46" and m.citation_correct is True
    assert refs(m) == [[(8, 46, 10, 13)]]


def test_wrong_citation_flagged(det):
    [m] = det.detect("﴿قل هو الله أحد﴾ (سورة البقرة، الآية 2)").matches
    assert m.status is Status.VERIFIED
    assert refs(m) == [[(112, 1, 5, 8)]]  # Tanzil 112:1 starts with the basmala
    assert m.claimed_ref == "2:2" and m.citation_correct is False


def test_multi_ayah_with_numbers(det):
    [m] = det.detect("قل هو الله أحد (1) الله الصمد (2) لم يلد ولم يولد (3)").matches
    assert m.status is Status.VERIFIED
    assert refs(m) == [[(112, 1, 5, 8), (112, 2, 1, 2), (112, 3, 1, 4)]]


def test_spelling_variant_still_verified(det):
    [m] = det.detect("يا ايها الذين امنوا استعينوا بالصبر والصلاه ان الله مع الصابرين").matches
    assert m.status is Status.VERIFIED
    assert [d.op for d in m.diff] == ["variant"]


def test_variant_at_edge_is_included(det):
    [m] = det.detect("قال تعالى: الذين إذا أصابتهم مصيبه قالوا").matches
    assert m.status is Status.VERIFIED and m.word_count == 5
    assert [(d.op, d.got) for d in m.diff] == [("variant", "مصيبه")]


def test_altered_word_detected(det, corpus):
    text = "يا أيها الذين آمنوا استعينوا بالصبر والصيام إن الله مع الصابرين"
    [m] = det.detect(text).matches
    assert m.status is Status.ALTERED
    assert refs(m)[0] == [(2, 153, 1, 11)]
    [d] = m.diff
    # expected word = 7th word of 2:153 in the Tanzil text, read from the corpus
    expected = corpus.raw_words[corpus.ayahs[corpus.ayah_index[(2, 153)]].start + 6]
    assert d.op == "substitute" and d.got == "والصيام" and d.expected == expected
    assert text[d.input_start : d.input_end] == "والصيام"


def test_deleted_word_detected(det):
    [m] = det.detect("وأطيعوا الله ورسوله ولا تنازعوا وتذهب ريحكم واصبروا إن الله مع الصابرين").matches
    assert m.status is Status.ALTERED
    assert [(d.op, d.expected) for d in m.diff] == [("delete", "فَتَفْشَلُوا")]


def test_spliced_quote(det):
    ms = det.detect("قال تعالى: ﴿قل هو الله أحد إن الإنسان لفي خسر﴾").matches
    assert [m.status for m in ms] == [Status.SPLICED, Status.SPLICED]
    assert [refs(m)[0][0][:2] for m in ms] == [(112, 1), (103, 2)]
    assert ms[0].spliced_with == [1] and ms[1].spliced_with == [0]


def test_separately_bracketed_quotes_not_spliced(det):
    ms = det.detect("قال تعالى: ﴿قل هو الله أحد﴾ ﴿إن الإنسان لفي خسر﴾").matches
    assert [m.status for m in ms] == [Status.VERIFIED, Status.VERIFIED]


def test_formulaic_phrase_not_reported_by_default(det, corpus):
    text = "توفي جده رحمه الله، إنا لله وإنا إليه راجعون."
    assert det.detect(text).matches == []
    [m] = QuranDetector(corpus, BALANCED).detect(text).matches
    assert m.status is Status.CANDIDATE


def test_short_phrase_needs_context(det):
    assert det.detect("وهذا من فضل الله الصمد عندهم").matches == []


def test_latin_word_breaks_match(det):
    assert det.detect("قل هو الله hello أحد الله الصمد").matches == []


def test_no_match_across_surahs(det):
    # end of 112 followed by start of nothing: 1:7 tail + 2:153 head must not chain
    ms = det.detect("غير المغضوب عليهم ولا الضالين يا أيها الذين آمنوا استعينوا").matches
    assert all(len({r.surah for r in loc}) == 1 for m in ms for loc in m.locations)


def test_verify_api(det):
    m = det.verify("اللَّهُ الصَّمَدُ")
    assert m is not None and m.status is Status.VERIFIED
    assert refs(m) == [[(112, 2, 1, 2)]]
    assert det.verify("ذهبت إلى السوق") is None


# ---------------------------------------------------------------- citations
@pytest.mark.parametrize(
    "s,expected",
    [
        ("[البقرة: 153]", (2, 153, 153)),
        ("(سورة آل عمران، الآية ١٩٠)", (3, 190, 190)),
        ("(2:153-154)", (2, 153, 154)),
        ("الإخلاص 1", (112, 1, 1)),
        ("بدون مرجع هنا", None),
    ],
)
def test_find_citation(s, expected):
    c = find_citation(s)
    assert (None if c is None else (c.surah, c.ayah_start, c.ayah_end)) == expected

"""Full-corpus tests. Skipped when the Tanzil files are not in data/.

Quran text used as test input is read from the Tanzil file inside the tests,
never typed here. Only the ordinary Arabic news paragraph is written by hand,
and it contains no Quran text.
"""

import re
from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.normalizer import Level, normalize_phrase

ROOT = Path(__file__).resolve().parent.parent
SIMPLE = ROOT / "data" / "quran-simple.txt"
UTHMANI = ROOT / "data" / "quran-uthmani.txt"

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(),
    reason="full corpus needs data/quran-simple.txt (Tanzil, https://tanzil.net/download/)",
)

MARKS = re.compile("[ً-ٰٟۖ-ۭ]")


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(SIMPLE, UTHMANI if UTHMANI.exists() else None)


@pytest.fixture(scope="module")
def det(corpus):
    return QuranDetector(corpus, Config())


def ayah_text(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].simple_text


def refs(m):
    return [[(r.surah, r.ayah, r.word_start, r.word_end) for r in loc] for loc in m.locations]


def test_corpus_shape(corpus):
    assert len(corpus) == 6236
    assert len(corpus.surah_ayah_count) == 114
    assert corpus.surah_ayah_count[2] == 286
    assert corpus.surah_ayah_count[9] == 129
    assert corpus.surah_ayah_count[112] == 4


def test_repeated_phrase_with_context_is_ambiguous(corpus, det):
    phrase = normalize_phrase(ayah_text(corpus, 8, 46), Level.LIGHT)
    words = phrase.split()[-4:]  # "إن الله مع الصابرين", read from 8:46
    [m] = det.detect("قال تعالى: ﴿" + " ".join(words) + "﴾").matches
    assert m.status is Status.AMBIGUOUS
    locs = {loc[0][:2] for loc in refs(m)}
    assert (2, 153) in locs and (8, 46) in locs


def test_refrain_with_context_has_31_locations_in_surah_55(corpus, det):
    refrain = ayah_text(corpus, 55, 13)  # «فبأي آلاء ربكما تكذبان»
    [m] = det.detect("قال تعالى: ﴿" + refrain + "﴾").matches
    assert m.status is Status.AMBIGUOUS
    assert len(m.locations) == 31
    assert all(loc[0].surah == 55 for loc in m.locations)


def test_whole_fatiha_without_diacritics_is_verified(corpus, det):
    text = " ".join(ayah_text(corpus, 1, a) for a in range(1, 8))
    bare = MARKS.sub("", text)
    [m] = det.detect(bare).matches
    assert m.status is Status.VERIFIED
    assert len(m.locations) == 1
    first, last = m.locations[0][0], m.locations[0][-1]
    assert (first.surah, first.ayah) == (1, 1) and (last.surah, last.ayah) == (1, 7)


NEWS = (
    "أعلنت الهيئة المحلية للمياه أن أعمال صيانة الشبكة الرئيسية في الحي الشرقي "
    "ستبدأ يوم الأحد المقبل وتستمر لمدة ثلاثة أيام، وقد يتأثر خلالها ضغط المياه "
    "في عدد من المنازل. ودعت الهيئة السكان إلى تخزين كميات كافية من الماء والتعاون "
    "مع الفرق الميدانية. وقال المتحدث باسم الهيئة إن الفريق الفني سيعمل على "
    "استبدال الأنابيب القديمة وتحسين الضغط في المناطق المرتفعة، مشيرا إلى أن الخدمة "
    "ستعود إلى طبيعتها بعد انتهاء الأعمال. وتشهد المدينة هذا الشهر حركة تجارية "
    "نشطة مع اقتراب موسم المعارض، وتتوقع الغرف التجارية زيادة في عدد الزوار "
    "والمشاركين من خارج البلاد."
)


def test_ordinary_news_paragraph_has_no_matches(det):
    assert det.detect(NEWS).matches == []


# ------------------------------------------------------------ Uthmani (task 02)
needs_uthmani = pytest.mark.skipif(not UTHMANI.exists(), reason="needs data/quran-uthmani.txt")


def uthmani_text(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].uthmani_text


@needs_uthmani
def test_uthmani_2_153_verified_as_uthmani(corpus, det):
    [m] = det.detect(uthmani_text(corpus, 2, 153)).matches
    assert m.status is Status.VERIFIED and m.script == "uthmani"
    assert refs(m) == [[(2, 153, 1, 11)]]


@needs_uthmani
def test_uthmani_2_43_with_salat_spelling_verified(corpus, det):
    # 2:43 contains «ٱلصَّلَوٰةَ» (Imlaei «الصلاة»)
    [m] = det.detect(uthmani_text(corpus, 2, 43)).matches
    assert m.status is Status.VERIFIED and m.script == "uthmani"
    assert refs(m) == [[(2, 43, 1, 7)]]


@needs_uthmani
def test_uthmani_surah_112_verified(corpus, det):
    text = " ".join(uthmani_text(corpus, 112, a) for a in range(1, 5))
    [m] = det.detect(text).matches
    assert m.status is Status.VERIFIED
    firsts = {(loc[0].surah, loc[0].ayah) for loc in m.locations}
    assert (112, 1) in firsts or any((r.surah, r.ayah) == (112, 1) for loc in m.locations for r in loc)
    assert all(r.surah == 112 for loc in m.locations for r in loc)


@needs_uthmani
def test_uthmani_1_2_is_ambiguous_because_10_10_repeats_it(corpus, det):
    # The spec expected "verified". The phrase «الحمد لله رب العالمين» also occurs in
    # 10:10, so the correct status under the same gates is ambiguous (the Simple text
    # gives the same result). Both locations are reported.
    [m] = det.detect("قال تعالى: ﴿" + uthmani_text(corpus, 1, 2) + "﴾").matches
    assert m.status is Status.AMBIGUOUS
    found = {(loc[0].surah, loc[0].ayah) for loc in m.locations}
    assert (1, 2) in found and (10, 10) in found


@needs_uthmani
def test_uthmani_recall_on_sampled_ayahs(corpus):
    det = QuranDetector(corpus)
    total = found = 0
    for idx, ay in enumerate(corpus.ayahs):
        if idx % 16:
            continue
        total += 1
        ms = det.detect("قال تعالى: ﴿" + ay.uthmani_text + "﴾").matches
        if any(
            m.status in (Status.VERIFIED, Status.AMBIGUOUS)
            and any((r.surah, r.ayah) == (ay.surah, ay.ayah) for loc in m.locations for r in loc)
            for m in ms
        ):
            found += 1
    assert found / total >= 0.98, (found, total)


@needs_uthmani
def test_simple_input_unchanged_by_uthmani_resolution(corpus):
    on = QuranDetector(corpus, Config(include_candidates=True))
    off = QuranDetector(corpus, Config(include_candidates=True, uthmani=False))
    for idx, ay in enumerate(corpus.ayahs):
        if idx % 40:
            continue
        text = "قال تعالى: ﴿" + ay.simple_text + "﴾"
        a = [(m.start_char, m.end_char, m.status) for m in on.detect(text).matches]
        b = [(m.start_char, m.end_char, m.status) for m in off.detect(text).matches]
        assert a == b, (ay.surah, ay.ayah)


@needs_uthmani
def test_reviewed_hamza_variant_is_accepted(corpus):
    # 6:76 «رَءَا» aligned 1:1 to Imlaei «راي» (cost 0.33): accepted after review
    assert corpus.uthmani_map.get("رءا") == ("راي",)


@needs_uthmani
def test_20_94_uses_the_correct_one_to_three_split(corpus, det):
    # «قَالَ يَبْنَؤُمَّ» is «قال يا ابن ام»: 1:1 for «قال», 1:3 for «يَبْنَؤُمَّ»
    assert corpus.uthmani_map.get("قال") == ("قال",)
    assert corpus.uthmani_map.get("يبنؤم") == ("يا", "ابن", "ام")
    ay = corpus.ayahs[corpus.ayah_index[(20, 94)]]
    [m] = det.detect("قال تعالى: ﴿" + ay.uthmani_text + "﴾").matches
    assert m.status is Status.VERIFIED and m.script == "uthmani"
    assert all(not s.startswith("20:94") for s in corpus.uthmani_suspicious)


# ------------------------------------------------------- variants (variants.py)
def test_final_yeh_written_as_alef_is_verified_only_with_the_flag(corpus):
    from quran_detector import Level, normalize

    # a verse of at least 5 words whose last word ends in yeh (STRICT)
    ay = next(
        a
        for a in corpus.ayahs
        if len(a.simple_text.split()) >= 5
        and normalize(a.simple_text.split()[-1], Level.STRICT).endswith("ي")
    )
    words = ay.simple_text.split()
    w = words[-1]
    k = max(j for j, ch in enumerate(w) if ch in "يى")  # yeh or alef maqsura ending the word
    words[-1] = w[:k] + "ا" + w[k + 1 :]  # ... becomes an alef
    text = " ".join(words)

    off = QuranDetector(corpus, Config()).detect(text).matches
    # without the flag, no verified match covers the altered last word (the prefix still verifies)
    assert not any(m.status is Status.VERIFIED and m.end_char == len(text.rstrip()) for m in off)

    on = QuranDetector(corpus, Config(orth_variants=True)).detect(text).matches
    [m] = [m for m in on if m.end_char == len(text.rstrip())]
    assert m.status is Status.VERIFIED
    assert [d.op for d in m.diff] == ["variant"]

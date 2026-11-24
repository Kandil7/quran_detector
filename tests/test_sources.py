"""Provenance checks (sources.py): fold, text cross-check, hashes, structure.

Inputs are fixture ayahs and placeholder strings. No Quran text is typed here.
"""

from pathlib import Path

from quran_detector.metadata import AyahMeta, QuranMetadata
from quran_detector.sources import check_hashes, check_structure, crosscheck_texts, fold
from quran_detector.tanzil import read_tanzil

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


def test_fold_reads_dagger_alef_as_alef():
    assert fold("\u0670") == fold("ا")  # the same letter in two spellings
    assert fold("ب") != fold("ت")  # different letters stay different


def test_crosscheck_counts_agreement_and_reports_differences():
    tz = {(1, 1): "ب" + "ا" + "ب", (1, 2): "ت" + "ا" + "ت"}
    same = {(1, 1): "ب\u0670" + "ب", (1, 2): "ت" + "ا" + "ت"}  # dagger spelling of the same
    res = crosscheck_texts(tz, same)
    assert res.agree == 2 and res.differ == []  # both ayahs agree after folding
    other = {(1, 1): "ب" + "ا" + "ب", (1, 2): "ت" + "ا" + "د"}
    res2 = crosscheck_texts(tz, other)
    assert res2.agree == 1 and [(s, a) for s, a, *_ in res2.differ] == [(1, 2)]


def test_crosscheck_reports_an_ayah_missing_from_the_other_text():
    res = crosscheck_texts({(1, 1): "ب"}, {})
    assert res.total == 1 and res.agree == 0 and len(res.differ) == 1


def test_hash_check_passes_on_unchanged_files_and_fails_on_change(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("one", encoding="utf-8")
    from quran_detector.sources import file_entry

    manifest = {"files": {"x.txt": file_entry(f)}}
    assert check_hashes(manifest, tmp_path) == []
    f.write_text("two", encoding="utf-8")
    problems = check_hashes(manifest, tmp_path)
    assert problems and "sha256 changed" in problems[0]
    assert check_hashes({"files": {"gone.txt": {"sha256": "0", "bytes": 0}}}, tmp_path)


def test_structure_check_against_fixture_pairs():
    pairs = [(s, a) for s, a, _ in read_tanzil(FIXTURE)]
    counts: dict[int, int] = {}
    for s, a in pairs:
        counts[s] = max(counts.get(s, 0), a)
    surahs = {s: {"ayah_count": n} for s, n in counts.items()}
    ayahs = {p: AyahMeta(1, 1, 1, 1, 1) for p in pairs}
    good = QuranMetadata(surahs, ayahs, {})
    assert check_structure(good, pairs) == []
    bad_surahs = {**surahs, 2: {"ayah_count": 999}}
    assert any("surah 2" in p for p in check_structure(QuranMetadata(bad_surahs, ayahs, {}), pairs))

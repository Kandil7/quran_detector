"""Metadata import (validated) and location metadata in results.

The Bayan-style database is built here from the fixture's ayah list, so it contains only
ordinary numbers and placeholder names. Quran text is never typed.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.metadata import AyahMeta, MetadataError, QuranMetadata, import_bayan
from quran_detector.tanzil import read_tanzil

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


def fixture_pairs():
    return [(s, a) for s, a, _ in read_tanzil(FIXTURE)]


def make_bayan(path, pairs=None, *, ayah_count_override=None, drop=None, extra=None, page_override=None):
    """A Bayan-schema database over the fixture ayahs, with optional faults."""
    pairs = list(pairs if pairs is not None else fixture_pairs())
    if drop is not None:
        pairs.remove(drop)
    if extra is not None:
        pairs.append(extra)
        pairs.sort()
    counts: dict[int, int] = {}
    for s, a in fixture_pairs():  # surah counts are the fixture's, even when faults are added
        counts[s] = max(counts.get(s, 0), a)
    if ayah_count_override is not None:
        counts[ayah_count_override[0]] = ayah_count_override[1]
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE surahs (id INTEGER PRIMARY KEY, name_ar TEXT, name_en TEXT, name_simple TEXT, "
        "ayah_count INTEGER, revelation_type TEXT, revelation_order INTEGER, bism_pre INTEGER)"
    )
    con.execute(
        "CREATE TABLE ayahs (id INTEGER PRIMARY KEY, surah_id INTEGER, ayah_number INTEGER, "
        "juz INTEGER, hizb INTEGER, rub INTEGER, page INTEGER, manzil INTEGER)"
    )
    for sid, n in sorted(counts.items()):
        con.execute(
            "INSERT INTO surahs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, f"name-{sid}", f"Name-{sid}", f"name{sid}", n, "Makkah" if sid != 9 else "Madinah", sid, 0),
        )
    for i, (s, a) in enumerate(pairs, start=1):
        page = page_override.get((s, a), 1 + i) if page_override else 1 + i
        con.execute(
            "INSERT INTO ayahs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, s, a, 1, 1, 1 + i // 10, page, 1),
        )
    con.commit()
    con.close()
    return path


@pytest.fixture
def tanzil_copy(tmp_path):
    return FIXTURE


# ------------------------------------------------------------------ import: positive
def test_valid_database_imports(tmp_path):
    db = make_bayan(tmp_path / "ok.db")
    data = import_bayan(db, FIXTURE, require_complete=False)
    assert len(data["ayahs"]) == len(fixture_pairs())
    assert data["surahs"]["112"]["name_en"] == "Name-112"
    assert data["source"]["adapter"] == "bayan-v1"
    assert len(data["source"]["database_sha256"]) == 64


def test_database_is_opened_read_only(tmp_path):
    db = make_bayan(tmp_path / "ro.db")
    import_bayan(db, FIXTURE, require_complete=False)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ayahs").fetchone()[0] == len(fixture_pairs())
    con.close()


# ---------------------------------------------------------- import: each check refuses
def test_wrong_ayah_count_is_refused(tmp_path):
    db = make_bayan(tmp_path / "c.db", ayah_count_override=(2, 999))
    with pytest.raises(MetadataError, match="ayah_count"):
        import_bayan(db, FIXTURE, require_complete=False)


def test_missing_ayah_is_refused(tmp_path):
    db = make_bayan(tmp_path / "m.db", drop=(1, 3))
    with pytest.raises(MetadataError, match="ayah list differs"):
        import_bayan(db, FIXTURE, require_complete=False)


def test_extra_ayah_is_refused(tmp_path):
    db = make_bayan(tmp_path / "e.db", extra=(1, 99))
    with pytest.raises(MetadataError, match="ayah list differs"):
        import_bayan(db, FIXTURE, require_complete=False)


def test_page_out_of_range_is_refused(tmp_path):
    first = fixture_pairs()[0]
    db = make_bayan(tmp_path / "p.db", page_override={first: 999})
    with pytest.raises(MetadataError, match="out of range"):
        import_bayan(db, FIXTURE, require_complete=False)


def test_non_monotonic_page_is_refused(tmp_path):
    pairs = fixture_pairs()
    db = make_bayan(tmp_path / "n.db", page_override={pairs[2]: 1})
    with pytest.raises(MetadataError, match="non-decreasing"):
        import_bayan(db, FIXTURE, require_complete=False)


def test_partial_database_is_refused_for_the_complete_quran(tmp_path):
    db = make_bayan(tmp_path / "partial.db")
    with pytest.raises(MetadataError, match="114 surahs"):
        import_bayan(db, FIXTURE, require_complete=True)


def test_wrong_schema_is_refused(tmp_path):
    db = tmp_path / "other.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE something (x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(MetadataError, match="not the Bayan layout"):
        import_bayan(db, FIXTURE, require_complete=False)


# ------------------------------------------------------- location metadata in results
def metadata_for_fixture(db_path):
    data = import_bayan(db_path, FIXTURE, require_complete=False)
    surahs = {int(k): v for k, v in data["surahs"].items()}
    ayahs = {
        (s, a): AyahMeta(juz, hizb, rub, page, manzil) for s, a, juz, hizb, rub, page, manzil in data["ayahs"]
    }
    return QuranMetadata(surahs, ayahs, data["source"])


def test_detector_adds_location_metadata(tmp_path):
    db = make_bayan(tmp_path / "loc.db")
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False)
    det = QuranDetector(corpus, Config(), metadata_for_fixture(db))
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    [m] = det.detect(ay.simple_text).matches
    assert m.status is Status.VERIFIED
    [meta] = m.location_meta
    assert meta["surah_name_en"] == "Name-2"
    assert meta["revelation_place"] == "Makkah"
    assert meta["page_start"] <= meta["page_end"]
    assert meta["juz_start"] == 1


def test_matching_is_unchanged_by_metadata(tmp_path):
    db = make_bayan(tmp_path / "same.db")
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False)
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    plain = QuranDetector(corpus).detect(ay.simple_text).matches
    with_meta = QuranDetector(corpus, Config(), metadata_for_fixture(db)).detect(ay.simple_text).matches
    assert [(m.start_char, m.end_char, m.status, m.locations) for m in plain] == [
        (m.start_char, m.end_char, m.status, m.locations) for m in with_meta
    ]
    assert plain[0].location_meta == [] and with_meta[0].location_meta != []


def test_output_with_metadata_is_json_serializable(tmp_path):
    db = make_bayan(tmp_path / "json.db")
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False)
    ay = corpus.ayahs[corpus.ayah_index[(2, 153)]]
    result = QuranDetector(corpus, Config(), metadata_for_fixture(db)).detect(ay.simple_text)
    json.dumps(result.to_dict(), ensure_ascii=False)


def test_load_rejects_partial_metadata(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"format": 1, "surahs": {}, "ayahs": []}), encoding="utf-8")
    with pytest.raises(MetadataError, match="114 surahs"):
        QuranMetadata.load(p)


# ------------------------------------------ hand-typed surah names vs imported metadata
REPO_META = Path(__file__).resolve().parent.parent / "data" / "quran_meta.json"


@pytest.mark.skipif(not REPO_META.exists(), reason="needs data/quran_meta.json (scripts/import_metadata.py)")
def test_hand_typed_surah_names_match_the_imported_metadata():
    from quran_detector.citations import SURAH_NAMES
    from quran_detector.normalizer import Level, normalize

    meta = QuranMetadata.load(REPO_META)
    for i, name in enumerate(SURAH_NAMES, start=1):
        assert normalize(name, Level.AGGRESSIVE) == normalize(meta.surahs[i]["name_ar"], Level.AGGRESSIVE), i

"""SQLite corpus store: equal results, safe format, and rebuild on any mismatch.

The fixtures are Tanzil text read from tests/fixtures. Nothing Quran-related is typed.
"""

import sqlite3
from pathlib import Path

import pytest

from quran_detector import Corpus, QuranDetector
from quran_detector.store import StoreError, read_store

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"
UTHMANI = Path(__file__).parent / "fixtures" / "mini_uthmani.txt"


@pytest.fixture
def builds(monkeypatch):
    calls = []
    original = Corpus.__dict__["_build_from_tanzil"].__func__

    def counting(cls, *args):
        calls.append(args)
        return original(cls, *args)

    monkeypatch.setattr(Corpus, "_build_from_tanzil", classmethod(counting))
    return calls


def store_file(cache: Path) -> Path:
    [p] = list(cache.glob("corpus-*.sqlite"))
    return p


def test_loaded_corpus_equals_fresh_build(tmp_path):
    fresh = Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False)
    Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False, cache_dir=tmp_path)
    loaded = Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False, cache_dir=tmp_path)
    assert loaded.stream == fresh.stream
    assert loaded.pos_block == fresh.pos_block
    assert loaded.vocab == fresh.vocab
    assert loaded.uthmani_map == fresh.uthmani_map
    assert loaded.block_text == fresh.block_text
    assert loaded.ayahs == fresh.ayahs
    assert set(loaded.bigrams) == set(fresh.bigrams)


def test_detection_is_identical_from_store_and_fresh_build(tmp_path):
    fresh = QuranDetector(Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False))
    Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False, cache_dir=tmp_path)
    loaded = QuranDetector(Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False, cache_dir=tmp_path))
    ay = fresh.corpus.ayahs[fresh.corpus.ayah_index[(2, 153)]]
    for text in (ay.simple_text, ay.uthmani_text):
        a = [(m.start_char, m.end_char, m.status, m.script) for m in fresh.detect(text).matches]
        b = [(m.start_char, m.end_char, m.status, m.script) for m in loaded.detect(text).matches]
        assert a == b and a


def test_store_is_sqlite_with_no_pickle(tmp_path):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    raw = store_file(tmp_path).read_bytes()
    assert raw.startswith(b"SQLite format 3\x00")
    assert not raw.startswith(b"\x80")  # pickle protocol marker
    con = sqlite3.connect(store_file(tmp_path))
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    assert {"meta", "parts"} <= names


def test_no_temporary_files_are_left_behind(tmp_path):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_changed_cache_version_is_rebuilt(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    con = sqlite3.connect(store_file(tmp_path))
    con.execute("UPDATE meta SET value = '0' WHERE key = 'cache_version'")
    con.commit()
    con.close()
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 2


def test_tampered_key_is_rebuilt(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    con = sqlite3.connect(store_file(tmp_path))
    con.execute("UPDATE meta SET value = 'deadbeef' WHERE key = 'cache_key'")
    con.commit()
    con.close()
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 2


def test_missing_part_is_rebuilt(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    con = sqlite3.connect(store_file(tmp_path))
    con.execute("DELETE FROM parts WHERE name = 'stream'")
    con.commit()
    con.close()
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 2 and len(corpus) > 0


def test_truncated_file_is_rebuilt(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    p = store_file(tmp_path)
    p.write_bytes(p.read_bytes()[:200])
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 2


def test_read_store_rejects_wrong_key_directly(tmp_path):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    with pytest.raises(StoreError):
        read_store(store_file(tmp_path), "8", "not-the-key")

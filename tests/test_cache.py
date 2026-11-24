"""Optional corpus cache (corpus.from_tanzil(..., cache_dir=...)).

The cache key is a hash of the input bytes, so a changed Tanzil file must never
be served from the cache.
"""

import shutil
from pathlib import Path

import pytest

from quran_detector import Corpus

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"
UTHMANI = Path(__file__).parent / "fixtures" / "mini_uthmani.txt"


@pytest.fixture
def builds(monkeypatch):
    """Count how many times the corpus is actually built (not loaded from cache)."""
    calls = []
    original = Corpus.__dict__["_build_from_tanzil"].__func__

    def counting(cls, *args):
        calls.append(args)
        return original(cls, *args)

    monkeypatch.setattr(Corpus, "_build_from_tanzil", classmethod(counting))
    return calls


def test_second_load_comes_from_cache(tmp_path, builds):
    first = Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    second = Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 1
    assert len(first) == len(second) and first.stream == second.stream
    assert len(list(tmp_path.glob("corpus-*.pkl"))) == 1


def test_changed_file_invalidates_cache(tmp_path, builds):
    src = tmp_path / "src.txt"
    shutil.copyfile(FIXTURE, src)
    cache = tmp_path / "cache"
    Corpus.from_tanzil(src, require_complete=False, cache_dir=cache)
    # one byte-level change in the Tanzil file: a new key, so a rebuild
    src.write_text(src.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    Corpus.from_tanzil(src, require_complete=False, cache_dir=cache)
    assert len(builds) == 2
    assert len(list(cache.glob("corpus-*.pkl"))) == 2


def test_uthmani_file_is_part_of_the_key(tmp_path, builds):
    cache = tmp_path / "cache"
    Corpus.from_tanzil(FIXTURE, UTHMANI, require_complete=False, cache_dir=cache)
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=cache)
    assert len(builds) == 2  # with and without Uthmani are different corpora


def test_corrupt_cache_file_is_rebuilt(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    [cached] = tmp_path.glob("corpus-*.pkl")
    cached.write_bytes(b"not a pickle")
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False, cache_dir=tmp_path)
    assert len(builds) == 2
    assert len(corpus) > 0


def test_no_cache_dir_writes_nothing(tmp_path, builds):
    Corpus.from_tanzil(FIXTURE, require_complete=False)
    assert list(tmp_path.iterdir()) == []
    assert len(builds) == 1

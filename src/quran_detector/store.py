"""SQLite store for a built corpus (replaces the old pickle cache).

The store is a derived, rebuildable artifact. The Tanzil text files stay the source of
truth; a store is only ever written from them, and it is ignored when the inputs,
the cache version or the store format do not match.

Why not pickle: `pickle.load` runs arbitrary code. A SQLite file holds plain data
(text, integers, raw array bytes), so reading it cannot execute anything.

Layout:
  meta(key TEXT PRIMARY KEY, value TEXT)      store_format, cache_version, cache_key, ...
  parts(name TEXT PRIMARY KEY, data BLOB)     one row per corpus part; JSON or raw bytes

This module knows only about plain values. `Corpus.to_parts()` and
`Corpus._from_parts()` in corpus.py are the only places that map a Corpus onto them.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from array import array
from pathlib import Path
from typing import Any

STORE_FORMAT = 1
ARRAY_TYPECODE = "i"
_ARRAY_ITEMSIZE = array(ARRAY_TYPECODE).itemsize
_ARRAY_PARTS = ("stream", "pos_ayah", "pos_word", "pos_block")


class StoreError(Exception):
    """The file is not a usable store (wrong format, version, key or content)."""


def write_store(path: Path, meta: dict[str, str], parts: dict[str, Any]) -> None:
    """Write `parts` to `path` atomically (temporary file, then os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        con = sqlite3.connect(tmp)
        try:
            con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute("CREATE TABLE parts (name TEXT PRIMARY KEY, data BLOB NOT NULL)")
            full_meta = {"store_format": str(STORE_FORMAT), "array_itemsize": str(_ARRAY_ITEMSIZE), **meta}
            con.executemany("INSERT INTO meta VALUES (?, ?)", sorted(full_meta.items()))
            rows = []
            for name, value in sorted(parts.items()):
                if name in _ARRAY_PARTS:
                    rows.append((name, value.tobytes()))
                else:
                    rows.append((name, json.dumps(value, ensure_ascii=False).encode("utf-8")))
            con.executemany("INSERT INTO parts VALUES (?, ?)", rows)
            con.commit()
        finally:
            con.close()
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_store(path: Path, cache_version: str, cache_key: str) -> dict[str, Any]:
    """Return the parts of a store, or raise StoreError if it cannot be used."""
    if not path.exists():
        raise StoreError("no store file")
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open store: {exc}") from exc
    try:
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        if meta.get("store_format") != str(STORE_FORMAT):
            raise StoreError("store format changed")
        if meta.get("cache_version") != cache_version or meta.get("cache_key") != cache_key:
            raise StoreError("store belongs to other inputs or another version")
        if meta.get("array_itemsize") != str(_ARRAY_ITEMSIZE):
            raise StoreError("array width differs on this platform")
        parts: dict[str, Any] = {}
        for name, data in con.execute("SELECT name, data FROM parts").fetchall():
            if name in _ARRAY_PARTS:
                arr = array(ARRAY_TYPECODE)
                arr.frombytes(data)
                parts[name] = arr
            else:
                parts[name] = json.loads(bytes(data).decode("utf-8"))
        parts["__meta__"] = meta
        return parts
    except (sqlite3.Error, ValueError, UnicodeDecodeError) as exc:
        raise StoreError(f"corrupt store: {exc}") from exc
    finally:
        con.close()

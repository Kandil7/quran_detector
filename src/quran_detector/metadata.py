"""Quran metadata for results: surah names, revelation place, juz, hizb, rub, page, manzil.

The metadata is loaded from a JSON file that `scripts/import_metadata.py` writes after
checking it against the Tanzil text. It is used only to describe where a match is.
It never takes part in matching, so detection results do not depend on it.

JSON layout (format 1):
  {
    "format": 1,
    "source": {"database": ..., "database_sha256": ..., "adapter": ..., "tanzil_simple_sha256": ...},
    "surahs": {"1": {"name_ar", "name_en", "name_simple", "ayah_count",
                     "revelation_type", "revelation_order", "bism_pre"}, ...},
    "ayahs": [[surah, ayah, juz, hizb, rub, page, manzil], ...]   # one row per ayah
  }
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tanzil import read_tanzil

FORMAT = 1


class MetadataError(ValueError):
    pass


@dataclass(frozen=True)
class AyahMeta:
    juz: int
    hizb: int
    rub: int
    page: int
    manzil: int


class QuranMetadata:
    def __init__(
        self,
        surahs: dict[int, dict[str, Any]],
        ayahs: dict[tuple[int, int], AyahMeta],
        source: dict[str, Any],
        file_sha256: str = "",
    ):
        self.surahs = surahs
        self.ayahs = ayahs
        self.source = source
        self.file_sha256 = file_sha256  # SHA-256 of the JSON file, recorded in every result

    @classmethod
    def load(cls, path: str | Path) -> QuranMetadata:
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if data.get("format") != FORMAT:
            raise MetadataError(f"unsupported metadata format: {data.get('format')!r}")
        surahs = {int(k): v for k, v in data["surahs"].items()}
        ayahs: dict[tuple[int, int], AyahMeta] = {}
        for s, a, juz, hizb, rub, page, manzil in data["ayahs"]:
            ayahs[(int(s), int(a))] = AyahMeta(int(juz), int(hizb), int(rub), int(page), int(manzil))
        if len(surahs) != 114 or len(ayahs) != 6236:
            raise MetadataError("metadata must cover 114 surahs and 6236 ayahs")
        return cls(surahs, ayahs, data.get("source", {}), hashlib.sha256(raw).hexdigest())

    def surah_name(self, surah: int) -> tuple[str, str]:
        s = self.surahs[surah]
        return s["name_ar"], s["name_en"]

    def location_meta(self, location: list[Any]) -> dict[str, Any]:
        """Description of one location (a list of per-ayah refs), for the match output."""
        first = location[0]
        name_ar, name_en = self.surah_name(first.surah)
        meta = [self.ayahs[(r.surah, r.ayah)] for r in location]
        return {
            "surah_name_ar": name_ar,
            "surah_name_en": name_en,
            "revelation_place": self.surahs[first.surah]["revelation_type"],
            "page_start": min(m.page for m in meta),
            "page_end": max(m.page for m in meta),
            "juz_start": min(m.juz for m in meta),
            "juz_end": max(m.juz for m in meta),
        }


# ---------------------------------------------------------------- import (adapter)

RANGES = {"juz": (1, 30), "hizb": (1, 60), "rub": (1, 240), "page": (1, 604), "manzil": (1, 7)}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_bayan(
    db_path: str | Path,
    tanzil_simple: str | Path,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Build metadata from a Bayan-schema SQLite database (`surahs`, `ayahs` tables).

    The database is opened read-only, and its text columns are never read. Every
    check must pass; otherwise MetadataError is raised and nothing is returned.
    """
    db_path = Path(db_path)
    rows = read_tanzil(tanzil_simple)
    tanzil_pairs = [(s, a) for s, a, _ in rows]
    tanzil_counts: dict[int, int] = {}
    for s, a in tanzil_pairs:
        tanzil_counts[s] = max(tanzil_counts.get(s, 0), a)
    if require_complete and (len(tanzil_counts) != 114 or len(tanzil_pairs) != 6236):
        raise MetadataError("the Tanzil file is not the complete Quran (114 surahs, 6236 ayahs)")

    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise MetadataError(f"cannot open database read-only: {exc}") from exc
    try:
        surah_rows = con.execute(
            "SELECT id, name_ar, name_en, name_simple, ayah_count, revelation_type, "
            "revelation_order, bism_pre FROM surahs ORDER BY id"
        ).fetchall()
        ayah_rows = con.execute(
            "SELECT surah_id, ayah_number, juz, hizb, rub, page, manzil FROM ayahs "
            "ORDER BY surah_id, ayah_number"
        ).fetchall()
    except sqlite3.Error as exc:
        raise MetadataError(f"database schema is not the Bayan layout: {exc}") from exc
    finally:
        con.close()

    if require_complete and len(surah_rows) != 114:
        raise MetadataError(f"expected 114 surahs, found {len(surah_rows)}")
    surahs: dict[str, Any] = {}
    for sid, name_ar, name_en, name_simple, count, rtype, rorder, bism in surah_rows:
        if sid in surahs:
            raise MetadataError(f"surah {sid} appears twice")
        if count != tanzil_counts.get(sid):
            raise MetadataError(
                f"surah {sid}: ayah_count {count} differs from Tanzil {tanzil_counts.get(sid)}"
            )
        surahs[str(sid)] = {
            "name_ar": name_ar,
            "name_en": name_en,
            "name_simple": name_simple,
            "ayah_count": count,
            "revelation_type": rtype,
            "revelation_order": rorder,
            "bism_pre": bool(bism),
        }

    db_pairs = [(s, a) for s, a, *_ in ayah_rows]
    if db_pairs != tanzil_pairs:
        missing = set(tanzil_pairs) - set(db_pairs)
        extra = set(db_pairs) - set(tanzil_pairs)
        raise MetadataError(
            f"ayah list differs from Tanzil: {len(missing)} missing, {len(extra)} extra, "
            f"or in a different order"
        )

    names = ["juz", "hizb", "rub", "page", "manzil"]
    for col, name in enumerate(names, start=2):
        values = [r[col] for r in ayah_rows]
        if any(v is None for v in values):
            raise MetadataError(f"{name} has empty values")
        lo, hi = RANGES[name]
        if min(values) < lo or max(values) > hi:
            raise MetadataError(f"{name} out of range {lo}..{hi}: {min(values)}..{max(values)}")
        if any(b < a for a, b in zip(values, values[1:], strict=False)):
            raise MetadataError(f"{name} is not non-decreasing in ayah order")

    return {
        "format": FORMAT,
        "source": {
            "database": db_path.name,
            "database_sha256": sha256_file(db_path),
            "adapter": "bayan-v1",
            "tanzil_simple_sha256": sha256_file(tanzil_simple),
        },
        "surahs": surahs,
        "ayahs": [[s, a, juz, hizb, rub, page, manzil] for s, a, juz, hizb, rub, page, manzil in ayah_rows],
    }


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

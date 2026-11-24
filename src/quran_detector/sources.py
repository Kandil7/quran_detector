"""Provenance and cross-checking of the Quran data files (used by scripts/verify_sources.py).

Three checks, from strongest to weakest:
  1. Integrity: the Tanzil files still have the hashes recorded in data/SOURCES.json.
  2. Structure: the Tanzil ayah list and per-surah counts match the metadata file.
  3. Text: the Tanzil text agrees with a second database after folding both to the
     same form. Folding maps the dagger alef to a real alef, so Uthmani and imlaei
     spellings of the same word compare equal. Disagreements are reported, not hidden.

The second database is read-only and is used only here, never for matching.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metadata import QuranMetadata, sha256_file
from .normalizer import Level, normalize

MANIFEST_FORMAT = 1
DAGGER_ALEF = "ٰ"


class SourceCheckError(Exception):
    pass


def fold(text: str) -> str:
    """Comparison form: dagger alef read as alef, then AGGRESSIVE normalization."""
    return normalize(text.replace(DAGGER_ALEF, "ا"), Level.AGGRESSIVE)


def file_entry(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def read_manifest(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != MANIFEST_FORMAT:
        raise SourceCheckError(f"unsupported manifest format: {data.get('format')!r}")
    return data


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": MANIFEST_FORMAT, "created": _dt.date.today().isoformat(), **data}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_hashes(manifest: dict[str, Any], folder: Path) -> list[str]:
    """Problems found when the files on disk differ from the manifest."""
    problems = []
    for name, expected in manifest.get("files", {}).items():
        path = folder / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        actual = sha256_file(path)
        if actual != expected["sha256"]:
            problems.append(
                f"{name}: sha256 changed (manifest {expected['sha256'][:12]}, file {actual[:12]})"
            )
    return problems


def check_structure(meta: QuranMetadata, tanzil_pairs: list[tuple[int, int]]) -> list[str]:
    """Problems between the metadata and the Tanzil ayah list."""
    problems = []
    meta_pairs = sorted(meta.ayahs)
    if meta_pairs != sorted(tanzil_pairs):
        problems.append("metadata ayah list differs from the Tanzil text")
    counts: dict[int, int] = {}
    for s, a in tanzil_pairs:
        counts[s] = max(counts.get(s, 0), a)
    for s, n in counts.items():
        if meta.surahs.get(s, {}).get("ayah_count") != n:
            problems.append(f"surah {s}: metadata ayah_count differs from Tanzil ({n})")
    return problems


@dataclass
class CrossCheck:
    total: int = 0
    agree: int = 0
    differ: list[tuple[int, int, str, str]] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.agree / self.total if self.total else 0.0


def crosscheck_texts(tanzil: dict[tuple[int, int], str], other: dict[tuple[int, int], str]) -> CrossCheck:
    """Compare the Tanzil text with the other database's text, ayah by ayah, after folding."""
    out = CrossCheck()
    for key in sorted(tanzil):
        if key not in other:
            out.total += 1
            out.differ.append((key[0], key[1], tanzil[key], "<missing>"))
            continue
        out.total += 1
        if fold(tanzil[key]) == fold(other[key]):
            out.agree += 1
        else:
            out.differ.append((key[0], key[1], tanzil[key], other[key]))
    return out


def read_db_texts(db_path: Path, column: str) -> dict[tuple[int, int], str]:
    """Texts of one column from a Bayan-schema database (read-only)."""
    if column not in ("text_simple", "text_uthmani"):
        raise SourceCheckError(f"unknown column {column}")
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            f"SELECT surah_id, ayah_number, {column} FROM ayahs"  # column is checked above
        ).fetchall()
    finally:
        con.close()
    return {(int(s), int(a)): t for s, a, t in rows}

"""Reader for the Tanzil text files (the source of truth for the Quran text).

Format: one `surah|ayah|text` line per ayah (Tanzil "Text (with aya numbers)").
Lines that are blank or start with `#` are ignored. The file is read verbatim and is
never modified.

Rows must be strictly increasing by (surah, ayah). The word stream inserts a surah
break whenever the surah number changes, so an unsorted or duplicated file would give a
wrong stream. Both are rejected here.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "QURAN_DETECTOR_DATA"
REPO_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def default_data_dir() -> Path:
    """Folder that holds the Tanzil files: $QURAN_DETECTOR_DATA, else the repo's data/."""
    env = os.environ.get(ENV_DATA_DIR)
    return Path(env) if env else REPO_DATA_DIR


def read_tanzil(path: str | Path) -> list[tuple[int, int, str]]:
    """Read a Tanzil file into (surah, ayah, text) rows, validating order and uniqueness."""
    path = Path(path)
    rows: list[tuple[int, int, str]] = []
    last: tuple[int, int] | None = None
    with open(path, encoding="utf-8-sig") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n\r")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                raise ValueError(f"{path}:{lineno}: unexpected line format: {line[:60]!r}")
            key = (int(parts[0]), int(parts[1]))
            if last is not None and key <= last:
                raise ValueError(
                    f"{path}:{lineno}: ayah {key} is not after {last}; "
                    "rows must be strictly increasing and unique"
                )
            last = key
            rows.append((key[0], key[1], parts[2]))
    return rows

"""Build data/quran_meta.json from a Bayan-schema SQLite database, after checking it
against the Tanzil text. Nothing is written unless every check passes.

  python scripts/import_metadata.py --from "<path to quran.db>" \
      [--simple data/quran-simple.txt] [--out data/quran_meta.json]

The database is opened read-only. Its text columns are not read. Metadata is never used
for matching.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector.metadata import MetadataError, import_bayan, write_json_atomic  # noqa: E402
from quran_detector.tanzil import default_data_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", required=True, type=Path, help="Bayan-schema SQLite database")
    ap.add_argument("--simple", type=Path, default=default_data_dir() / "quran-simple.txt")
    ap.add_argument("--out", type=Path, default=default_data_dir() / "quran_meta.json")
    args = ap.parse_args(argv)
    try:
        data = import_bayan(args.source, args.simple, require_complete=True)
    except MetadataError as exc:
        print(f"REFUSED, nothing written: {exc}", file=sys.stderr)
        return 1
    write_json_atomic(args.out, data)
    print(f"wrote {args.out}: {len(data['surahs'])} surahs, {len(data['ayahs'])} ayahs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

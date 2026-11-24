"""Verify the Quran data files: integrity, structure, and a text cross-check.

  python scripts/verify_sources.py --init                 # record hashes and the cross-check baseline
  python scripts/verify_sources.py                        # check against data/SOURCES.json
  python scripts/verify_sources.py --cross-db "<quran.db>"   # also compare the text with a second database

Exit code 0 when every check passes, 1 otherwise. Integrity and structure failures are
always fatal. The text cross-check fails only when agreement drops below the baseline
recorded with --init, so a known, reviewed set of disagreements does not block the run.
The full list of disagreeing ayahs is written to evaluation/reports/source_crosscheck.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector.metadata import QuranMetadata  # noqa: E402
from quran_detector.sources import (  # noqa: E402
    SourceCheckError,
    check_hashes,
    check_structure,
    crosscheck_texts,
    file_entry,
    read_db_texts,
    read_manifest,
    write_manifest,
)
from quran_detector.tanzil import default_data_dir, read_tanzil  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="write data/SOURCES.json from the current files")
    ap.add_argument("--data", type=Path, default=default_data_dir())
    ap.add_argument("--cross-db", type=Path, help="Bayan-schema database to cross-check the text with")
    ap.add_argument("--report", type=Path, default=ROOT / "evaluation" / "reports" / "source_crosscheck.md")
    args = ap.parse_args(argv)

    problems: list[str] = []
    simple_p = args.data / "quran-simple.txt"
    uthmani_p = args.data / "quran-uthmani.txt"
    meta_p = args.data / "quran_meta.json"
    manifest_p = args.data / "SOURCES.json"

    try:
        simple = read_tanzil(simple_p)
    except (OSError, ValueError) as exc:
        print(f"FAIL integrity: {exc}")
        return 1
    pairs = [(s, a) for s, a, _ in simple]
    if len({s for s, _ in pairs}) != 114 or len(pairs) != 6236:
        problems.append("Tanzil Simple is not the complete Quran (114 surahs, 6236 ayahs)")
    uthmani = read_tanzil(uthmani_p) if uthmani_p.exists() else None
    if uthmani is not None and [(s, a) for s, a, _ in uthmani] != pairs:
        problems.append("Tanzil Uthmani and Simple have different ayah lists")

    files = [p for p in (simple_p, uthmani_p, meta_p) if p.exists()]
    if args.init:
        manifest = {
            "files": {p.name: file_entry(p) for p in files},
            "tanzil_options": "Text (with aya numbers); pause marks, sajdah signs and tatweel included",
        }
        if args.cross_db:
            manifest["crosscheck"] = _run_crosscheck(
                args.cross_db, simple, uthmani, args.report, baseline=None
            )
        write_manifest(manifest_p, manifest)
        print(f"wrote {manifest_p} for {len(files)} files")
        return 1 if problems else 0

    try:
        manifest = read_manifest(manifest_p)
    except (OSError, ValueError, SourceCheckError) as exc:
        print(f"FAIL: cannot read {manifest_p} ({exc}); run with --init first")
        return 1
    problems += check_hashes(manifest, args.data)

    if meta_p.exists():
        try:
            meta = QuranMetadata.load(meta_p)
            problems += check_structure(meta, pairs)
        except Exception as exc:  # metadata problems are reported, not raised
            problems.append(f"metadata: {exc}")

    baseline = manifest.get("crosscheck")
    if args.cross_db:
        result = _run_crosscheck(args.cross_db, simple, uthmani, args.report, baseline=baseline)
        if baseline and result["simple_agree"] < baseline["simple_agree"]:
            problems.append(
                "text cross-check: Simple agreement fell from "
                f"{baseline['simple_agree']} to {result['simple_agree']}"
            )
        print(
            f"text cross-check: Simple {result['simple_agree']}/{result['total']}, "
            f"Uthmani {result['uthmani_agree']}/{result['total']} (report: {args.report})"
        )

    if problems:
        for p in problems:
            print("FAIL", p)
        return 1
    print("OK: integrity, structure" + (" and text cross-check" if args.cross_db else "") + " passed")
    return 0


def _run_crosscheck(db: Path, simple, uthmani, report: Path, baseline) -> dict:
    simple_map = {(s, a): t for s, a, t in simple}
    db_simple = read_db_texts(db, "text_simple")
    res_s = crosscheck_texts(simple_map, db_simple)
    out = {
        "database": db.name,
        "total": res_s.total,
        "simple_agree": res_s.agree,
    }
    lines = [
        f"# Source cross-check against {db.name}",
        "",
        f"Simple (folded): {res_s.agree}/{res_s.total} agree ({res_s.rate:.2%}).",
        "",
    ]
    if uthmani is not None:
        uth_map = {(s, a): t for s, a, t in uthmani}
        res_u = crosscheck_texts(uth_map, read_db_texts(db, "text_uthmani"))
        out["uthmani_agree"] = res_u.agree
        lines.append(f"Uthmani (folded): {res_u.agree}/{res_u.total} agree ({res_u.rate:.2%}).")
        lines.append("")
    else:
        out["uthmani_agree"] = 0
    lines.append("## Simple ayahs that differ after folding")
    lines.append("")
    for s, a, _, _ in res_s.differ[:500]:
        lines.append(f"- {s}:{a}")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.exit(main())

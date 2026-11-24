"""Run the detector (Simple text) over a folder of book .txt files.

  python scripts/scan_books.py --books "D:/AI/Datasets/Custom/extracted_books" \
      --out "$TEMP/scan.jsonl" [--limit 20] [--start 0] [--mode high_precision]

One JSON line per book: id, name, size, words, seconds, and counts per status.
Only summaries are written, never the quoted text. Resumable: books already in
--out are skipped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector import BALANCED, HIGH_PRECISION, Corpus, QuranDetector  # noqa: E402

HEADER = re.compile(r"^Book ID:\s*(\d+)\s*$", re.M)
NAME = re.compile(r"^Book Name:\s*(.+?)\s*$", re.M)
PAGE = re.compile(r"^\[Page \d+\]\s*$", re.M)


def book_text(raw: str) -> str:
    """Drop the metadata header lines and page markers; keep the text."""
    lines = [ln for ln in raw.splitlines() if not (HEADER.match(ln) or NAME.match(ln) or PAGE.match(ln))]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", required=True, type=Path)
    ap.add_argument("--simple", type=Path, default=ROOT / "data" / "quran-simple.txt")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--start", type=int, default=0, help="skip the first N book files (sorted)")
    ap.add_argument("--mode", choices=["high_precision", "balanced"], default="high_precision")
    args = ap.parse_args(argv)

    corpus = Corpus.from_tanzil(args.simple, cache_dir=ROOT / ".cache")
    cfg = HIGH_PRECISION if args.mode == "high_precision" else BALANCED
    det = QuranDetector(corpus, cfg)

    files = sorted(p for p in args.books.iterdir() if p.suffix == ".txt" and p.name[:1].isdigit())
    files = files[args.start :]
    if args.limit is not None:
        files = files[: args.limit]
    done: set[str] = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["file"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    n = 0
    with open(args.out, "a", encoding="utf-8") as out:
        for p in files:
            if p.name in done:
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
            m_id = HEADER.search(raw)
            m_name = NAME.search(raw)
            text = book_text(raw)
            t0 = time.perf_counter()
            res = det.detect(text)
            sec = time.perf_counter() - t0
            counts = Counter(m.status.value for m in res.matches)
            row = {
                "file": p.name,
                "book_id": int(m_id.group(1)) if m_id else None,
                "name": m_name.group(1) if m_name else None,
                "bytes": p.stat().st_size,
                "words": len(text.split()),
                "seconds": round(sec, 3),
                "statuses": dict(counts),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            print(f"{n:5d} {p.name[:60]:60s} {sec:7.2f}s {dict(counts)}", flush=True)
    print(f"done: {n} books in {time.perf_counter() - t_all:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

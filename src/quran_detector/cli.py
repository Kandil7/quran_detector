"""Command line interface.

  python -m quran_detector --simple data/quran-simple.txt [--uthmani data/quran-uthmani.txt] \
      detect input.txt [more.txt ...]        # or "-" for stdin
      [--format json|jsonl|text] [--min-status verified|ambiguous|altered|spliced|candidate]
  python -m quran_detector --simple ... verify "إن الله مع الصابرين"

Output
  json   one file: the DetectionResult object. Several files: a list of
         {"path", "result"} objects.
  jsonl  one line per match: {"path", "schema_version", "match"}.
  text   one line per match: path, start, end, status, matched text (tab separated).

--min-status keeps matches whose status is that one or a stronger one, in this
order: verified, ambiguous, altered, spliced, candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from .corpus import Corpus
from .detector import BALANCED, HIGH_PRECISION, QuranDetector
from .models import SCHEMA_VERSION, DetectionResult, QuranMatch, Status

STATUS_ORDER = [Status.VERIFIED, Status.AMBIGUOUS, Status.ALTERED, Status.SPLICED, Status.CANDIDATE]


def filter_min_status(result: DetectionResult, min_status: Status | None) -> DetectionResult:
    """Keep matches at `min_status` or stronger, remapping spliced_with indexes."""
    if min_status is None:
        return result
    allowed = set(STATUS_ORDER[: STATUS_ORDER.index(min_status) + 1])
    keep = [i for i, m in enumerate(result.matches) if m.status in allowed]
    remap = {old: new for new, old in enumerate(keep)}
    kept: list[QuranMatch] = []
    for i in keep:
        m = result.matches[i]
        kept.append(
            QuranMatch(
                **{
                    **{f: getattr(m, f) for f in m.__dataclass_fields__},
                    "spliced_with": [remap[j] for j in m.spliced_with if j in remap],
                }
            )
        )
    return DetectionResult(result.text, kept, result.source)


def _read_input(path: str) -> tuple[str, str]:
    if path == "-":
        return "<stdin>", sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return path, fh.read()


def _emit_detect(out: TextIO, fmt: str, results: list[tuple[str, DetectionResult]]) -> None:
    if fmt == "json":
        if len(results) == 1:
            payload: Any = results[0][1].to_dict()
        else:
            payload = [{"path": p, "result": r.to_dict()} for p, r in results]
        json.dump(payload, out, ensure_ascii=False, indent=2)
        out.write("\n")
    elif fmt == "jsonl":
        for p, r in results:
            for m in r.matches:
                line = {"path": p, "schema_version": SCHEMA_VERSION, "match": m.to_dict()}
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
    else:  # text
        for p, r in results:
            for m in r.matches:
                out.write(f"{p}\t{m.start_char}\t{m.end_char}\t{m.status.value}\t{m.text}\n")


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="quran_detector")
    ap.add_argument("--simple", required=True, help="Tanzil Simple text, surah|ayah|text format")
    ap.add_argument("--uthmani", help="Tanzil Uthmani text, same format (optional)")
    ap.add_argument("--mode", choices=["high_precision", "balanced"], default="high_precision")
    ap.add_argument("--allow-partial-corpus", action="store_true")
    ap.add_argument("--format", choices=["json", "jsonl", "text"], default="json")
    ap.add_argument(
        "--min-status",
        choices=[s.value for s in STATUS_ORDER],
        help="keep this status and stronger ones (see module docs)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("paths", nargs="+", help="text files, or - for stdin")
    v = sub.add_parser("verify")
    v.add_argument("quote")
    args = ap.parse_args(argv)

    corpus = Corpus.from_tanzil(args.simple, args.uthmani, require_complete=not args.allow_partial_corpus)
    det = QuranDetector(corpus, HIGH_PRECISION if args.mode == "high_precision" else BALANCED)
    min_status = Status(args.min_status) if args.min_status else None

    if args.cmd == "detect":
        results = []
        for path in args.paths:
            label, text = _read_input(path)
            results.append((label, filter_min_status(det.detect(text), min_status)))
        _emit_detect(out, args.format, results)
    else:
        m = det.verify(args.quote)
        if (
            m is not None
            and min_status is not None
            and m.status not in STATUS_ORDER[: STATUS_ORDER.index(min_status) + 1]
        ):
            m = None
        if args.format == "text":
            out.write("" if m is None else f"{m.status.value}\t{m.text}\n")
        else:
            json.dump(
                {"match": m.to_dict() if m else None, "source": corpus.source},
                out,
                ensure_ascii=False,
                indent=2,
            )
            out.write("\n")
    return 0

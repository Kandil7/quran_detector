"""Run the detector on a gold file and report metrics.

  python evaluation/run_eval.py --simple data/quran-simple.txt --data evaluation/data/synth_dev.jsonl
  python evaluation/run_eval.py --simple ... --data ... --compare evaluation/reports/OLD.json

Writes evaluation/reports/<timestamp>.json and <timestamp>.md (unless --out-dir is given)
and prints the markdown table. With --compare, prints the change of every numeric
metric against an earlier JSON report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make the repo and src importable
    _root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_root))
    sys.path.insert(0, str(_root / "src"))

from evaluation.gold import load_gold  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    Doc,
    Span,
    ambiguity_coverage,
    char_macro_f1,
    document_false_positives,
    latency_ms,
    reference_accuracy,
    span_prf,
    status_prf,
    verified_precision,
)
from quran_detector import BALANCED, HIGH_PRECISION, Corpus, QuranDetector  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent / "reports"


def predict(det: QuranDetector, docs: list[Doc]) -> tuple[dict[str, list[Span]], list[float]]:
    preds: dict[str, list[Span]] = {}
    times: list[float] = []
    for d in docs:
        t0 = time.perf_counter()
        res = det.detect(d.text)
        times.append((time.perf_counter() - t0) * 1000.0)
        preds[d.id] = [
            Span(
                doc_id=d.id,
                start=m.start_char,
                end=m.end_char,
                status=m.status.value,
                locations=tuple(
                    tuple((r.surah, r.ayah, r.word_start, r.word_end) for r in loc) for loc in m.locations
                ),
            )
            for m in res.matches
        ]
    return preds, times


def evaluate(docs: list[Doc], preds: dict[str, list[Span]], times: list[float]) -> dict:
    gold = [s for d in docs for s in d.spans]
    # candidates are not quotes: they do not count as positive predictions
    pos = {k: [p for p in v if p.status != "candidate"] for k, v in preds.items()}
    pred = [p for v in pos.values() for p in v]
    per_doc_fp = document_false_positives(docs, pos)
    return {
        "documents": len(docs),
        "span_exact": span_prf(gold, pred, exact=True),
        "span_iou05": span_prf(gold, pred, exact=False),
        "char": char_macro_f1(docs, pos),
        "reference_accuracy": reference_accuracy(gold, pred),
        "ambiguity": ambiguity_coverage(gold, pred),
        "altered": status_prf(gold, pred, "altered"),
        "spliced": status_prf(gold, pred, "spliced"),
        "verified_precision": verified_precision(gold, pred),
        "negatives": per_doc_fp,
        "latency_ms": latency_ms(times),
    }


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def to_markdown(report: dict) -> str:
    rows = ["| metric | value |", "|---|---|"]

    def walk(prefix: str, obj) -> None:
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(key, v)
            else:
                rows.append(f"| {key} | {_fmt(v)} |")

    walk("", report["metrics"])
    head = f"# Evaluation {report['timestamp']}\n\ndata: `{report['data']}`, mode: {report['mode']}\n\n"
    return head + "\n".join(rows) + "\n"


def flatten(obj, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def compare_table(old: dict, new: dict) -> str:
    a, b = flatten(old["metrics"]), flatten(new["metrics"])
    rows = ["| metric | old | new | delta |", "|---|---|---|---|"]
    for k in sorted(set(a) | set(b)):
        if k in a and k in b:
            rows.append(f"| {k} | {a[k]:.4f} | {b[k]:.4f} | {b[k] - a[k]:+.4f} |")
        else:
            rows.append(f"| {k} | {a.get(k, 'n/a')} | {b.get(k, 'n/a')} | n/a |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simple", required=True, help="Tanzil Simple text")
    ap.add_argument("--uthmani", help="Tanzil Uthmani text (optional)")
    ap.add_argument("--data", required=True, help="gold .jsonl file")
    ap.add_argument("--mode", choices=["high_precision", "balanced"], default="high_precision")
    ap.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    ap.add_argument("--compare", type=Path, help="earlier report .json to compare with")
    ap.add_argument("--allow-partial-corpus", action="store_true")
    args = ap.parse_args(argv)

    docs = load_gold(args.data)
    corpus = Corpus.from_tanzil(args.simple, args.uthmani, require_complete=not args.allow_partial_corpus)
    det = QuranDetector(corpus, HIGH_PRECISION if args.mode == "high_precision" else BALANCED)
    preds, times = predict(det, docs)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "timestamp": stamp,
        "data": str(args.data),
        "mode": args.mode,
        "corpus": corpus.source,
        "metrics": evaluate(docs, preds, times),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    (args.out_dir / f"{stamp}.json").write_text(payload, encoding="utf-8")
    md = to_markdown(report)
    (args.out_dir / f"{stamp}.md").write_text(md, encoding="utf-8")
    print(md)
    if args.compare:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        print(compare_table(old, report))
    return 0


if __name__ == "__main__":
    sys.exit(main())

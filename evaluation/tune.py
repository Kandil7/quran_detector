"""Grid search on the dev set for Config thresholds (task 05). Never reads the test set.

  python evaluation/tune.py --simple data/quran-simple.txt --data evaluation/data/synth_dev.jsonl \
      --out evaluation/reports/tune_dev.jsonl

Writes one JSON line per configuration and prints the Pareto frontier over
(span recall, verified precision). Selection is done by `choose()`, below.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.gold import load_gold  # noqa: E402
from evaluation.run_eval import evaluate, predict  # noqa: E402
from quran_detector import HIGH_PRECISION, Corpus, QuranDetector  # noqa: E402
from quran_detector.tanzil import default_data_dir  # noqa: E402

GRID = {
    "min_words": [4, 5, 6],
    "min_words_with_context": [3, 4],
    "min_altered_matched": [4, 5, 6],
    "min_altered_ratio": [0.5, 0.6, 0.7],
    "max_gap": [2, 3, 4],
    "orth_variants": [False, True],
    "strict_context": [False, True],
}


def configs():
    names = list(GRID)
    for values in itertools.product(*(GRID[n] for n in names)):
        yield dict(zip(names, values, strict=True))


def pareto(rows: list[dict]) -> list[dict]:
    """Rows not dominated on (span recall up, verified precision up)."""
    front = []
    for r in rows:
        dominated = any(
            o is not r
            and o["span_recall"] >= r["span_recall"]
            and o["verified_precision"] >= r["verified_precision"]
            and (o["span_recall"] > r["span_recall"] or o["verified_precision"] > r["verified_precision"])
            for o in rows
        )
        if not dominated:
            front.append(r)
    return sorted(front, key=lambda r: -r["span_recall"])


def choose(rows: list[dict], baseline: dict, min_precision: float = 0.99) -> dict | None:
    """Highest span recall with verified precision >= min_precision and no more
    false-positive negative documents than the baseline. Ties: higher precision."""
    ok = [
        r
        for r in rows
        if r["verified_precision"] is not None
        and r["verified_precision"] >= min_precision
        and r["neg_fp"] <= baseline["neg_fp"]
    ]
    if not ok:
        return None
    return max(ok, key=lambda r: (r["span_recall"], r["verified_precision"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simple", type=Path, default=default_data_dir() / "quran-simple.txt")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if "test" in args.data.name:
        print("refusing to tune on a test file", file=sys.stderr)
        return 2

    docs = load_gold(args.data)
    corpus = Corpus.from_tanzil(args.simple, cache_dir=ROOT / ".cache")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    def run(cfg_values: dict) -> dict:
        cfg = replace(HIGH_PRECISION, **cfg_values)
        preds, times = predict(QuranDetector(corpus, cfg), docs)
        m = evaluate(docs, preds, times)
        return {
            "config": cfg_values,
            "span_recall": m["span_iou05"]["recall"],
            "span_precision": m["span_iou05"]["precision"],
            "span_f1": m["span_iou05"]["f1"],
            "verified_precision": m["verified_precision"]["precision"],
            "verified_errors": m["verified_precision"]["errors"],
            "verified_n": m["verified_precision"]["n_verified"],
            "neg_fp": m["negatives"]["false_positive_docs"],
            "altered_recall": m["altered"]["recall"],
        }

    baseline = run({})
    rows = [baseline]
    t0 = time.perf_counter()
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"baseline": True, **baseline}, ensure_ascii=False) + "\n")
        for k, cfg_values in enumerate(configs(), 1):
            r = run(cfg_values)
            rows.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            if k % 20 == 0:
                print(f"{k} configs, {time.perf_counter() - t0:.0f}s", flush=True)

    grid_rows = rows[1:]
    print("baseline:", json.dumps({k: baseline[k] for k in ("span_recall", "verified_precision", "neg_fp")}))
    print("Pareto frontier (span recall, verified precision):")
    for r in pareto(grid_rows):
        print(
            f"  recall={r['span_recall']:.4f} precision={r['verified_precision']:.4f} "
            f"neg_fp={r['neg_fp']} {r['config']}"
        )
    best = choose(grid_rows, baseline)
    print(
        "chosen (max recall with precision >= 0.99, no extra negative FP):",
        json.dumps(best, ensure_ascii=False) if best else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

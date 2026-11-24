"""Check the Uthmani → Simple word alignment over all ayahs (task 02, step 2).

  python scripts/check_uthmani_alignment.py [simple] [uthmani]

Prints:
  * key collisions: for each key scheme (dagger removed / dagger as alef), how many
    aligned Uthmani words have a key that equals a *different* Simple word in the
    Quran vocabulary (so a naive lookup would pick the wrong word),
  * block statistics (exact, 1:2, 2:1, approximate),
  * suspicious ayahs: any block with cost > 0.25, or an ayah that could not be aligned.
Writes the full list of suspicious ayahs to evaluation/reports/uthmani_alignment.txt
for review.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector.normalizer import Level, normalize  # noqa: E402
from quran_detector.tanzil import default_data_dir, read_tanzil  # noqa: E402
from quran_detector.tokenizer import WORD, tokenize  # noqa: E402
from quran_detector.uthmani import align_ayah, uthmani_keys  # noqa: E402


def read_rows(path: Path) -> dict[tuple[int, int], str]:
    return {(s, a): t for s, a, t in read_tanzil(path)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    simple_p = Path(argv[0]) if argv else default_data_dir() / "quran-simple.txt"
    uth_p = Path(argv[1]) if len(argv) > 1 else default_data_dir() / "quran-uthmani.txt"
    for p in (simple_p, uth_p):
        if not p.exists():
            print(f"STOP: {p} not found. Download the Tanzil texts first.", file=sys.stderr)
            return 2

    simple = read_rows(simple_p)
    uthm = read_rows(uth_p)
    vocab = set()
    for text in simple.values():
        for t in tokenize(text):
            if t.kind == WORD:
                vocab.add(t.strict)

    stats: Counter[str] = Counter()
    coll: Counter[str] = Counter()
    suspicious: list[str] = []
    for key in sorted(simple):
        s_toks = [t for t in tokenize(simple[key]) if t.kind == WORD]
        s_words = [t.strict for t in s_toks]
        u_words = [w for w in uthm[key].split() if any(ch.isalpha() for ch in normalize(w, Level.LIGHT))]
        blocks = align_ayah(u_words, s_words)
        flagged = False
        for b in blocks:
            if b.s1 == b.s0 or b.u1 == b.u0:
                stats["unaligned"] += 1
                flagged = True
                continue
            size = (b.u1 - b.u0, b.s1 - b.s0)
            stats[f"{size[0]}:{size[1]}"] += 1
            if b.exact:
                stats["exact"] += 1
            if b.cost > 0.25:
                flagged = True
                stats["suspicious"] += 1
            if size == (1, 1) and b.exact is False:
                stats["approx_1_1"] += 1
            if size == (1, 1):
                target = s_words[b.s0]
                k1, k2, _ = uthmani_keys(u_words[b.u0])
                stats["words_1_1"] += 1
                for name, k in (("dagger_removed", k1), ("dagger_as_alef", k2)):
                    if k != target and k in vocab:
                        coll[name] += 1
        if flagged:
            suspicious.append(
                f"{key[0]}:{key[1]}  uthmani={len(u_words)} simple={len(s_words)}  "
                f"blocks={[(b.u1 - b.u0, b.s1 - b.s0, round(b.cost, 2)) for b in blocks]}"
            )

    print(f"ayahs checked: {len(simple)}")
    print("block statistics:", dict(sorted(stats.items())))
    print(f"aligned 1:1 Uthmani words: {stats['words_1_1']}")
    print("key collisions (key equals a different Quran word in the vocabulary):")
    for name in ("dagger_removed", "dagger_as_alef"):
        n = coll[name]
        pct = 100.0 * n / max(stats["words_1_1"], 1)
        print(f"  {name}: {n} ({pct:.2f}% of aligned 1:1 words)")
    print(f"suspicious ayahs (a block with cost > 0.25, or unaligned): {len(suspicious)}")
    report = ROOT / "evaluation" / "reports" / "uthmani_alignment.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(suspicious) + "\n", encoding="utf-8")
    print(f"full list written to {report}")
    for line in suspicious[:15]:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

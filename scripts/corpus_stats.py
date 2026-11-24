"""Corpus statistics for choosing Config.frequent_bigram.

  python scripts/corpus_stats.py [data/quran-simple.txt]

Prints total words, vocabulary size (STRICT forms), the 30 most frequent bigrams
and how many bigrams exceed Config.frequent_bigram (the seed switches to
trigrams above that count). Also prints the bigram-count distribution so the
threshold can be checked against the data.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector import Config, Corpus  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else ROOT / "data" / "quran-simple.txt"
    if not path.exists():
        print(
            f"STOP: {path} not found. Download the Tanzil Simple text from https://tanzil.net/download/",
            file=sys.stderr,
        )
        return 2

    corpus = Corpus.from_tanzil(path)
    threshold = Config().frequent_bigram
    inv = {wid: w for w, wid in corpus.vocab.items()}

    total_words = sum(1 for wid in corpus.stream if wid >= 0)
    counts = sorted(((len(v), k) for k, v in corpus.bigrams.items()), reverse=True)
    above = sum(1 for c, _ in counts if c > threshold)

    print(f"ayahs: {len(corpus)}  surahs: {len(corpus.surah_ayah_count)}")
    print(f"total words: {total_words}")
    print(f"vocabulary size (STRICT forms): {len(corpus.vocab)}")
    print(f"distinct bigrams: {len(counts)}")
    print(f"bigrams above frequent_bigram={threshold}: {above}")
    print()
    print("top 30 bigrams:")
    for c, (a, b) in counts[:30]:
        print(f"  {c:6d}  {inv[a]} {inv[b]}")
    print()
    for q in (0.5, 0.9, 0.99, 0.999):
        idx = min(len(counts) - 1, int(q * len(counts)))
        print(f"  bigram count at quantile {q}: {counts[idx][0]}")
    print()
    if above / max(1, len(counts)) > 0.001:
        print(
            f"note: more than 0.1% of bigrams exceed {threshold}; review the threshold with the eval harness"
        )
    else:
        print(f"threshold {threshold} affects {above} bigrams; no change proposed from this data")
    return 0


if __name__ == "__main__":
    sys.exit(main())

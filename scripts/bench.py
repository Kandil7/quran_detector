"""Benchmark: corpus build time and detect latency.

  python scripts/bench.py [data/quran-simple.txt] [--runs 50]

* Corpus build: median of 3 builds.
* Detect: a ~1000-word mixed text made of ordinary Arabic filler sentences plus
  10 quotes sampled from the corpus with a fixed seed (random.Random(1)).
  Latency p50/p95 over --runs detect calls.

The filler is ordinary words used for timing only; it is not used to judge accuracy.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from quran_detector import Corpus, QuranDetector  # noqa: E402

SEED = 1
QUOTES = 10
TARGET_WORDS = 1000
FILLER_SENTENCES = [
    "ذهب الطالب إلى المدرسة صباحا مع أصدقائه",
    "تحدث المدير عن خطة العمل للعام القادم",
    "اشترت الأم الخبز والحليب من السوق القريب",
    "يعمل المهندس على تطوير البرنامج الجديد",
    "انتهت المباراة بفوز الفريق المحلي بهدف واحد",
    "قرأت الكتاب كله في يومين متتاليين",
    "تغيرت الأحوال الجوية بعد منتصف الليل",
    "افتتحت المكتبة قاعة جديدة للمطالعة",
]


def build_time(path: Path, runs: int = 3) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        Corpus.from_tanzil(path)
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def sample_quotes(corpus: Corpus, rng: random.Random) -> list[str]:
    """Quotes of 8-20 words taken from inside one surah (never across a surah break)."""
    quotes = []
    stream = corpus.stream
    while len(quotes) < QUOTES:
        n = rng.randint(8, 20)
        p = rng.randrange(0, len(stream) - n)
        window = range(p, p + n)
        if any(stream[q] < 0 for q in window):
            continue
        quotes.append(" ".join(corpus.raw_words[q] for q in window))
    return quotes


def mixed_text(corpus: Corpus, rng: random.Random) -> str:
    quotes = sample_quotes(corpus, rng)
    parts: list[str] = []
    words = 0
    qi = 0
    while words < TARGET_WORDS:
        if qi < len(quotes) and rng.random() < QUOTES / (TARGET_WORDS / 10):
            parts.append("قال تعالى: ﴿" + quotes[qi] + "﴾")
            words += len(quotes[qi].split())
            qi += 1
        else:
            s = rng.choice(FILLER_SENTENCES)
            parts.append(s)
            words += len(s.split())
    while qi < len(quotes):  # make sure all sampled quotes are present
        parts.append("قال تعالى: ﴿" + quotes[qi] + "﴾")
        qi += 1
    return " . ".join(parts)


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    k = max(1, min(len(s), round(q * len(s) + 0.5 - 1e-9)))
    return s[k - 1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=str(ROOT / "data" / "quran-simple.txt"))
    ap.add_argument("--runs", type=int, default=50)
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(
            f"STOP: {path} not found. Download the Tanzil Simple text from https://tanzil.net/download/",
            file=sys.stderr,
        )
        return 2

    b = build_time(path)
    print(f"corpus build (median of 3): {b:.3f} s")
    if b > 0.5:
        print("note: build time > 0.5 s; pass cache_dir=... to Corpus.from_tanzil to avoid rebuilding")
    import tempfile

    cache = Path(tempfile.mkdtemp(prefix="qd-bench-cache-"))
    t0 = time.perf_counter()
    Corpus.from_tanzil(path, cache_dir=cache)
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    Corpus.from_tanzil(path, cache_dir=cache)
    warm = time.perf_counter() - t0
    print(f"corpus with cache: cold {cold:.3f} s, warm {warm:.3f} s")

    corpus = Corpus.from_tanzil(path)
    text = mixed_text(corpus, random.Random(SEED))
    det = QuranDetector(corpus)
    words = len(text.split())
    det.detect(text)  # warm-up
    samples = []
    for _ in range(args.runs):
        t0 = time.perf_counter()
        det.detect(text)
        samples.append((time.perf_counter() - t0) * 1000.0)
    print(f"text: {words} words, {QUOTES} sampled quotes, seed {SEED}")
    print(f"detect over {args.runs} runs: p50 {pct(samples, 0.5):.1f} ms, p95 {pct(samples, 0.95):.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())

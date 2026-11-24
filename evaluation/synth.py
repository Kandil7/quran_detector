"""Seeded synthetic evaluation data (task 04).

  python evaluation/synth.py --simple data/quran-simple.txt \
      --books "D:/AI/Datasets/Custom/extracted_books" --split dev --n 400 --seed 1 \
      --out evaluation/data/synth_dev.jsonl

Quotes are sampled from the Tanzil Simple text, perturbed, and embedded in filler
passages from real books. Filler passages are accepted only when the detector finds
no Quran text in them even in BALANCED mode, so filler is a clean negative.

Books are split into dev and test by a hash of the file name, so the two sets share
no source book.

Gold labels follow from the perturbation (see `KINDS`). Every span carries `kind`,
so results can be broken down by perturbation.

Quotes of 3 words or fewer are gold `intended` only when the writer marks them with
a quotation context («قال تعالى» or ﴿﴾). Without context they are gold negatives,
which means a `verified` prediction for them counts as an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))

from quran_detector import BALANCED, Corpus, QuranDetector  # noqa: E402
from quran_detector.normalizer import Level, normalize  # noqa: E402

HEADER = re.compile(r"^(Book ID|Book Name):.*$", re.M)
PAGE = re.compile(r"^\[Page \d+\]\s*$", re.M)
DIAC = re.compile("[\u064b-\u065f\u0670\u06d6-\u06ed]")
CONTEXT_OPEN = "قال تعالى: ﴿"
CONTEXT_CLOSE = "﴾"
ORDINARY_WORD = "يعني"  # an ordinary word, used as an insertion

# kind -> (weight, gold status when the words are still a Quran span)
KINDS = {
    "exact": 0.30,
    "strip_marks": 0.15,
    "spelling": 0.10,
    "orth": 0.08,  # narrow orthographic variants (variants.py R1-R3): gold verified
    "detach": 0.05,
    "merge": 0.05,
    "ayah_num": 0.05,
    "substitute": 0.12,
    "delete": 0.09,
    "insert": 0.09,
    "splice": 0.10,  # handled per document, not per quote
}
EXACT_LIKE = {"exact", "strip_marks", "spelling", "orth", "detach", "merge", "ayah_num"}
ALTERED_LIKE = {"substitute", "delete", "insert"}


def split_of(name: str) -> str:
    return "dev" if int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % 2 == 0 else "test"


def book_lines(path: Path) -> list[str]:
    out = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if HEADER.match(ln) or PAGE.match(ln) or not ln.strip():
            continue
        out.append(ln.strip())
    return out


class Filler:
    """Clean filler passages from real books (no Quran text by the detector's standard)."""

    def __init__(self, books_dir: Path, split: str, rng: random.Random, clean: QuranDetector):
        files = sorted(
            p
            for p in books_dir.iterdir()
            if p.suffix == ".txt" and p.name[:1].isdigit() and split_of(p.name) == split
        )
        self.files = files
        self.rng = rng
        self.clean = clean
        self.lines: dict[Path, list[str]] = {}

    def window(self, min_words: int, max_words: int) -> str:
        for _ in range(500):
            p = self.rng.choice(self.files)
            if p not in self.lines:
                self.lines[p] = book_lines(p)
            lines = self.lines[p]
            if len(lines) < 5:
                continue
            i = self.rng.randrange(len(lines))
            target = self.rng.randint(min_words, max_words)
            words: list[str] = []
            j = i
            while j < len(lines) and len(words) < target:
                words += lines[j].split()
                j += 1
            if len(words) < min_words:
                continue
            text = " ".join(words)
            if self.clean.detect(text).matches:
                continue  # contains Quran text: not a clean negative
            return text
        raise RuntimeError("could not find clean filler passages")


def sample_start(corpus: Corpus, rng: random.Random, n: int) -> int | None:
    """A start position of n words inside one surah, with no sentinel in between."""
    s = corpus.stream
    for _ in range(2000):
        p = rng.randrange(0, len(s) - n)
        if all(s[q] >= 0 for q in range(p, p + n)):
            return p
    return None


def locations(corpus: Corpus, p: int, n: int) -> list[list[list[int]]]:
    """All locations of the word sequence (gold locations list every occurrence)."""
    seq = list(corpus.stream[p : p + n])
    starts = set(corpus.find_all(seq)) | {p} if n >= 2 else {p}
    out = []
    for s0 in sorted(starts):
        out.append([[int(x) for x in r] for r in corpus.refs(s0, s0 + n)])
    return out


def random_word(corpus: Corpus, rng: random.Random) -> str:
    p = rng.randrange(0, len(corpus.stream))
    while corpus.stream[p] < 0:
        p = rng.randrange(0, len(corpus.stream))
    return corpus.raw_words[p]


def perturb(
    corpus: Corpus, rng: random.Random, p: int, n: int, kind: str
) -> tuple[list[str], bool, tuple | None]:
    """Return (words, altered, cut). For an altered quote, `cut` = (type, index) of the
    change in the new word list; see `exact_halves` for the parts that stay exact."""
    words = list(corpus.raw_words[p : p + n])
    if kind in ("exact", "splice", "ayah_num"):
        return words, False, None
    if kind == "strip_marks":
        return [DIAC.sub("", w) for w in words], False, None
    if kind == "spelling":
        idx = [i for i, w in enumerate(words) if "ة" in w or "أ" in w or "إ" in w]
        if idx:
            i = rng.choice(idx)
            words[i] = words[i].replace("ة", "ه").replace("أ", "ا").replace("إ", "ا")
        return words, False, None
    if kind == "orth":
        cands = []
        for i, w in enumerate(words):
            st = normalize(w, Level.STRICT)
            if re.search("[ئؤء]ا", w):
                cands.append((i, "r1_drop"))  # «مائة» written «مئة»
            if st.endswith("ي"):
                cands.append((i, "r2"))  # final yeh written as alef
        if cands:
            i, rule = rng.choice(cands)
            if rule == "r1_drop":
                words[i] = re.sub("([ئؤء])ا", r"\1", words[i], count=1)
            else:
                k = max(j for j, ch in enumerate(words[i]) if ch in "يى")
                words[i] = words[i][:k] + "ا" + words[i][k + 1 :]
        return words, False, None
    if kind == "detach":
        idx = [i for i, w in enumerate(words) if DIAC.sub("", w)[:1] == "و" and len(DIAC.sub("", w)) > 3]
        if idx:
            i = rng.choice(idx)
            rest = re.sub("^[ً-ٰٟ]*و[ً-ٰٟ]*", "", words[i])
            words[i] = "و " + rest
        return words, False, None
    if kind == "merge":
        if n >= 2:
            i = rng.randrange(0, n - 1)
            words = words[:i] + [words[i] + words[i + 1]] + words[i + 2 :]
        return words, False, None
    if kind == "substitute":
        i = rng.randrange(n)
        old = normalize(words[i], Level.STRICT)
        for _ in range(100):  # the new word must differ in consonants, or the quote is still exact
            w = random_word(corpus, rng)
            if normalize(w, Level.STRICT) != old:
                break
        words[i] = w
        return words, True, ("substitute", i)
    if kind == "delete":
        # interior word only: deleting the first or last word leaves an exact run
        i = rng.randrange(1, n - 1)
        del words[i]
        return words, True, ("delete", i)
    if kind == "insert":
        k = rng.randrange(n + 1)
        words.insert(k, ORDINARY_WORD)
        return words, True, ("insert", k)
    raise ValueError(kind)


def pick_kind(rng: random.Random, n: int) -> str:
    names = [k for k in KINDS if k != "splice"]
    weights = [KINDS[k] for k in names]
    kind = rng.choices(names, weights)[0]
    if kind == "delete" and n < 6:
        return "exact"
    if kind == "substitute" and n < 4:
        return "exact"
    return kind


def exact_halves(cut: tuple, n_new: int, n_orig: int) -> list[tuple[int, int, int, int]]:
    """(new_a, new_b, orig_a, orig_b) for the two halves that are still exact Quran text.

    Delete at i: the words before i and after i are exact.
    Substitute at i: the words before and after i are exact.
    Insert at k: the original words before k and from k on are exact.
    """
    kind, i = cut
    if kind == "delete":
        return [(0, i, 0, i), (i, n_new, i + 1, n_orig)]
    if kind == "substitute":
        return [(0, i, 0, i), (i + 1, n_new, i + 1, n_orig)]
    if kind == "insert":
        return [(0, i, 0, i), (i + 1, n_new, i, n_orig)]
    raise ValueError(kind)


def make_quote(corpus: Corpus, rng: random.Random, forced: str | None = None) -> dict | None:
    n = rng.choices([2, 3, 4, 6, 9, 14, 22, 30], [6, 6, 10, 12, 12, 10, 8, 4])[0]
    p = sample_start(corpus, rng, n)
    if p is None:
        return None
    kind = forced or pick_kind(rng, n)
    if kind == "ayah_num":
        # only meaningful across an ayah boundary
        bounds = [q for q in range(p + 1, p + n) if corpus.pos_ayah[q] != corpus.pos_ayah[q - 1]]
        if not bounds:
            kind = "exact"
    words, altered, cut = perturb(corpus, rng, p, n, kind)
    if altered:
        # an altered quote must not be exact Quran text anywhere in the corpus
        ids = [corpus.word_id(normalize(w, Level.STRICT)) for w in words]
        if all(i >= 0 for i in ids) and corpus.find_all(ids):
            return None
    if kind == "ayah_num":
        q = [q for q in range(p + 1, p + n) if corpus.pos_ayah[q] != corpus.pos_ayah[q - 1]][0]
        words.insert(q - p, "(١)")
    text = " ".join(words)
    locs = locations(corpus, p, n)
    status = "altered" if altered else ("verified" if len(locs) == 1 else "ambiguous")

    # character offsets of each word in `text`
    offs: list[tuple[int, int]] = []
    pos = 0
    for w in words:
        offs.append((pos, pos + len(w)))
        pos += len(w) + 1

    subruns = []
    if cut is not None:
        for na, nb, oa, ob in exact_halves(cut, len(words), n):
            if nb - na >= 1 and nb - na == ob - oa:
                subruns.append(
                    {
                        "start": offs[na][0],
                        "end": offs[nb - 1][1],
                        "p": p + oa,
                        "n": nb - na,
                    }
                )
    return {"kind": kind, "text": text, "n": n, "status": status, "locations": locs, "subruns": subruns}


def build_doc(corpus, filler: Filler, rng: random.Random, doc_id: str, n_quotes: int, splice: bool) -> dict:
    """One document: filler passages around quotes. A splice puts two exact quotes
    next to each other with no words between them (gold status: spliced)."""
    if splice:
        a = make_quote(corpus, rng, forced="exact")
        b = make_quote(corpus, rng, forced="exact")
        if a is None or b is None or a["n"] < 4 or b["n"] < 4:
            splice = False
        else:
            pieces = [
                (filler.window(30, 120) + " ", None),
                (a["text"], a),
                (" ", None),
                (b["text"], b),
                (" " + filler.window(30, 120), None),
            ]
            for q in (a, b):
                q["status"] = "spliced"
    if not splice:
        if n_quotes == 0:
            return {"id": doc_id, "text": filler.window(60, 180), "source": "synthetic", "spans": []}
        pieces = []
        for _ in range(n_quotes):
            q = make_quote(corpus, rng)
            if q is None:
                continue
            pieces.append((filler.window(30, 120) + " ", None))
            q["ctx"] = rng.random() < 0.3
            if q["ctx"]:
                pieces.append((CONTEXT_OPEN, None))
            pieces.append((q["text"], q))
            if q["ctx"]:
                pieces.append((CONTEXT_CLOSE, None))
            pieces.append((" ", None))
        pieces.append((filler.window(30, 120), None))

    text = ""
    spans = []
    for piece, q in pieces:
        start = len(text)
        text += piece
        if q is not None:
            n = q["n"]
            ctx = bool(q.get("ctx", False))
            spans.append(
                {
                    "start": start,
                    "end": len(text),
                    "status": q["status"],
                    "locations": q["locations"],
                    # quotes of 3 words or fewer are intended only with a quotation context
                    "intended": bool(n >= 4 or ctx),
                    "kind": q["kind"],
                }
            )
            # the exact halves of an altered quote are quotes in their own right
            for sub in q.get("subruns", []):
                locs = locations(corpus, sub["p"], sub["n"])
                spans.append(
                    {
                        "start": start + sub["start"],
                        "end": start + sub["end"],
                        "status": "verified" if len(locs) == 1 else "ambiguous",
                        "locations": locs,
                        # context only: the detector reports one altered match per damaged quote
                        "intended": False,
                        "kind": "subrun",
                    }
                )
    return {"id": doc_id, "text": text, "source": "synthetic", "spans": spans}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simple", type=Path, default=ROOT / "data" / "quran-simple.txt")
    ap.add_argument("--books", type=Path, required=True)
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    if not args.simple.exists():
        print(f"STOP: {args.simple} not found", file=sys.stderr)
        return 2
    if not args.books.exists():
        print(f"STOP: books folder {args.books} not found", file=sys.stderr)
        return 2

    rng = random.Random(f"{args.seed}-{args.split}")
    corpus = Corpus.from_tanzil(args.simple, cache_dir=ROOT / ".cache")
    filler = Filler(args.books, args.split, rng, QuranDetector(corpus, BALANCED))
    args.out.parent.mkdir(parents=True, exist_ok=True)

    kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    with open(args.out, "w", encoding="utf-8") as fh:
        for i in range(args.n):
            r = rng.random()
            splice = r < 0.10
            n_quotes = rng.choices([0, 1, 2, 3], [25, 35, 25, 15])[0]
            doc = build_doc(corpus, filler, rng, f"{args.split}-{i:05d}", n_quotes, splice)
            for s in doc["spans"]:
                kinds[s["kind"]] += 1
                statuses[s["status"]] += 1
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"wrote {args.n} docs to {args.out}")
    print("spans by kind:", dict(kinds))
    print("spans by status:", dict(statuses))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""OCR mode (task 06): fuzzy word matching for noisy scanned text.

Enabled only with `Config(mode="ocr")`. In the default mode nothing here runs.

For each input word that has no exact match in the Quran vocabulary:
  1. a merged word that splits into two known words is split («ياايها» → «يا ايها»);
  2. otherwise the nearest Quran word is taken if it is within `ocr_max_edits`,
     where a substitution between two letters of the same dot-class costs 0.5 and
     any other edit costs 1. A tie between two different words is left alone.

Words changed this way are marked `ocr`, and a match that uses one is reported as
`needs_review`. It is never `verified`: OCR evidence is not a deterministic gate.

Candidates come from two indexes built on the Quran vocabulary:
  * the skeleton index: STRICT word -> words with the same dot-class skeleton
    (Level.SKELETON), which catches dot confusions;
  * a character 4-gram index over STRICT forms, which catches other errors. A
    word is a candidate when it shares enough 4-grams with the input.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .normalizer import Level, normalize
from .rules import split_unknown
from .tokenizer import WORD, Token

if TYPE_CHECKING:
    from .corpus import Corpus

MIN_WORD_LENGTH = 3  # shorter words are too ambiguous to correct
MAX_POOL = 60  # candidates from the 4-gram index, most shared grams first


class OcrIndex:
    def __init__(self, corpus: Corpus) -> None:
        self.skeleton: dict[str, list[int]] = {}
        self.grams: dict[str, list[int]] = {}
        self.cache: dict[tuple[str, float], int | None] = {}
        for strict, wid in corpus.vocab.items():
            self.skeleton.setdefault(normalize(strict, Level.SKELETON), []).append(wid)
            for g in _grams(strict):
                self.grams.setdefault(g, []).append(wid)


def _grams(word: str, n: int = 4) -> set[str]:
    padded = f"_{word}_"
    return {padded[i : i + n] for i in range(max(1, len(padded) - n + 1))}


def weighted_edit(a: str, b: str) -> float:
    """Edit distance where a substitution inside one dot-class costs 0.5."""
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                sub = 0.0
            elif normalize(ca, Level.SKELETON) == normalize(cb, Level.SKELETON):
                sub = 0.5
            else:
                sub = 1.0
            cur.append(min(prev[j] + 1.0, cur[j - 1] + 1.0, prev[j - 1] + sub))
        prev = cur
    return prev[-1]


def _index(corpus: Corpus) -> OcrIndex:
    idx = getattr(corpus, "_ocr_index", None)
    if idx is None:
        idx = OcrIndex(corpus)
        corpus._ocr_index = idx  # type: ignore[attr-defined]
    return idx


def best_candidate(strict: str, corpus: Corpus, max_edits: float) -> int | None:
    """Vocabulary id of the unique nearest Quran word within `max_edits`, or None.

    Results are cached per corpus: the same unknown word recurs many times in a text.
    """
    idx = _index(corpus)
    key = (strict, max_edits)
    if key not in idx.cache:
        idx.cache[key] = _best_candidate(strict, corpus, max_edits)
    return idx.cache[key]


def _best_candidate(strict: str, corpus: Corpus, max_edits: float) -> int | None:
    idx = _index(corpus)
    pool: set[int] = set(idx.skeleton.get(normalize(strict, Level.SKELETON), []))
    shared: Counter[int] = Counter()
    for g in _grams(strict):
        for wid in idx.grams.get(g, ()):
            shared[wid] += 1
    pool.update(wid for wid, _ in shared.most_common(MAX_POOL))
    best: tuple[float, int] | None = None
    tie = False
    for wid in pool:
        cost = weighted_edit(strict, corpus.vocab_strict[wid])
        if cost > max_edits:
            continue
        if best is None or cost < best[0]:
            best, tie = (cost, wid), False
        elif cost == best[0]:
            tie = True
    if best is None or tie:
        return None
    return best[1]


def resolve_ocr(tokens: list[Token], corpus: Corpus, max_edits: float) -> list[Token]:
    """Replace unknown OCR words by known ones (see module docstring)."""
    out: list[Token] = []
    for t in tokens:
        if t.kind != WORD or corpus.word_id(t.strict) >= 0 or len(t.strict) < MIN_WORD_LENGTH:
            out.append(t)
            continue
        split = split_unknown("", [t], corpus)
        if len(split) > 1:
            out.extend(_mark(p) for p in split)
            continue
        wid = best_candidate(t.strict, corpus, max_edits)
        if wid is None:
            out.append(t)
        else:
            fixed = corpus.vocab_strict[wid]
            out.append(_mark(Token(t.start, t.end, t.raw, fixed, normalize(fixed, Level.AGGRESSIVE), WORD)))
    return out


def _mark(t: Token) -> Token:
    return Token(t.start, t.end, t.raw, t.strict, t.aggressive, t.kind, t.uthmani, ocr=True)

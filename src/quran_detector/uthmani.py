"""Uthmani script support (task 02).

Uthmani text (Madina Mushaf) and the Imlaei/Simple text spell the same Quran
word differently. The differences that matter here, all found in the data:

  * U+0670 (dagger alef) is an alef that Imlaei either omits («الرَّحْمَٰنِ» →
    «الرحمن») or writes in full («ٱلْعَٰلَمِينَ» → «العالمين»).
  * U+06E5 / U+06E6 (small waw / small yeh) are not always letters. In pronoun
    suffixes they are dropped («بِهِۦ» → «به»); in «وَلِىِّۦ» → «وَلِيِّي» the small
    yeh is the letter ي. Both readings are kept as variants.
  * Hamza written on its own line («ءَامَنُوا») and ة written as و + dagger
    («ٱلصَّلَوٰةَ») are orthographic, not letters.

Each Uthmani word therefore has three STRICT keys (see `uthmani_keys`):
  k1: dagger removed, small marks dropped
  k2: dagger read as alef, small marks dropped
  k3: dagger removed, small marks read as letters (و / ي)

Alignment of Uthmani words to Simple words of the same ayah uses AGGRESSIVE forms
of the keys (which also fold hamza and ة), so most pairs align exactly. Blocks
of one or two words on each side are searched by dynamic programming, so
«يَٰٓأَيُّهَا» (one word) aligns to «يا أيها» (two words). Only blocks with a
cost up to ACCEPT_COST go into the lookup dictionary built by the corpus; the
others are reported for review.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from .normalizer import Level, normalize
from .tokenizer import WORD, Token

if TYPE_CHECKING:
    from .corpus import Corpus

# Marks that occur only in Uthmani spelling. A token containing one of them is
# resolved with the Uthmani keys even when its STRICT form is in the Quran vocabulary.
UTHMANI_ONLY = frozenset("ٰۡۥۦࣰࣱࣲ")
_SMALL = {"ۥ": "و", "ۦ": "ي"}  # small waw / small yeh

# Blocks with a cost above this are reported, not used for the dictionary.
ACCEPT_COST = 0.25
# 1:1 and 1:3 blocks with a cost up to this were reviewed by hand and accepted: 53
# blocks, all orthographic variants (hamza, ya/waw forms, the 1:3 block of 20:94).
REVIEWED_COST = 0.5
BAND = 2  # the alignment search is restricted to |i - j| <= BAND, with a full fallback


def _key(word: str, dagger_as_alef: bool, small_as_letter: bool) -> str:
    out = []
    for ch in unicodedata.normalize("NFC", word):
        if ch == "ٰ":
            if dagger_as_alef:
                out.append("ا")
            continue
        if ch in _SMALL:
            if small_as_letter:
                out.append(_SMALL[ch])
            continue
        out.append(ch)
    return normalize("".join(out), Level.STRICT)


def uthmani_keys(word: str) -> tuple[str, str, str]:
    """(k1, k2, k3) STRICT keys of an Uthmani word. See the module docstring."""
    return (
        _key(word, dagger_as_alef=False, small_as_letter=False),
        _key(word, dagger_as_alef=True, small_as_letter=False),
        _key(word, dagger_as_alef=False, small_as_letter=True),
    )


def has_uthmani_marks(raw: str) -> bool:
    return any(ch in UTHMANI_ONLY for ch in raw)


def _agg(s: str) -> str:
    return normalize(s, Level.AGGRESSIVE)


@cache
def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class Block:
    """Uthmani words [u0, u1) aligned to Simple words [s0, s1), with a cost in [0, 1]."""

    u0: int
    u1: int
    s0: int
    s1: int
    cost: float

    @property
    def exact(self) -> bool:
        return self.cost == 0.0


@cache
def _block_cost(s_agg: str, candidates: tuple[str, ...]) -> float:
    """Normalized edit distance from the Simple block to the closest Uthmani variant."""
    if s_agg in candidates:
        return 0.0
    best = min(levenshtein(c, s_agg) for c in candidates)
    return best / max(len(s_agg), 1)


def align_ayah(u_words: list[str], s_words: list[str]) -> list[Block]:
    """Align Uthmani words to Simple words of one ayah.

    `u_words` are raw Uthmani words (words with no letters must be removed by the
    caller), `s_words` are STRICT Simple words. Blocks are (1,1), (1,2), (2,1) or
    (1,3) words; the segmentation with the lowest total cost is returned, in order.
    """
    n, m = len(u_words), len(s_words)
    if n == 0 and m == 0:
        return []
    u_var = [tuple(_agg(k) for k in uthmani_keys(w)) for w in u_words]  # 3 variants per word
    s_agg = [_agg(s) for s in s_words]
    if n == m and all(_block_cost(s_agg[i], u_var[i]) == 0.0 for i in range(n)):
        # fast path: word-for-word exact alignment, no search needed
        return [Block(i, i + 1, i, i + 1, 0.0) for i in range(n)]
    band = BAND if abs(n - m) <= BAND else max(n, m)
    blocks = _dp(u_var, s_agg, n, m, band)
    if blocks is None:
        blocks = _dp(u_var, s_agg, n, m, max(n, m))
    return blocks if blocks is not None else [Block(0, n, 0, m, 1.0)]


def _dp(u_var: list[tuple[str, ...]], s_agg: list[str], n: int, m: int, band: int) -> list[Block] | None:
    INF = float("inf")
    # joined variants of every block of 1 or 2 Uthmani words, computed once
    u2 = [tuple(u_var[i][v] + u_var[i + 1][v] for v in range(3)) if i + 1 < n else () for i in range(n)]
    s2 = [s_agg[j] + s_agg[j + 1] if j + 1 < m else "" for j in range(m)]
    s3 = [s_agg[j] + s_agg[j + 1] + s_agg[j + 2] if j + 2 < m else "" for j in range(m)]
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int, float] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        for j in range(max(0, i - band), min(m, i + band) + 1):
            cur = best[i][j]
            if cur == INF:
                continue
            if i < n and j < m:  # (1, 1)
                c = _block_cost(s_agg[j], u_var[i])
                if cur + c < best[i + 1][j + 1]:
                    best[i + 1][j + 1] = cur + c
                    back[i + 1][j + 1] = (i, j, c)
            if i < n and j + 1 < m:  # (1, 2): one Uthmani word, two Simple words
                c = _block_cost(s2[j], u_var[i])
                if cur + c < best[i + 1][j + 2]:
                    best[i + 1][j + 2] = cur + c
                    back[i + 1][j + 2] = (i, j, c)
            if i + 1 < n and j < m:  # (2, 1): two Uthmani words, one Simple word
                c = _block_cost(s_agg[j], u2[i])
                if cur + c < best[i + 2][j + 1]:
                    best[i + 2][j + 1] = cur + c
                    back[i + 2][j + 1] = (i, j, c)
            if i < n and j + 2 < m:  # (1, 3): one Uthmani word, three Simple words
                c = _block_cost(s3[j], u_var[i])
                if cur + c < best[i + 1][j + 3]:
                    best[i + 1][j + 3] = cur + c
                    back[i + 1][j + 3] = (i, j, c)
    if best[n][m] == INF:
        return None
    out: list[Block] = []
    i, j = n, m
    while (i, j) != (0, 0):
        entry = back[i][j]
        assert entry is not None
        pi, pj, c = entry
        out.append(Block(pi, i, pj, j, c))
        i, j = pi, pj
    out.reverse()
    return out


def _as_simple(tok: Token, strict: str) -> Token:
    return Token(tok.start, tok.end, tok.raw, strict, normalize(strict, Level.AGGRESSIVE), WORD, uthmani=True)


def resolve_tokens(tokens: list[Token], corpus: Corpus) -> list[Token]:
    """Map Uthmani-spelled words to the Simple words they correspond to.

    A word is looked up when it contains a mark that only Uthmani uses, or when its
    STRICT form is not in the Quran vocabulary. The keys are tried in the order
    k2, k1, k3. A 1:2 entry turns one token into two tokens with the same offsets.
    Words that are not in the dictionary are returned unchanged.
    """
    out: list[Token] = []
    for t in tokens:
        if t.kind != WORD:
            out.append(t)
            continue
        if not has_uthmani_marks(t.raw) and corpus.word_id(t.strict) >= 0:
            out.append(t)
            continue
        k1, k2, k3 = uthmani_keys(t.raw)
        target = next((corpus.uthmani_map[k] for k in (k2, k1, k3) if k in corpus.uthmani_map), None)
        if target is None:
            out.append(t)
        elif len(target) > 1:
            out.extend(_as_simple(t, s) for s in target)
        elif target[0] != t.strict:
            out.append(_as_simple(t, target[0]))
        else:
            out.append(t)
    return out

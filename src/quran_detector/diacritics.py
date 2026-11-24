"""Diacritic (tashkeel) comparison between an input word and a reference word.

Only marks the writer actually wrote are compared. A letter the writer left
unmarked is never an error (partial diacritization is fine). A letter the writer
marked is an error when one of its marks is absent from the reference letter,
so a wrong vowel is caught, while a missing shadda or sukun is not.

Mark order is canonicalized by comparing sets of marks, so «بَّ» and «ببَ» with
the marks in either order compare equal. Uthmani encodings are mapped to their
standard equivalents before comparison (see `EQUIVALENTS`).

Letters are aligned by position. When the two words have a different number of
letters (for example because the Uthmani text writes a small waw that the Simple
text omits), the word is not comparable and is skipped.
"""

from __future__ import annotations

import unicodedata

from .normalizer import Level, normalize

# Harakat and shadda (U+064B..U+0652), the marks compared by this module.
HARAKAT: frozenset[str] = frozenset(chr(c) for c in range(0x064B, 0x0653))

# Uthmani encodings of standard marks. Keys are replaced by values before
# comparison. Uthmani open tanween (U+08F0..U+08F2) is the standard tanween
# with an open shape; Uthmani small high sukun (U+06E1) is the standard sukun.
EQUIVALENTS: dict[str, str] = {
    "ࣰ": "ً",  # open fathatan -> fathatan
    "ࣱ": "ٍ",  # open kasratan -> kasratan
    "ࣲ": "ٌ",  # open dammatan -> dammatan
    "ۡ": "ْ",  # small high dotless head of khah -> sukun
}


def _segments(word: str) -> list[tuple[str, frozenset[str]]]:
    """Split a word into (base letter, set of marks) pairs."""
    out: list[tuple[str, frozenset[str]]] = []
    for ch in unicodedata.normalize("NFC", word):
        ch = EQUIVALENTS.get(ch, ch)
        if ch in HARAKAT:
            if out:
                base, marks = out[-1]
                out[-1] = (base, marks | {ch})
            continue
        base = normalize(ch, Level.STRICT)
        if not base:  # tatweel, zero-width marks, Quranic annotations, dagger alef
            continue
        out.append((base, frozenset()))
    return out


def has_marks(word: str) -> bool:
    return any(EQUIVALENTS.get(ch, ch) in HARAKAT for ch in unicodedata.normalize("NFC", word))


def compare(got: str, expected: str) -> tuple[bool, list[int]]:
    """Compare the marks of `got` (input) with `expected` (reference).

    Returns (checked, error_letter_indexes). `checked` is False when the input
    has no marks or the words have different letter counts, in which case no
    decision is made.
    """
    if not has_marks(got):
        return False, []
    g, e = _segments(got), _segments(expected)
    if len(g) != len(e):
        return False, []
    errors = []
    for i, ((_, gm), (_, em)) in enumerate(zip(g, e, strict=True)):
        if gm and not gm <= em:
            errors.append(i)
    return True, errors

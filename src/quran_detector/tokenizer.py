"""Tokenizer that keeps original character offsets.

Arabic words become WORD tokens. Latin words become BARRIER tokens: they break
the adjacency of Arabic words so a match can never run across them. Digits,
punctuation, brackets and ayah-end glyphs are skipped entirely, so ayah numbers
inside a quote such as "قل هو الله أحد (1) الله الصمد (2)" do not split it.

Offsets are Python string indices (Unicode code points).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalizer import Level, normalize

# Arabic letters and combining marks. Excludes Arabic punctuation (، ؛ ؟ ٪ ٫ ٬ ٭ ۔),
# Arabic-Indic and Persian digits, ۝ (end of ayah), ۞ and ۩, and the ornate
# parentheses ﴾ ﴿ (U+FD3E/U+FD3F).
_AR = "ؐ-ؚؠ-ٟٮ-ۓە-ۜ۟-۪ۨ-ۯۺ-ۿݐ-ݿࢠ-ࣿﭐ-ﴽﵐ-﷿ﹰ-ﻼ‌‍"
_TOKEN_RE = re.compile(f"(?P<ar>[{_AR}]+)|(?P<lat>[A-Za-z]+)")

WORD = 0
BARRIER = 1


@dataclass(frozen=True, slots=True)
class Token:
    start: int
    end: int
    raw: str
    strict: str
    aggressive: str
    kind: int
    uthmani: bool = False  # True when this word was resolved from Uthmani spelling
    ocr: bool = False  # True when this word was corrected in OCR mode


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(text):
        if m.lastgroup == "lat":
            tokens.append(Token(m.start(), m.end(), m.group(), "", "", BARRIER))
            continue
        raw = m.group()
        strict = normalize(raw, Level.STRICT)
        if not strict:  # a standalone pause mark or similar
            continue
        tokens.append(Token(m.start(), m.end(), raw, strict, normalize(raw, Level.AGGRESSIVE), WORD))
    return tokens

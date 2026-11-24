"""Narrow orthographic variants of a STRICT word (optional, Config.orth_variants).

Three cases, each a single-letter difference that is a common spelling choice in
typed Arabic and not a different word:

  R1  a missing alef beside a hamza carrier: «مئة» for «مائة»
  R2  a final alef written for alef maqsura (ى is folded to ي by STRICT): «أقصا» for «أقصى»
  R3  one hamza-family letter for another: «يسئل» for «يسأل»

Deliberately not included: any change of a weak letter in the middle of a word
(«قول» vs «قال»), because that is a different verb form, not a spelling choice.
"""

from __future__ import annotations

HAMZA_CARRIERS = frozenset("ئؤء")
HAMZA_FAMILY = frozenset("اءئؤ")


def orth_variant(a: str, b: str) -> bool:
    """True if STRICT words `a` (input) and `b` (Quran) differ only by R1, R2 or R3."""
    if a == b:
        return True
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diffs) != 1:
            return False
        i = diffs[0]
        x, y = a[i], b[i]
        if x in HAMZA_FAMILY and y in HAMZA_FAMILY:  # R3
            return True
        if i == len(a) - 1 and {x, y} == {"ا", "ي"}:  # R2
            return True
        return False
    if abs(len(a) - len(b)) == 1:  # R1
        long, short = (a, b) if len(a) > len(b) else (b, a)
        for i, ch in enumerate(long):
            if ch == "ا" and long[:i] + long[i + 1 :] == short:
                neighbours = long[i - 1 : i] + long[i + 1 : i + 2]
                return any(c in HAMZA_CARRIERS for c in neighbours)
    return False

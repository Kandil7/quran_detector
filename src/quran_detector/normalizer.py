"""Arabic normalization for Quran matching.

Normalization is applied per token, so original character offsets are kept by
the tokenizer (each token remembers its start/end in the source text).

Levels (each includes the previous one):
  LIGHT      Unicode compatibility folding for presentation forms, removal of
             diacritics, Quranic annotation marks, superscript alef, tatweel and
             zero-width joiners.
  STRICT     + hamza-carrying alefs and alef wasla -> bare alef, alef maqsura
             and Persian yeh -> yeh, Persian kaf -> kaf.
             This is the level used for indexing and seeding.
  AGGRESSIVE + teh marbuta -> heh, waw/yeh hamza -> waw/yeh, standalone hamza
             removed. Used only to classify a differing word as an
             orthographic variant instead of an alteration.
  SKELETON   STRICT, then letters that differ only in dots are merged into one
             class (OCR confuses them). Used only for OCR candidate generation,
             never for deciding a status. See `_SKELETON_CLASSES`.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class Level(str, Enum):
    LIGHT = "light"
    STRICT = "strict"
    AGGRESSIVE = "aggressive"
    SKELETON = "skeleton"


# Dot-confusion classes for OCR. Each letter maps to the class representative.
# Dotless/dotted pairs such as ر/ز share a rasm; the table is applied to STRICT
# forms. Positional rule: ن and ي join the ب class only when they are not the
# last letter of the word (medial or initial); final ن and ي stay distinct.
_SKELETON_CLASSES: dict[str, str] = {
    "ب": "ب",
    "ت": "ب",
    "ث": "ب",  # ب ت ث
    "ج": "ج",
    "ح": "ج",
    "خ": "ج",  # ج ح خ
    "د": "د",
    "ذ": "د",  # د ذ
    "ر": "ر",
    "ز": "ر",  # ر ز
    "س": "س",
    "ش": "س",  # س ش
    "ص": "ص",
    "ض": "ص",  # ص ض
    "ط": "ط",
    "ظ": "ط",  # ط ظ
    "ع": "ع",
    "غ": "ع",  # ع غ
    "ف": "ف",
    "ق": "ف",  # ف ق (position not considered)
}
_SKELETON_MEDIAL_TO_BA = {"ن", "ي"}  # ن ي


# Characters removed at every level.
_REMOVE = re.compile(
    "["
    "ؐ-ؚ"  # honorific / Quranic signs above letters
    "ً-ٟ"  # harakat, tanween, shadda, sukun, extended marks
    "ٰ"  # superscript (dagger) alef
    "ۖ-ۭ"  # Quranic pause marks, small high letters, rub el hizb, sajdah
    "࣓-ࣿ"  # extended Arabic marks
    "ـ"  # tatweel
    "​-‏"  # zero-width chars and bidi marks
    "‪-‮"  # bidi embedding controls
    "⁦-⁩"  # bidi isolates
    "﻿"  # BOM
    "\\s"
    "]+"
)

_PRESENTATION = re.compile("[ﭐ-﷿ﹰ-﻿]")

_STRICT_MAP = str.maketrans(
    {
        "أ": "ا",  # أ
        "إ": "ا",  # إ
        "آ": "ا",  # آ
        "ٱ": "ا",  # ٱ alef wasla
        "ٲ": "ا",
        "ٳ": "ا",
        "ى": "ي",  # ى -> ي
        "ی": "ي",  # Persian yeh -> ي
        "ک": "ك",  # Persian kaf -> ك
    }
)

_AGGRESSIVE_MAP = str.maketrans(
    {
        "ة": "ه",  # ة -> ه
        "ؤ": "و",  # ؤ -> و
        "ئ": "ي",  # ئ -> ي
        "ء": "",  # ء removed
    }
)

_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize(text: str, level: Level = Level.STRICT) -> str:
    """Normalize a single token (or a short string) at the given level."""
    if _PRESENTATION.search(text):
        text = unicodedata.normalize("NFKC", text)
    text = _REMOVE.sub("", text)
    if level is Level.LIGHT:
        return text
    text = text.translate(_STRICT_MAP)
    if level is Level.STRICT:
        return text
    if level is Level.SKELETON:
        return _skeleton(text)
    return text.translate(_AGGRESSIVE_MAP)


def _skeleton(text: str) -> str:
    """Map a STRICT word to its dot-confusion skeleton (see `_SKELETON_CLASSES`)."""
    out = []
    last = len(text) - 1
    for i, ch in enumerate(text):
        if ch in _SKELETON_MEDIAL_TO_BA and i < last:
            out.append("ب")
        else:
            out.append(_SKELETON_CLASSES.get(ch, ch))
    return "".join(out)


def normalize_phrase(text: str, level: Level = Level.STRICT) -> str:
    """Normalize a multi-word string, keeping single spaces between words."""
    words = (normalize(w, level) for w in text.split())
    return " ".join(w for w in words if w)


def to_ascii_digits(text: str) -> str:
    return text.translate(_ARABIC_INDIC_DIGITS)

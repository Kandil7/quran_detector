"""Parse the reference a writer gives next to a quote, e.g. [البقرة: 153],
(سورة البقرة، الآية 153)، (2:153)، البقرة 153-154."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalizer import Level, normalize_phrase, to_ascii_digits

SURAH_NAMES = [
    "الفاتحة",
    "البقرة",
    "آل عمران",
    "النساء",
    "المائدة",
    "الأنعام",
    "الأعراف",
    "الأنفال",
    "التوبة",
    "يونس",
    "هود",
    "يوسف",
    "الرعد",
    "إبراهيم",
    "الحجر",
    "النحل",
    "الإسراء",
    "الكهف",
    "مريم",
    "طه",
    "الأنبياء",
    "الحج",
    "المؤمنون",
    "النور",
    "الفرقان",
    "الشعراء",
    "النمل",
    "القصص",
    "العنكبوت",
    "الروم",
    "لقمان",
    "السجدة",
    "الأحزاب",
    "سبأ",
    "فاطر",
    "يس",
    "الصافات",
    "ص",
    "الزمر",
    "غافر",
    "فصلت",
    "الشورى",
    "الزخرف",
    "الدخان",
    "الجاثية",
    "الأحقاف",
    "محمد",
    "الفتح",
    "الحجرات",
    "ق",
    "الذاريات",
    "الطور",
    "النجم",
    "القمر",
    "الرحمن",
    "الواقعة",
    "الحديد",
    "المجادلة",
    "الحشر",
    "الممتحنة",
    "الصف",
    "الجمعة",
    "المنافقون",
    "التغابن",
    "الطلاق",
    "التحريم",
    "الملك",
    "القلم",
    "الحاقة",
    "المعارج",
    "نوح",
    "الجن",
    "المزمل",
    "المدثر",
    "القيامة",
    "الإنسان",
    "المرسلات",
    "النبأ",
    "النازعات",
    "عبس",
    "التكوير",
    "الانفطار",
    "المطففين",
    "الانشقاق",
    "البروج",
    "الطارق",
    "الأعلى",
    "الغاشية",
    "الفجر",
    "البلد",
    "الشمس",
    "الليل",
    "الضحى",
    "الشرح",
    "التين",
    "العلق",
    "القدر",
    "البينة",
    "الزلزلة",
    "العاديات",
    "القارعة",
    "التكاثر",
    "العصر",
    "الهمزة",
    "الفيل",
    "قريش",
    "الماعون",
    "الكوثر",
    "الكافرون",
    "النصر",
    "المسد",
    "الإخلاص",
    "الفلق",
    "الناس",
]
assert len(SURAH_NAMES) == 114

_ALIASES = {
    "براءة": 9,
    "بني إسرائيل": 17,
    "المؤمن": 40,
    "حم السجدة": 41,
    "القتال": 47,
    "الدهر": 76,
    "الانشراح": 94,
    "اللهب": 111,
    "الزلزال": 99,
    "التوحيد": 112,
}

_NAME_TO_SURAH: dict[str, int] = {}
for _i, _name in enumerate(SURAH_NAMES, 1):
    _NAME_TO_SURAH[normalize_phrase(_name, Level.AGGRESSIVE)] = _i
for _name, _i in _ALIASES.items():
    _NAME_TO_SURAH[normalize_phrase(_name, Level.AGGRESSIVE)] = _i

# Longest names first so "ال عمران" wins over shorter prefixes.
_NAMES_RE = "|".join(sorted((re.escape(n) for n in _NAME_TO_SURAH), key=len, reverse=True))
_NAMED = re.compile(
    rf"(?:سوره\s*)?(?<![^\s\[\(\{{:،,])({_NAMES_RE})(?![^\s\]\)\}}:،,\d\-])"
    r"\s*[:،,\-]?\s*(?:(?:الايه|الايات|ايه|ايات)\s*)?(?:رقم\s*)?"
    r"(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?"
)
_NUMERIC = re.compile(r"(?<!\d)(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?(?!\d)")


@dataclass(frozen=True)
class Citation:
    surah: int
    ayah_start: int
    ayah_end: int
    text: str

    def covers(self, surah: int, ayah: int) -> bool:
        return surah == self.surah and self.ayah_start <= ayah <= self.ayah_end


def _prep(text: str) -> str:
    # Aggressive word-level normalization; keep punctuation and digits as-is.
    text = to_ascii_digits(text)
    out = []
    for piece in re.split(r"(\s+)", text):
        out.append(piece if piece.isspace() else _norm_piece(piece))
    return "".join(out)


def _norm_piece(piece: str) -> str:
    # Normalize Arabic runs inside a piece while keeping brackets/colons.
    return re.sub(
        r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+",
        lambda m: normalize_phrase(m.group(), Level.AGGRESSIVE),
        piece,
    )


def find_citation(text: str) -> Citation | None:
    """Return the first citation found in `text` (the window after a quote)."""
    prepared = _prep(text)
    best = None
    m = _NAMED.search(prepared)
    if m:
        surah = _NAME_TO_SURAH[m.group(1)]
        a1 = int(m.group(2))
        a2 = int(m.group(3)) if m.group(3) else a1
        best = (m.start(), Citation(surah, a1, max(a1, a2), m.group(0)))
    m = _NUMERIC.search(prepared)
    if m and 1 <= int(m.group(1)) <= 114:
        a1 = int(m.group(2))
        a2 = int(m.group(3)) if m.group(3) else a1
        cand = (m.start(), Citation(int(m.group(1)), a1, max(a1, a2), m.group(0)))
        if best is None or cand[0] < best[0]:
            best = cand
    return best[1] if best else None

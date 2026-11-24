from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# Version of the to_dict() output layout. Bump when a field is added, removed or renamed.
SCHEMA_VERSION = "3"


class Status(str, Enum):
    VERIFIED = "verified"  # matches the Quran text exactly (after normalization), one location
    AMBIGUOUS = "ambiguous"  # exact, but the same words occur in several places
    ALTERED = "altered"  # clearly intended quote with word-level differences
    SPLICED = "spliced"  # directly joined to another quote from a non-adjacent place
    CANDIDATE = "candidate"  # real Quran words, but too short/common to call a quote


@dataclass(frozen=True)
class Ref:
    surah: int
    ayah: int
    word_start: int  # 1-based, inclusive, words of the Tanzil Simple text
    word_end: int

    def __str__(self) -> str:
        return f"{self.surah}:{self.ayah}[{self.word_start}-{self.word_end}]"


@dataclass(frozen=True)
class DiffOp:
    op: str  # "variant" | "substitute" | "insert" | "delete" | "diacritic"
    got: str | None  # word in the input (None for delete)
    expected: str | None  # Quran word (None for insert)
    input_start: int | None = None  # char offsets of `got` in the input
    input_end: int | None = None
    letter_index: int | None = None  # "diacritic" only: 0-based letter in the word


@dataclass
class QuranMatch:
    start_char: int
    end_char: int
    text: str
    status: Status
    locations: list[list[Ref]]  # each location is a list of per-ayah refs
    word_count: int
    matched_words: int
    score: float  # heuristic ranking score, NOT a calibrated probability
    diff: list[DiffOp] = field(default_factory=list)
    reference_text: str = ""  # Tanzil Simple words of the (first) location
    reference_uthmani: list[str] = field(default_factory=list)  # whole ayahs
    has_context: bool = False
    claimed_ref: str | None = None
    citation_correct: bool | None = None
    spliced_with: list[int] = field(default_factory=list)
    # None: no diacritics to check (or not comparable). True/False: all marks
    # written by the writer agree / some do not. Set only when diacritics != "off".
    diacritics_ok: bool | None = None
    # "simple": matched on the Imlaei text. "uthmani": at least one input word was an
    # Uthmani spelling; reference_uthmani then holds the matched Uthmani words.
    script: str = "simple"

    @property
    def surah(self) -> int:
        return self.locations[0][0].surah

    @property
    def ayah_start(self) -> int:
        return self.locations[0][0].ayah

    @property
    def ayah_end(self) -> int:
        return self.locations[0][-1].ayah

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class DetectionResult:
    text: str
    matches: list[QuranMatch]
    source: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "matches": [m.to_dict() for m in self.matches],
            "source": self.source,
        }

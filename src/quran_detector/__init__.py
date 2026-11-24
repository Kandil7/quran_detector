"""Detect, ground and verify Quran quotes in Arabic text."""

from .corpus import Corpus
from .detector import BALANCED, HIGH_PRECISION, Config, QuranDetector
from .models import DetectionResult, DiffOp, QuranMatch, Ref, Status
from .normalizer import Level, normalize

__all__ = [
    "BALANCED",
    "HIGH_PRECISION",
    "Config",
    "Corpus",
    "DetectionResult",
    "DiffOp",
    "Level",
    "QuranDetector",
    "QuranMatch",
    "Ref",
    "Status",
    "normalize",
]
__version__ = "0.4.0"

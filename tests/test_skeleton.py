"""Level.SKELETON: dot-confusion classes for OCR candidate generation (task 06).

Letter-only probes below are not Quran text; they test the table itself.
"""

import pytest

from quran_detector.normalizer import _SKELETON_CLASSES, Level, normalize, normalize_phrase


@pytest.mark.parametrize(
    "a,b",
    [
        ("ب", "ت"),
        ("ب", "ث"),
        ("ت", "ث"),  # ب ت ث
        ("ج", "ح"),
        ("ح", "خ"),  # ج ح خ
        ("د", "ذ"),
        ("ر", "ز"),
        ("س", "ش"),
        ("ص", "ض"),
        ("ط", "ظ"),
        ("ع", "غ"),
        ("ف", "ق"),
    ],
)
def test_dot_confusions_share_a_skeleton(a, b):
    assert normalize(a, Level.SKELETON) == normalize(b, Level.SKELETON)


def test_medial_noon_and_yeh_join_the_ba_class():
    # not the last letter: ن and ي read as ب
    assert normalize("نب", Level.SKELETON) == normalize("بب", Level.SKELETON)
    assert normalize("يب", Level.SKELETON) == normalize("بب", Level.SKELETON)


def test_final_noon_and_yeh_stay_distinct():
    # negative: word-final ن and ي must not merge with the dotted class or each other
    assert normalize("بن", Level.SKELETON) == "بن"
    assert normalize("بي", Level.SKELETON) == "بي"
    assert normalize("بن", Level.SKELETON) != normalize("بي", Level.SKELETON)
    assert normalize("بن", Level.SKELETON) != normalize("بب", Level.SKELETON)


def test_letters_outside_the_table_are_unchanged():
    # negative: letters with no dot confusion keep their identity
    assert normalize("ك", Level.SKELETON) == "ك"
    assert normalize("ل", Level.SKELETON) == "ل"
    assert normalize("م", Level.SKELETON) != normalize("ن", Level.SKELETON)


def test_skeleton_is_strict_then_classes():
    # STRICT folding happens first: أ and ا are the same letter
    assert normalize("أ", Level.SKELETON) == normalize("ا", Level.SKELETON) == "ا"


def test_skeleton_phrase_keeps_word_boundaries():
    assert normalize_phrase("تب ثب", Level.SKELETON) == "بب بب"


def test_table_has_no_duplicate_targets_across_classes():
    # each dotted letter belongs to exactly one class
    reps = set(_SKELETON_CLASSES.values())
    for rep in reps:
        members = [k for k, v in _SKELETON_CLASSES.items() if v == rep]
        assert all(_SKELETON_CLASSES[m] == rep for m in members)

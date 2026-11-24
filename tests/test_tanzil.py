"""Tanzil reader: order and uniqueness are enforced (the word stream depends on them).

Test rows are built as text lines with ordinary numbers and placeholder words; no
Quran text is typed here.
"""

import pytest

from quran_detector.tanzil import default_data_dir, read_tanzil


def write(tmp_path, lines, name="t.txt"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_sorted_file_reads_and_skips_comments_and_blanks(tmp_path):
    p = write(tmp_path, ["# header", "", "1|1|aa", "1|2|bb", "2|1|cc"])
    assert read_tanzil(p) == [(1, 1, "aa"), (1, 2, "bb"), (2, 1, "cc")]


def test_unsorted_rows_are_rejected(tmp_path):
    p = write(tmp_path, ["1|2|bb", "1|1|aa"])
    with pytest.raises(ValueError, match="strictly increasing"):
        read_tanzil(p)


def test_duplicate_ayah_is_rejected(tmp_path):
    p = write(tmp_path, ["1|1|aa", "1|1|bb"])
    with pytest.raises(ValueError, match="strictly increasing"):
        read_tanzil(p)


def test_malformed_line_is_rejected(tmp_path):
    p = write(tmp_path, ["1|1"])
    with pytest.raises(ValueError, match="unexpected line format"):
        read_tanzil(p)


def test_env_variable_overrides_default_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QURAN_DETECTOR_DATA", str(tmp_path))
    assert default_data_dir() == tmp_path
    monkeypatch.delenv("QURAN_DETECTOR_DATA")
    assert default_data_dir().name == "data"

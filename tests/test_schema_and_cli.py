"""Output schema (schema/detection.schema.json) and the CLI formats.

Quran text is read from the fixture corpus inside the tests.
"""

import io
import json
from pathlib import Path

import pytest

from quran_detector import Config, Corpus, QuranDetector, Status
from quran_detector.cli import filter_min_status, main
from quran_detector.models import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"
SCHEMA = ROOT / "schema" / "detection.schema.json"


@pytest.fixture(scope="module")
def corpus():
    return Corpus.from_tanzil(FIXTURE, require_complete=False)


def verse(corpus, s, a):
    return corpus.ayahs[corpus.ayah_index[(s, a)]].simple_text


def sample_inputs(corpus):
    v = verse(corpus, 2, 153)
    words = v.split()
    altered = " ".join(words[:2] + ["كتاب"] + words[3:])  # one word replaced
    wrong_vowel = v.replace("َ", "ِ", 1)  # first fatha → kasra
    spliced = verse(corpus, 112, 1) + " " + verse(corpus, 103, 2)
    return [v, altered, wrong_vowel, spliced, "ذهبت إلى السوق صباحا"]


# ------------------------------------------------------------------ schema
def test_schema_version_is_in_output(corpus):
    out = QuranDetector(corpus).detect(verse(corpus, 2, 153)).to_dict()
    assert out["schema_version"] == SCHEMA_VERSION
    json.dumps(out)  # JSON-serializable


def test_outputs_validate_against_schema(corpus):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for mode in ("off", "report", "strict"):
        det = QuranDetector(corpus, Config(diacritics=mode, include_candidates=True))
        for text in sample_inputs(corpus):
            payload = det.detect(text).to_dict()
            errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
            assert not errors, [e.message for e in errors[:3]]


def test_schema_rejects_bad_status(corpus):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = QuranDetector(corpus).detect(verse(corpus, 2, 153)).to_dict()
    payload["matches"][0]["status"] = "probably"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


# --------------------------------------------------------------------- CLI
def run(argv):
    buf = io.StringIO()
    code = main(["--simple", str(FIXTURE), "--allow-partial-corpus", *argv], out=buf)
    assert code == 0
    return buf.getvalue()


def test_cli_json_single_file(tmp_path, corpus):
    f = tmp_path / "a.txt"
    f.write_text(verse(corpus, 2, 153), encoding="utf-8")
    data = json.loads(run(["detect", str(f)]))
    assert data["schema_version"] == SCHEMA_VERSION
    assert [m["status"] for m in data["matches"]] == ["verified"]


def test_cli_json_many_files_is_a_list(tmp_path, corpus):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(verse(corpus, 2, 153), encoding="utf-8")
    b.write_text("ذهبت إلى السوق صباحا", encoding="utf-8")
    data = json.loads(run(["detect", str(a), str(b)]))
    assert [item["path"] for item in data] == [str(a), str(b)]
    assert data[1]["result"]["matches"] == []


def test_cli_jsonl_one_line_per_match(tmp_path, corpus):
    f = tmp_path / "a.txt"
    text = "قال تعالى: ﴿" + verse(corpus, 2, 153) + "﴾ . قال تعالى: ﴿" + verse(corpus, 112, 1) + "﴾"
    f.write_text(text, encoding="utf-8")
    lines = run(["--format", "jsonl", "detect", str(f)]).strip().splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 2 and [r["match"]["status"] for r in rows] == ["verified", "verified"]
    assert all(r["schema_version"] == SCHEMA_VERSION and r["path"] == str(f) for r in rows)


def test_cli_text_format(tmp_path, corpus):
    f = tmp_path / "a.txt"
    f.write_text(verse(corpus, 2, 153), encoding="utf-8")
    [line] = run(["--format", "text", "detect", str(f)]).strip().splitlines()
    path, start, end, status, text = line.split("\t")
    assert status == "verified" and path == str(f)
    assert int(end) - int(start) == len(text)


def test_min_status_drops_weaker_matches(tmp_path, corpus):
    f = tmp_path / "a.txt"
    f.write_text(sample_inputs(corpus)[1], encoding="utf-8")  # altered
    all_matches = json.loads(run(["detect", str(f)]))["matches"]
    assert [m["status"] for m in all_matches] == ["altered"]
    strict = json.loads(run(["--min-status", "verified", "detect", str(f)]))["matches"]
    assert strict == []
    kept = json.loads(run(["--min-status", "altered", "detect", str(f)]))["matches"]
    assert len(kept) == 1


def test_filter_min_status_remaps_splice_links(corpus):
    det = QuranDetector(corpus, Config(include_candidates=True))
    res = det.detect(sample_inputs(corpus)[3])
    spliced = [m for m in res.matches if m.spliced_with]
    if not spliced:
        pytest.skip("no splice in this sample")
    kept = filter_min_status(res, Status.CANDIDATE)
    assert len(kept.matches) == len(res.matches)
    for m in kept.matches:
        assert all(0 <= j < len(kept.matches) for j in m.spliced_with)


def test_verify_text_format(corpus):
    v = verse(corpus, 2, 153)
    out = run(["--format", "text", "verify", v]).strip()
    assert out.startswith("verified\t")


def test_bad_format_is_rejected(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--simple", str(FIXTURE), "--allow-partial-corpus", "--format", "xml", "detect", str(f)])

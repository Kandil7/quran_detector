"""Tests for the evaluation harness (evaluation/). Not part of the core library."""

import json
import math
from pathlib import Path

import pytest
from evaluation.gold import GoldFormatError, load_gold
from evaluation.metrics import (
    Doc,
    Span,
    ambiguity_coverage,
    char_macro_f1,
    document_false_positives,
    latency_ms,
    reference_accuracy,
    span_prf,
    status_prf,
    verified_precision,
)
from evaluation.run_eval import evaluate, predict
from evaluation.stats import betainc, clopper_pearson_upper

from quran_detector import Config, Corpus, QuranDetector

FIXTURE = Path(__file__).parent / "fixtures" / "mini_simple.txt"


# ------------------------------------------------------------ Clopper–Pearson
def test_betainc_uniform_and_symmetry():
    for x in (0.1, 0.37, 0.8):
        assert betainc(1, 1, x) == pytest.approx(x, abs=1e-12)  # Beta(1,1) is uniform
        assert betainc(3, 5, x) == pytest.approx(1 - betainc(5, 3, 1 - x), abs=1e-12)


def test_zero_errors_closed_form_one_sided():
    # 0 errors in n: upper bound solves (1-p)^n = alpha, so p = 1 - alpha^(1/n)
    for n in (10, 100, 1000):
        assert clopper_pearson_upper(0, n, 0.95) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-9)


def test_known_value_zero_in_ten_two_sided():
    # the familiar [0, 0.3085] Clopper–Pearson 95% interval for 0 of 10
    assert clopper_pearson_upper(0, 10, two_sided=True) == pytest.approx(0.308497, abs=1e-5)


def test_bound_grows_with_errors_and_shrinks_with_n():
    assert clopper_pearson_upper(1, 100) > clopper_pearson_upper(0, 100)
    assert clopper_pearson_upper(2, 1000) < clopper_pearson_upper(2, 100)


def test_bound_edge_cases():
    assert clopper_pearson_upper(0, 0) == 1.0  # nothing observed
    assert clopper_pearson_upper(5, 5) == 1.0  # every trial failed
    with pytest.raises(ValueError):
        clopper_pearson_upper(3, 2)
    with pytest.raises(ValueError):
        clopper_pearson_upper(0, 10, confidence=1.0)


# ------------------------------------------------------------ metric edge cases
def sp(start, end, status="verified", locs=(((2, 153, 1, 11),),), doc="d", intended=True):
    return Span(doc, start, end, status, tuple(locs), intended)


def test_no_predictions_no_gold_is_undefined_not_perfect():
    r = span_prf([], [], exact=True)
    assert r["precision"] is None and r["recall"] is None and r["f1"] is None


def test_no_predictions_with_gold_is_zero_recall():
    r = span_prf([sp(0, 10)], [], exact=False)
    assert r["precision"] is None and r["recall"] == 0.0 and r["f1"] == 0.0


def test_predictions_without_gold_is_zero_f1():
    r = span_prf([], [sp(0, 10)], exact=False)
    assert r["recall"] is None and r["precision"] == 0.0 and r["f1"] == 0.0


def test_exact_vs_iou_boundaries():
    gold, pred = [sp(0, 100)], [sp(0, 80)]
    assert span_prf(gold, pred, exact=True)["tp"] == 0
    assert span_prf(gold, pred, exact=False)["tp"] == 1  # IoU 0.8
    assert span_prf([sp(0, 100)], [sp(90, 200)], exact=False)["tp"] == 0  # IoU < 0.5


def test_unintended_gold_is_ignored_for_recall():
    r = span_prf([sp(0, 10, intended=False)], [], exact=True)
    assert r["n_gold"] == 0


def test_status_f1_counts_only_same_status():
    gold = [sp(0, 20, status="altered")]
    assert status_prf(gold, [sp(0, 20, status="altered")], "altered")["f1"] == 1.0
    wrong = status_prf(gold, [sp(0, 20, status="verified")], "altered")
    assert wrong["tp"] == 0 and wrong["f1"] == 0.0 and wrong["n_pred"] == 0


def test_reference_accuracy_and_ambiguity():
    a = ((1, 1, 1, 2),)
    b = ((2, 2, 1, 2),)
    gold = [sp(0, 10, status="ambiguous", locs=(a, b))]
    assert reference_accuracy(gold, [sp(0, 10, locs=(a, b))])["accuracy"] == 1.0
    assert reference_accuracy(gold, [sp(0, 10, locs=(a,))])["accuracy"] == 0.0
    cov = ambiguity_coverage(gold, [sp(0, 10, locs=(a,))])
    assert cov["location_recall"] == 0.5 and cov["location_precision"] == 1.0


def test_verified_precision_with_bound():
    a = ((2, 153, 1, 11),)
    gold = [sp(0, 10, locs=(a,))]
    good = verified_precision(gold, [sp(0, 10, locs=(a,))])
    assert good["precision"] == 1.0 and good["errors"] == 0
    assert good["error_rate_upper_bound"] == pytest.approx(1 - 0.05, abs=1e-9)  # n=1, 0 errors
    bad = verified_precision(gold, [sp(0, 10, locs=(((8, 46, 1, 3),),))])
    assert bad["precision"] == 0.0 and bad["errors"] == 1


def test_verified_precision_no_verified_predictions():
    r = verified_precision([sp(0, 10)], [])
    assert r["precision"] is None and r["error_rate_upper_bound"] is None


def test_char_macro_f1_perfect_and_empty():
    d = Doc("d", "x" * 20, "manual", [sp(5, 15)])
    perfect = char_macro_f1([d], {"d": [sp(5, 15)]})
    assert perfect["quran_f1"] == 1.0 and perfect["macro_f1"] == 1.0
    # no Quran text and no predictions: the Quran class is undefined (None), and
    # the non-Quran class is predicted perfectly, so the macro mean is over one class
    none = char_macro_f1([Doc("e", "x" * 5, "manual", [])], {})
    assert none["quran_f1"] is None and none["non_quran_f1"] == 1.0 and none["macro_f1"] == 1.0


def test_false_positives_on_negatives():
    neg = Doc("n", "plain", "manual", [])
    r = document_false_positives([neg], {"n": [sp(0, 3)]})
    assert r["false_positive_docs"] == 1 and r["rate"] == 1.0


def test_latency_percentiles_nearest_rank():
    r = latency_ms([4.0, 1.0, 3.0, 2.0])
    assert r["p50"] == 2.0 and r["p95"] == 4.0 and r["n"] == 4
    assert latency_ms([])["p50"] is None


# ---------------------------------------------------------------- gold reader
def write_gold(tmp_path, rows):
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def base_row(**kw):
    row = {"id": "a", "text": "abcdef", "source": "manual", "spans": []}
    row.update(kw)
    return row


def test_gold_loader_accepts_negative_and_span(tmp_path):
    p = write_gold(
        tmp_path,
        [
            base_row(id="neg"),
            base_row(
                id="pos",
                spans=[
                    {
                        "start": 0,
                        "end": 3,
                        "status": "verified",
                        "locations": [[[2, 153, 1, 3]]],
                        "intended": True,
                    }
                ],
            ),
        ],
    )
    docs = load_gold(p)
    assert [d.id for d in docs] == ["neg", "pos"]
    assert docs[1].spans[0].locations == (((2, 153, 1, 3),),)


@pytest.mark.parametrize(
    "row",
    [
        base_row(source="unknown"),
        base_row(spans=[{"start": 0, "end": 99, "status": "verified", "locations": []}]),
        base_row(spans=[{"start": 0, "end": 3, "status": "maybe", "locations": []}]),
        base_row(spans=[{"start": 0, "end": 3, "status": "verified", "locations": [[[1, 2, 3]]]}]),
    ],
)
def test_gold_loader_rejects_bad_rows(tmp_path, row):
    with pytest.raises(GoldFormatError):
        load_gold(write_gold(tmp_path, [row]))


def test_gold_loader_rejects_duplicate_id(tmp_path):
    with pytest.raises(GoldFormatError):
        load_gold(write_gold(tmp_path, [base_row(), base_row()]))


# ------------------------------------------------------- end to end on fixture
def test_end_to_end_perfect_detector_on_fixture(tmp_path):
    corpus = Corpus.from_tanzil(FIXTURE, require_complete=False)
    verse = corpus.ayahs[corpus.ayah_index[(2, 153)]].simple_text  # read, not typed
    neg_text = "ذهبت إلى السوق صباحا واشتريت الخبز والحليب"
    docs = [
        Doc("pos", verse, "manual", [Span("pos", 0, len(verse), "verified", (((2, 153, 1, 11),),), True)]),
        Doc("neg", neg_text, "manual", []),
    ]
    det = QuranDetector(corpus, Config())
    preds, times = predict(det, docs)
    m = evaluate(docs, preds, times)
    assert m["span_exact"]["f1"] == 1.0
    assert m["verified_precision"]["precision"] == 1.0
    assert m["negatives"]["false_positive_docs"] == 0
    assert m["latency_ms"]["n"] == 2
    assert not math.isnan(m["latency_ms"]["p50"])

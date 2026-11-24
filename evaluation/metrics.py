"""Evaluation metrics for detection output against gold documents.

Conventions
  * A predicted match is a positive span unless its status is "candidate".
  * A gold span with intended=True is a positive span. Gold spans with
    intended=False are ignored for span metrics.
  * A predicted span matches a gold span when the character intervals have
    IoU >= 0.5 (IoU metric) or are identical (exact metric). Matching is greedy
    one-to-one, in order of decreasing overlap.
  * Undefined ratios (for example precision with no predictions) are None,
    never 0.0 or 1.0, so an empty evaluation cannot look like a perfect one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .stats import clopper_pearson_upper

POSITIVE_STATUSES = {"verified", "ambiguous", "altered", "spliced", "needs_review"}
IOU_THRESHOLD = 0.5


@dataclass
class Span:
    doc_id: str
    start: int
    end: int
    status: str
    locations: tuple  # tuple of locations; a location is a tuple of ref tuples
    intended: bool = True
    kind: str = ""  # perturbation kind (synthetic gold), "" for predictions
    words: int = 0  # word count (predictions), for length breakdowns


@dataclass
class Doc:
    id: str
    text: str
    source: str
    spans: list[Span] = field(default_factory=list)


def _ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def _f1_with_empty(tp: int, n_pred: int, n_gold: int, p: float | None, r: float | None) -> float | None:
    """F1 for span counts. None only when there is nothing on either side."""
    if n_pred == 0 and n_gold == 0:
        return None
    if tp == 0:
        return 0.0
    return _f1(p, r)


def _iou(a: Span, b: Span) -> float:
    inter = min(a.end, b.end) - max(a.start, b.start)
    if inter <= 0:
        return 0.0
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union


def match_spans(gold: list[Span], pred: list[Span], exact: bool) -> list[tuple[int, int]]:
    """Greedy one-to-one matching. Returns (gold_index, pred_index) pairs."""
    cands = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if g.doc_id != p.doc_id:
                continue  # offsets only mean something inside one document
            if exact:
                if (g.start, g.end) == (p.start, p.end):
                    cands.append((1.0, gi, pi))
            else:
                iou = _iou(g, p)
                if iou >= IOU_THRESHOLD:
                    cands.append((iou, gi, pi))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_g: set[int] = set()
    used_p: set[int] = set()
    pairs = []
    for _, gi, pi in cands:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        pairs.append((gi, pi))
    return pairs


def span_prf(gold: list[Span], pred: list[Span], exact: bool) -> dict:
    gold = [g for g in gold if g.intended]
    tp = len(match_spans(gold, pred, exact))
    p = _ratio(tp, len(pred))
    r = _ratio(tp, len(gold))
    return {
        "tp": tp,
        "n_pred": len(pred),
        "n_gold": len(gold),
        "precision": p,
        "recall": r,
        "f1": _f1_with_empty(tp, len(pred), len(gold), p, r),
    }


def status_prf(gold: list[Span], pred: list[Span], status: str) -> dict:
    """Span F1 for one status: a pair counts when both sides say `status`."""
    gold = [g for g in gold if g.intended]
    g_st = [g for g in gold if g.status == status]
    p_st = [p for p in pred if p.status == status]
    tp = len(match_spans(g_st, p_st, exact=False))  # only same-status pairs compete
    p = _ratio(tp, len(p_st))
    r = _ratio(tp, len(g_st))
    return {
        "tp": tp,
        "n_pred": len(p_st),
        "n_gold": len(g_st),
        "precision": p,
        "recall": r,
        "f1": _f1_with_empty(tp, len(p_st), len(g_st), p, r),
    }


def char_macro_f1(docs: list[Doc], preds: dict[str, list[Span]]) -> dict:
    """Character-level F1 for the Quran class and the non-Quran class, and their macro mean.

    A character is Quran in the gold if it lies in an intended gold span; in the
    prediction if it lies in a positive predicted span.
    """
    tp = fp = fn = tn = 0
    for d in docs:
        n = len(d.text)
        g = [False] * n
        for s in d.spans:
            if s.intended:
                for i in range(max(0, s.start), min(n, s.end)):
                    g[i] = True
        q = [False] * n
        for s in preds.get(d.id, []):
            if s.status in POSITIVE_STATUSES:
                for i in range(max(0, s.start), min(n, s.end)):
                    q[i] = True
        for gi, qi in zip(g, q, strict=True):
            if gi and qi:
                tp += 1
            elif qi:
                fp += 1
            elif gi:
                fn += 1
            else:
                tn += 1
    f1_quran = _f1(_ratio(tp, tp + fp), _ratio(tp, tp + fn))
    f1_non = _f1(_ratio(tn, tn + fn), _ratio(tn, tn + fp))
    vals = [v for v in (f1_quran, f1_non) if v is not None]
    return {
        "quran_f1": f1_quran,
        "non_quran_f1": f1_non,
        "macro_f1": statistics.fmean(vals) if vals else None,
    }


def reference_accuracy(gold: list[Span], pred: list[Span]) -> dict:
    """For matched spans: is the predicted location set equal to the gold set?"""
    gold_i = [g for g in gold if g.intended]
    correct = total = 0
    for gi, pi in match_spans(gold_i, pred, exact=False):
        total += 1
        if set(gold_i[gi].locations) == set(pred[pi].locations):
            correct += 1
    return {"matched": total, "correct": correct, "accuracy": _ratio(correct, total)}


def ambiguity_coverage(gold: list[Span], pred: list[Span]) -> dict:
    """Location-set recall and precision over matched gold spans with status ambiguous."""
    gold_i = [g for g in gold if g.intended and g.status == "ambiguous"]
    recalls, precisions = [], []
    for gi, pi in match_spans(gold_i, pred, exact=False):
        G = set(gold_i[gi].locations)
        P = set(pred[pi].locations)
        inter = len(G & P)
        if G:
            recalls.append(inter / len(G))
        if P:
            precisions.append(inter / len(P))
    return {
        "spans": len(gold_i),
        "location_recall": statistics.fmean(recalls) if recalls else None,
        "location_precision": statistics.fmean(precisions) if precisions else None,
    }


def recall_by_kind(gold: list[Span], pred: list[Span]) -> dict[str, dict]:
    """Span recall (IoU >= 0.5, any non-candidate prediction) for each gold kind."""
    out: dict[str, dict] = {}
    gold_i = [g for g in gold if g.intended and g.kind]
    for kind in sorted({g.kind for g in gold_i}):
        gk = [g for g in gold_i if g.kind == kind]
        tp = len(match_spans(gk, pred, exact=False))
        out[kind] = {"n_gold": len(gk), "tp": tp, "recall": _ratio(tp, len(gk))}
    return out


def _word_set(locations) -> set[tuple[int, int, int]]:
    """(surah, ayah, word) triples covered by a list of locations."""
    out: set[tuple[int, int, int]] = set()
    for loc in locations:
        for r in loc:
            s, a, w1, w2 = r[0], r[1], r[2], r[3]
            out.update((s, a, w) for w in range(w1, w2 + 1))
    return out


def _grounded(pred_locations, gold_locations) -> bool:
    """A prediction is grounded when its words lie inside one gold location.

    A fragment of a gold quote (for example what remains after a merged word) is
    exact Quran text at the right place, so it is correct. Words outside every gold
    location are not.
    """
    pw = _word_set(pred_locations)
    if not pw:
        return False
    return any(pw <= _word_set([loc]) for loc in gold_locations)


def verified_precision(
    gold: list[Span],
    pred: list[Span],
    confidence: float = 0.95,
    min_words: int = 0,
    max_words: int | None = None,
) -> dict:
    """Precision of predicted `verified` matches, with a Clopper–Pearson error bound.

    A verified prediction is correct when it matches (IoU >= 0.5) an intended gold
    span and its single location is one of the gold locations of that span.

    A verified prediction that lies inside an intended *altered* gold span is exact
    Quran text inside a damaged quote. It is neither counted as correct nor as an
    error, and is reported as `inside_altered`.
    """
    gold_i = [g for g in gold if g.intended]
    altered = [g for g in gold_i if g.status == "altered"]
    ver_all = [
        p
        for p in pred
        if p.status == "verified" and p.words >= min_words and (max_words is None or p.words <= max_words)
    ]
    ver = []
    inside = 0
    for p in ver_all:
        plen = max(p.end - p.start, 1)
        inside_alt = any(
            g.doc_id == p.doc_id and min(p.end, g.end) - max(p.start, g.start) >= 0.8 * plen for g in altered
        )
        if inside_alt:
            inside += 1
        else:
            ver.append(p)
    correct = 0
    for gi, vi in match_spans(gold_i, ver, exact=False):
        p = ver[vi]
        if _grounded(p.locations, gold_i[gi].locations):
            correct += 1
    n = len(ver)
    errors = n - correct
    return {
        "n_verified": n,
        "correct": correct,
        "errors": errors,
        "inside_altered": inside,
        "precision": _ratio(correct, n),
        "error_rate_upper_bound": clopper_pearson_upper(errors, n, confidence) if n else None,
        "confidence": confidence,
    }


def document_false_positives(docs: list[Doc], preds: dict[str, list[Span]]) -> dict:
    """Documents with no gold quote that still got a positive prediction (negatives)."""
    negatives = [d for d in docs if not any(s.intended for s in d.spans)]
    fp_docs = [d.id for d in negatives if any(s.status in POSITIVE_STATUSES for s in preds.get(d.id, []))]
    return {
        "negative_docs": len(negatives),
        "false_positive_docs": len(fp_docs),
        "rate": _ratio(len(fp_docs), len(negatives)),
    }


def latency_ms(samples: list[float]) -> dict:
    if not samples:
        return {"p50": None, "p95": None, "n": 0}
    s = sorted(samples)

    def pct(q: float) -> float:
        # nearest-rank percentile
        k = max(1, min(len(s), round(q * len(s) + 0.5 - 1e-9)))
        return s[k - 1]

    return {"p50": pct(0.50), "p95": pct(0.95), "n": len(s)}

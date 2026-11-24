"""Exact binomial confidence bound (Clopper–Pearson), pure Python.

For k errors in n trials, the Clopper–Pearson upper bound on the error rate at
confidence c is the p such that P(X <= k | p) = 1 - c, which equals the c-quantile
of Beta(k+1, n-k). It is computed here by inverting the regularized incomplete
beta function with bisection. The beta function itself uses the standard
continued fraction (Lentz's method).

Default is one-sided, which is the usual "95% upper bound". Pass two_sided=True
for the two-sided 95% interval's upper limit (confidence 0.975 on the upper side).
"""

from __future__ import annotations

import math


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 301):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b), i.e. the CDF of Beta(a, b) at x."""
    if a <= 0 or b <= 0:
        raise ValueError("a and b must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95, two_sided: bool = False) -> float:
    """Upper confidence bound on the error rate after `errors` errors in `n` trials.

    With n == 0 nothing is known, so the bound is 1.0. With errors == n the bound
    is 1.0 as well.
    """
    if n < 0 or errors < 0 or errors > n:
        raise ValueError(f"need 0 <= errors <= n, got errors={errors}, n={n}")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if n == 0 or errors == n:
        return 1.0
    level = 1.0 - (1.0 - confidence) / 2.0 if two_sided else confidence
    a, b = errors + 1.0, float(n - errors)
    lo, hi = 0.0, 1.0
    for _ in range(200):  # bisection on the CDF: I_p(a, b) is increasing in p
        mid = 0.5 * (lo + hi)
        if betainc(a, b, mid) < level:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return 0.5 * (lo + hi)

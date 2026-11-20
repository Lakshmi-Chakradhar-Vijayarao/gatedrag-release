"""Statistics for release decisions: CIs, paired tests, multiplicity, power. numpy + stdlib only."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > hi:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


@dataclass(frozen=True)
class Interval:
    estimate: float
    lower: float
    upper: float


def bootstrap_ci(values, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> Interval:
    """Percentile bootstrap CI for the mean, resampling items."""
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        raise ValueError("empty sample")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n_boot, x.size))
    means = x[idx].mean(axis=1)
    return Interval(float(x.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def cluster_bootstrap_ci(values, clusters, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> Interval:
    """Percentile bootstrap CI for the item mean, resampling whole clusters (e.g. all questions
    written from the same document), so correlated items do not shrink the interval."""
    x = np.asarray(values, dtype=float)
    labels = np.asarray(clusters)
    if x.shape[0] != labels.shape[0] or x.size == 0:
        raise ValueError("values and clusters must align and be non-empty")
    uniq = np.unique(labels)
    sums = np.array([x[labels == u].sum() for u in uniq])
    counts = np.array([(labels == u).sum() for u in uniq], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, uniq.size, size=(n_boot, uniq.size))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return Interval(float(x.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def repeated_release_risk(per_release_rate: float, n_releases: int) -> dict:
    """If each release independently faces false-block probability f, over n releases:
    expected false blocks n*f and P(at least one) = 1 - (1 - f)^n."""
    if not 0 <= per_release_rate <= 1 or n_releases < 1:
        raise ValueError("need 0 <= rate <= 1 and n_releases >= 1")
    return {"n_releases": n_releases, "expected_false_blocks": n_releases * per_release_rate,
            "p_at_least_one": 1 - (1 - per_release_rate) ** n_releases}


def paired_bootstrap_ci(baseline, candidate, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> Interval:
    """CI for mean(candidate - baseline), resampling items jointly (pairs preserved)."""
    a, b = np.asarray(baseline, float), np.asarray(candidate, float)
    if a.shape != b.shape:
        raise ValueError("paired samples must align item by item")
    return bootstrap_ci(b - a, n_boot=n_boot, alpha=alpha, seed=seed)


def mcnemar_exact(baseline, candidate, alternative: str = "less") -> tuple[float, int, int]:
    """Exact McNemar test on paired binary outcomes.

    b = items correct in baseline only, c = items correct in candidate only.
    alternative='less': H1 candidate is worse (c < b). Returns (p, b, c).
    """
    a, d = np.asarray(baseline).astype(int), np.asarray(candidate).astype(int)
    if a.shape != d.shape:
        raise ValueError("paired samples must align item by item")
    b = int(((a == 1) & (d == 0)).sum())
    c = int(((a == 0) & (d == 1)).sum())
    n = b + c
    if n == 0:
        return 1.0, b, c
    # P(X <= c) for X ~ Binomial(n, 1/2)
    cdf = sum(math.comb(n, k) for k in range(0, c + 1)) / 2 ** n
    if alternative == "less":
        return min(1.0, cdf), b, c
    if alternative == "two-sided":
        tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
        return min(1.0, 2 * tail), b, c
    raise ValueError("alternative must be 'less' or 'two-sided'")


def sign_flip_test(baseline, candidate, n_perm: int = 5000, seed: int = 0) -> float:
    """One-sided paired permutation test (H1: candidate mean < baseline mean) by random sign flips."""
    a, b = np.asarray(baseline, float), np.asarray(candidate, float)
    if a.shape != b.shape:
        raise ValueError("paired samples must align item by item")
    diff = b - a
    if np.allclose(diff, 0):
        return 1.0
    obs = diff.mean()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, diff.size))
    null = (signs * diff).mean(axis=1)
    return float((1 + (null <= obs).sum()) / (n_perm + 1))


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm step-down: returns {name: rejected} controlling family-wise error at alpha."""
    order = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(order)
    rejected, still = {}, True
    for i, (name, p) in enumerate(order):
        still = still and p <= alpha / (m - i)
        rejected[name] = still
    return rejected


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> Interval:
    if n == 0:
        return Interval(float("nan"), 0.0, 1.0)
    z = _norm_ppf(1 - alpha / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half))


def mde_paired_binary(n_items: int, discordant_rate: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest drop in a paired binary metric detectable with a one-sided test.

    Under a normal approximation the difference in proportions has variance
    ~ discordant_rate / n, so MDE = (z_{1-alpha} + z_{power}) * sqrt(discordant_rate / n).
    """
    if n_items <= 0 or not 0 < discordant_rate <= 1:
        raise ValueError("need n_items > 0 and 0 < discordant_rate <= 1")
    return (_norm_ppf(1 - alpha) + _norm_ppf(power)) * math.sqrt(discordant_rate / n_items)

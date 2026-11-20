"""Statistics for release decisions: intervals, paired tests, multiple testing, power."""

import math
from dataclasses import dataclass

import numpy as np


def _norm_ppf(p):
    if not 0.0 < p < 1.0:
        raise ValueError("p must be strictly between 0 and 1")
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        cdf = 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0)))
        if cdf < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


@dataclass(frozen=True)
class Interval:
    estimate: float
    lower: float
    upper: float


def bootstrap_ci(values, n_boot=2000, alpha=0.05, seed=0):
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        raise ValueError("empty sample")
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, x.size, size=(n_boot, x.size))
    means = x[samples].mean(axis=1)
    return Interval(
        float(np.mean(x)),
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def cluster_bootstrap_ci(values, clusters, n_boot=2000, alpha=0.05, seed=0):
    x = np.asarray(values, dtype=float)
    c = np.asarray(clusters, dtype=object)
    if x.size == 0 or c.size == 0:
        raise ValueError("empty input")
    if x.size != c.size:
        raise ValueError("values and clusters must have the same length")

    groups = {}
    for i, label in enumerate(c):
        groups.setdefault(label, []).append(i)

    labels = list(groups)
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=float)

    for j in range(n_boot):
        selected = rng.integers(0, len(labels), size=len(labels))
        total = 0.0
        count = 0
        for idx in selected:
            inds = groups[labels[idx]]
            total += float(np.sum(x[inds]))
            count += len(inds)
        means[j] = total / count

    return Interval(
        float(np.mean(x)),
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def repeated_release_risk(per_release_rate, n_releases):
    if not 0.0 <= per_release_rate <= 1.0:
        raise ValueError("per_release_rate must be between 0 and 1")
    if n_releases < 1:
        raise ValueError("n_releases must be at least 1")
    return {
        "n_releases": n_releases,
        "expected_false_blocks": n_releases * per_release_rate,
        "p_at_least_one": 1.0 - (1.0 - per_release_rate) ** n_releases,
    }


def paired_bootstrap_ci(baseline, candidate, n_boot=2000, alpha=0.05, seed=0):
    a = np.asarray(baseline, dtype=float)
    b = np.asarray(candidate, dtype=float)
    if a.shape != b.shape:
        raise ValueError("baseline and candidate must have the same shape")
    if a.size == 0:
        raise ValueError("empty sample")

    d = b - a
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, d.size, size=(n_boot, d.size))
    means = d[indices].mean(axis=1)

    return Interval(
        float(np.mean(d)),
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def mcnemar_exact(baseline, candidate, alternative="less"):
    a = np.asarray(baseline)
    b = np.asarray(candidate)

    if a.shape != b.shape:
        raise ValueError("baseline and candidate must have the same shape")

    if not np.all(np.isin(a, [0, 1])) or not np.all(np.isin(b, [0, 1])):
        raise ValueError("inputs must contain only 0 and 1")

    b_count = int(np.sum((a == 1) & (b == 0)))
    c_count = int(np.sum((a == 0) & (b == 1)))
    n = b_count + c_count

    if alternative not in ("less", "two-sided"):
        raise ValueError("invalid alternative")

    if n == 0:
        return 1.0, b_count, c_count

    def binom_cdf(k, n):
        return sum(
            math.comb(n, i) * (0.5 ** n)
            for i in range(k + 1)
        )

    if alternative == "less":
        p = binom_cdf(c_count, n)
    else:
        p = min(1.0, 2.0 * binom_cdf(min(b_count, c_count), n))

    return float(p), b_count, c_count


def sign_flip_test(baseline, candidate, n_perm=5000, seed=0):
    a = np.asarray(baseline, dtype=float)
    b = np.asarray(candidate, dtype=float)

    if a.shape != b.shape:
        raise ValueError("baseline and candidate must have the same shape")

    d = b - a

    if np.all(np.isclose(d, 0.0)):
        return 1.0

    observed = float(np.mean(d))
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, d.size))
    permuted = (signs * d).mean(axis=1)

    count = int(np.sum(permuted <= observed))
    return float((1 + count) / (n_perm + 1))


def holm(pvalues: dict, alpha=0.05):
    if not pvalues:
        return {}

    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    result = {name: False for name in pvalues}
    m = len(ordered)

    for i, (name, p) in enumerate(ordered, start=1):
        threshold = alpha / (m - i + 1)
        if p <= threshold:
            result[name] = True
        else:
            break

    return result


def wilson_ci(successes, n, alpha=0.05):
    if n == 0:
        return Interval(float("nan"), 0.0, 1.0)

    p = successes / n
    z = _norm_ppf(1.0 - alpha / 2.0)
    z2 = z * z
    denominator = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denominator
    half = (
        z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
        / denominator
    )

    return Interval(
        float(p),
        float(max(0.0, centre - half)),
        float(min(1.0, centre + half)),
    )


def mde_paired_binary(
    n_items,
    discordant_rate,
    alpha=0.05,
    power=0.8,
):
    if n_items <= 0 or not 0.0 < discordant_rate <= 1.0:
        raise ValueError("invalid n_items or discordant_rate")

    z_alpha = _norm_ppf(1.0 - alpha)
    z_power = _norm_ppf(power)

    return float(
        (z_alpha + z_power)
        * math.sqrt(discordant_rate / n_items)
    )

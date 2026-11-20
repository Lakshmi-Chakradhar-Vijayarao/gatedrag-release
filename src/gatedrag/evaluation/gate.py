"""The release gate: a candidate release is compared with the previous release and a frozen anchor."""

import tomllib
from dataclasses import dataclass, field

import numpy as np

from gatedrag.evaluation.metrics import METRICS
from gatedrag.evaluation.stats import (
    cluster_bootstrap_ci,
    holm,
    mcnemar_exact,
    paired_bootstrap_ci,
    sign_flip_test,
)


@dataclass(frozen=True)
class GateRule:
    primary: tuple = ("correct", "unsupported_shipped")
    hard: tuple = ("leak",)
    security_tested: tuple = ("injection_followed",)
    alpha: float = 0.05
    n_boot: int = 2000
    n_perm: int = 5000
    perf_tolerance: float = 0.10

    def __post_init__(self):
        for group in (self.primary, self.hard, self.security_tested):
            for metric in group:
                if metric not in METRICS or METRICS[metric] is None:
                    raise ValueError(f"invalid metric: {metric}")


def load_rule(path):
    with open(path, "rb") as f:
        data = tomllib.load(f)["gate"]

    if "primary" not in data or "alpha" not in data:
        raise ValueError("primary and alpha are required")

    return GateRule(
        primary=tuple(data["primary"]),
        hard=tuple(data.get("hard", ("leak",))),
        security_tested=tuple(
            data.get("security_tested", ("injection_followed",))
        ),
        alpha=float(data["alpha"]),
        n_boot=int(data.get("n_boot", 2000)),
        n_perm=int(data.get("n_perm", 5000)),
        perf_tolerance=float(data.get("perf_tolerance", 0.10)),
    )


@dataclass
class GateDecision:
    blocked: bool
    reasons: list
    table: list = field(default_factory=list)


def _aligned(base, cand, metric):
    a = np.asarray([row[metric] for row in base], dtype=float)
    b = np.asarray([row[metric] for row in cand], dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    return a[mask], b[mask]


def decide(base, cand, rule, seed=0, clusters=None):
    if len(base) != len(cand):
        raise ValueError("runs differ in length")

    if clusters is not None and len(clusters) != len(base):
        raise ValueError("clusters differ in length")

    reasons = []
    table = []
    primary_p = {}

    for metric in rule.primary:
        a, b = _aligned(base, cand, metric)

        if a.size == 0:
            continue

        higher_better = METRICS[metric]

        if higher_better:
            good_a = a
            good_b = b
        else:
            good_a = 1.0 - a
            good_b = 1.0 - b

        binary = np.all(
            np.isin(good_a, [0.0, 1.0])
            & np.isin(good_b, [0.0, 1.0])
        )

        if binary:
            p, _, _ = mcnemar_exact(
                good_a.astype(int),
                good_b.astype(int),
                "less",
            )
        else:
            p = sign_flip_test(
                good_a,
                good_b,
                rule.n_perm,
                seed,
            )

        ci = paired_bootstrap_ci(
            a,
            b,
            rule.n_boot,
            rule.alpha,
            seed,
        )

        row = {
            "metric": metric,
            "n": int(a.size),
            "baseline": float(np.mean(a)),
            "candidate": float(np.mean(b)),
            "diff": float(np.mean(b - a)),
            "ci_low": float(ci.lower),
            "ci_high": float(ci.upper),
            "p_worse": float(p),
        }

        if clusters is not None:
            aligned_mask = ~(
                np.isnan(
                    np.asarray(
                        [row_[metric] for row_ in base],
                        dtype=float,
                    )
                )
                | np.isnan(
                    np.asarray(
                        [row_[metric] for row_ in cand],
                        dtype=float,
                    )
                )
            )
            aligned_clusters = np.asarray(clusters, dtype=object)[
                aligned_mask
            ]
            cluster_ci = cluster_bootstrap_ci(
                b - a,
                aligned_clusters,
                rule.n_boot,
                rule.alpha,
                seed,
            )
            row["cluster_ci_low"] = float(cluster_ci.lower)
            row["cluster_ci_high"] = float(cluster_ci.upper)
            row["n_clusters"] = int(len(set(aligned_clusters.tolist())))

        table.append(row)
        primary_p[metric] = p

    for metric, rejected in holm(primary_p, rule.alpha).items():
        if rejected:
            reasons.append(f"{metric} significantly worse (p={primary_p[metric]:.4f}, Holm)")

    for metric in rule.hard:
        a, b = _aligned(base, cand, metric)
        if a.size == 0:
            continue

        baseline_failures = float(np.sum(a))
        candidate_failures = float(np.sum(b))

        if candidate_failures > baseline_failures:
            reasons.append(f"{metric} increased")

    security_p = {}

    for metric in rule.security_tested:
        a, b = _aligned(base, cand, metric)

        if a.size == 0:
            continue

        good_a = 1.0 - a
        good_b = 1.0 - b

        p, _, _ = mcnemar_exact(
            good_a.astype(int),
            good_b.astype(int),
            "less",
        )

        security_p[metric] = p

    for metric, rejected in holm(security_p, rule.alpha).items():
        if rejected:
            reasons.append(f"{metric} significantly increased")

    return GateDecision(bool(reasons), reasons, table)


def item_means(runs, metric):
    values = np.asarray(
        [[run_item[metric] for run_item in run] for run in runs],
        dtype=float,
    )

    with np.errstate(all="ignore"):
        means = np.nanmean(values, axis=0)

    all_nan = np.all(np.isnan(values), axis=0)
    if np.any(all_nan):
        means[all_nan] = values[0, all_nan]

    return means


def cluster_sign_flip_test(
    diff,
    clusters=None,
    n_perm=5000,
    seed=0,
):
    d = np.asarray(diff, dtype=float)

    if clusters is not None:
        c = np.asarray(clusters, dtype=object)
        if c.shape != d.shape:
            raise ValueError("diff and clusters must have the same shape")

        # one unit per cluster, in sorted label order, so the result does not depend on item order
        units = np.asarray([d[c == label].sum() for label in np.unique(c)], dtype=float)
    else:
        units = d.copy()

    if units.size == 0 or np.all(np.isclose(units, 0.0)):
        return 1.0

    observed = float(np.sum(units))
    rng = np.random.default_rng(seed)
    signs = rng.choice(
        np.array([-1.0, 1.0]),
        size=(n_perm, units.size),
    )
    permuted = np.sum(signs * units, axis=1)

    count = int(np.sum(permuted <= observed + 1e-12))
    return float((1 + count) / (n_perm + 1))


def _compare(
    base_runs,
    cand_runs,
    rule,
    alpha,
    label,
    clusters,
    seed,
    security,
):
    k = min(len(base_runs), len(cand_runs))
    metrics = list(rule.primary)

    if security:
        metrics.extend(rule.security_tested)

    reasons = []
    table = []
    primary_p = {}
    security_p = {}

    for metric in metrics:
        base_mean = item_means(base_runs, metric)
        cand_mean = item_means(cand_runs, metric)

        mask = ~(np.isnan(base_mean) | np.isnan(cand_mean))

        a = base_mean[mask]
        b = cand_mean[mask]

        if clusters is not None:
            c = np.asarray(clusters, dtype=object)[mask]
        else:
            c = None

        if a.size == 0:
            continue

        if METRICS[metric]:
            good_a = a
            good_b = b
        else:
            good_a = 1.0 - a
            good_b = 1.0 - b

        if k == 1:
            p, _, _ = mcnemar_exact(
                good_a.astype(int),
                good_b.astype(int),
                "less",
            )
            test_name = "exact McNemar"
        else:
            p = cluster_sign_flip_test(
                good_b - good_a,
                c,
                rule.n_perm,
                seed,
            )
            test_name = (
                "cluster permutation"
                if clusters is not None
                else "permutation"
            )

        row = {
            "comparison": label,
            "metric": metric,
            "test": test_name,
            "n": int(a.size),
            "k": int(k),
            "baseline": float(np.mean(a)),
            "candidate": float(np.mean(b)),
            "diff": float(np.mean(b - a)),
            "p_worse": float(p),
        }

        table.append(row)

        if security and metric in rule.security_tested:
            security_p[metric] = p
        elif metric in rule.primary:
            primary_p[metric] = p

    for metric, rejected in holm(primary_p, alpha).items():
        if rejected:
            reasons.append(f"{label}: {metric} significantly worse (p={primary_p[metric]:.4f}, Holm at alpha={alpha})")

    if security:
        for metric, rejected in holm(security_p, alpha).items():
            if rejected:
                reasons.append(
                    f"{label}: {metric} significantly more failures (p={security_p[metric]:.4f})"
                )

    for metric in rule.hard:
        base_failure_totals = []
        cand_failure_totals = []

        for run in base_runs:
            values = np.asarray(
                [row[metric] for row in run],
                dtype=float,
            )
            base_failure_totals.append(np.nansum(values))

        for run in cand_runs:
            values = np.asarray(
                [row[metric] for row in run],
                dtype=float,
            )
            cand_failure_totals.append(np.nansum(values))

        base_failure_mean = float(np.mean(base_failure_totals))
        cand_failure_mean = float(np.mean(cand_failure_totals))

        table.append(
            {
                "comparison": label,
                "metric": metric,
                "test": "any increase",
                "n": int(len(base_runs[0])),
                "k": int(k),
                "baseline": base_failure_mean,
                "candidate": cand_failure_mean,
                "diff": cand_failure_mean - base_failure_mean,
            }
        )

        if cand_failure_mean > base_failure_mean:
            reasons.append(f"{label}: {metric} {cand_failure_mean:g} failures/run vs {base_failure_mean:g} (hard rule)")

    return reasons, table


def perf_noninferior(
    anchor,
    cand,
    tolerance,
    stat="p95",
    n_boot=2000,
    seed=0,
):
    a = np.asarray(anchor, dtype=float)
    c = np.asarray(cand, dtype=float)

    def statistic(x):
        if stat == "p95":
            return float(np.quantile(x, 0.95))
        return float(np.mean(x))

    anchor_stat = statistic(a)
    candidate_stat = statistic(c)

    ratio = candidate_stat / max(anchor_stat, 1e-12)

    rng = np.random.default_rng(seed)
    ratios = np.empty(n_boot, dtype=float)

    for i in range(n_boot):
        a_sample = a[
            rng.integers(0, a.size, size=a.size)
        ]
        c_sample = c[
            rng.integers(0, c.size, size=c.size)
        ]

        ratios[i] = statistic(c_sample) / max(
            statistic(a_sample),
            1e-12,
        )

    upper95 = float(np.quantile(ratios, 0.95))

    return {
        "stat": stat,
        "ratio": float(ratio),
        "upper95": upper95,
        "tolerance": float(tolerance),
        "pass": bool(upper95 <= 1.0 + tolerance),
    }


def decide_release(
    previous,
    anchor,
    candidate,
    rule,
    clusters=None,
    perf=None,
    seed=0,
):
    releases = [previous, anchor, candidate]

    if any(len(release) == 0 for release in releases):
        raise ValueError("releases must not be empty")

    expected_len = len(previous[0])

    for release in releases:
        for run in release:
            if len(run) != expected_len:
                raise ValueError("runs do not cover the same items")

    a2 = rule.alpha / 2.0

    reasons_previous, table_previous = _compare(
        previous,
        candidate,
        rule,
        a2,
        "vs previous",
        clusters,
        seed,
        security=False,
    )

    reasons_anchor, table_anchor = _compare(
        anchor,
        candidate,
        rule,
        a2,
        "vs anchor",
        clusters,
        seed + 1,
        security=True,
    )

    reasons = reasons_previous + reasons_anchor
    table = table_previous + table_anchor

    if perf is not None:
        for key, stat in (
            ("latency_ms", "p95"),
            ("tokens", "mean"),
        ):
            if key not in perf["anchor"] or key not in perf["candidate"]:
                continue

            result = perf_noninferior(
                perf["anchor"][key],
                perf["candidate"][key],
                rule.perf_tolerance,
                stat=stat,
                n_boot=rule.n_boot,
                seed=seed,
            )

            table.append(
                {
                    "comparison": "vs anchor",
                    "metric": key,
                    "test": "non-inferiority",
                    "n": len(perf["candidate"][key]),
                    "k": 1,
                    "baseline": float(
                        np.quantile(
                            np.asarray(perf["anchor"][key], dtype=float),
                            0.95,
                        )
                        if stat == "p95"
                        else np.mean(
                            np.asarray(
                                perf["anchor"][key],
                                dtype=float,
                            )
                        )
                    ),
                    "candidate": float(
                        np.quantile(
                            np.asarray(
                                perf["candidate"][key],
                                dtype=float,
                            ),
                            0.95,
                        )
                        if stat == "p95"
                        else np.mean(
                            np.asarray(
                                perf["candidate"][key],
                                dtype=float,
                            )
                        )
                    ),
                    "diff": float(
                        np.mean(
                            np.asarray(
                                perf["candidate"][key],
                                dtype=float,
                            )
                        )
                        - np.mean(
                            np.asarray(
                                perf["anchor"][key],
                                dtype=float,
                            )
                        )
                    ),
                    "ratio": result["ratio"],
                    "upper95": result["upper95"],
                    "pass": result["pass"],
                }
            )

            if not result["pass"]:
                reasons.append(
                    f"vs anchor: {key} {stat} ratio upper bound {result['upper95']:.3f} > {1 + rule.perf_tolerance:.2f}"
                )

    return GateDecision(
        blocked=bool(reasons),
        reasons=reasons,
        table=table,
    )

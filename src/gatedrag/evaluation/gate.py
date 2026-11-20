"""The release gate. Its rule is read from a committed TOML file (configs/gate_rule.toml) that is
frozen before any measuring run, so the gate cannot be tuned to make its own error rates look good."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gatedrag.evaluation.metrics import METRICS
from gatedrag.evaluation.stats import cluster_bootstrap_ci, holm, mcnemar_exact, paired_bootstrap_ci, sign_flip_test


@dataclass(frozen=True)
class GateRule:
    """primary:       quality metrics; block if significantly worse (one-sided paired test, Holm).
    hard:          DETERMINISTIC security failures (e.g. access-control leaks decided by retrieval);
                   any increase over baseline blocks.
    security_tested: STOCHASTIC security failures (e.g. following injected instructions, which depends
                   on sampling); block if significantly more failures (one-sided exact McNemar, Holm
                   within this family). An 'any increase' rule on a stochastic metric blocks harmless
                   releases by chance — found in the synthetic pilot, see docs/PREREG.md."""
    primary: tuple[str, ...] = ("correct", "unsupported_shipped")
    hard: tuple[str, ...] = ("leak",)
    security_tested: tuple[str, ...] = ("injection_followed",)
    alpha: float = 0.05            # total; decide_release splits it across its two comparisons
    n_boot: int = 2000
    n_perm: int = 5000             # permutations for the K-sample test
    perf_tolerance: float = 0.10   # non-inferiority margin for p95 latency and tokens/request

    def __post_init__(self):
        for m in self.primary + self.hard + self.security_tested:
            if m not in METRICS or METRICS[m] is None:
                raise ValueError(f"unknown or non-directional metric: {m}")


def load_rule(path: str | Path) -> GateRule:
    with open(path, "rb") as f:
        d = tomllib.load(f)["gate"]
    return GateRule(primary=tuple(d["primary"]), hard=tuple(d.get("hard", ())),
                    security_tested=tuple(d.get("security_tested", ())), alpha=float(d["alpha"]),
                    n_boot=int(d.get("n_boot", 2000)), n_perm=int(d.get("n_perm", 5000)),
                    perf_tolerance=float(d.get("perf_tolerance", 0.10)))


@dataclass
class GateDecision:
    blocked: bool
    reasons: list[str]
    table: list[dict] = field(default_factory=list)


def _aligned(base: list[dict], cand: list[dict], metric: str) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([r[metric] for r in base], float)
    b = np.array([r[metric] for r in cand], float)
    keep = ~(np.isnan(a) | np.isnan(b))
    return a[keep], b[keep]


def decide(base: list[dict], cand: list[dict], rule: GateRule, seed: int = 0,
           clusters: list[str] | None = None) -> GateDecision:
    """Block the candidate if any primary metric is significantly worse (one-sided paired test,
    Holm-corrected across primaries) or any hard (security) metric has more failures than baseline.
    With `clusters`, the report adds cluster-bootstrap CIs (whole documents resampled)."""
    if len(base) != len(cand):
        raise ValueError("runs must cover the same items in the same order")
    if clusters is not None and len(clusters) != len(base):
        raise ValueError("one cluster label per item")
    pvals, table = {}, []
    for m in rule.primary:
        a, b = _aligned(base, cand, m)
        good_a, good_b = (a, b) if METRICS[m] else (1 - a, 1 - b)   # orient so higher = better
        binary = set(np.unique(np.concatenate([a, b]))) <= {0.0, 1.0}
        p = mcnemar_exact(good_a, good_b, "less")[0] if binary else sign_flip_test(good_a, good_b, seed=seed)
        ci = paired_bootstrap_ci(a, b, n_boot=rule.n_boot, seed=seed)
        pvals[m] = p
        row = {"metric": m, "n": int(a.size), "baseline": float(a.mean()), "candidate": float(b.mean()),
               "diff": ci.estimate, "ci_low": ci.lower, "ci_high": ci.upper, "p_worse": p}
        if clusters is not None:
            full_a = np.array([r[m] for r in base], float)
            full_b = np.array([r[m] for r in cand], float)
            keep = ~(np.isnan(full_a) | np.isnan(full_b))
            cci = cluster_bootstrap_ci((full_b - full_a)[keep], np.asarray(clusters)[keep],
                                       n_boot=rule.n_boot, seed=seed)
            row.update({"cluster_ci_low": cci.lower, "cluster_ci_high": cci.upper,
                        "n_clusters": int(np.unique(np.asarray(clusters)[keep]).size)})
        table.append(row)
    rejected = holm(pvals, rule.alpha)
    reasons = [f"{m} significantly worse (p={pvals[m]:.4f}, Holm)" for m in rule.primary if rejected[m]]
    for m in rule.hard:
        a, b = _aligned(base, cand, m)
        fails_a, fails_b = int(a.sum()), int(b.sum())
        table.append({"metric": m, "n": int(a.size), "baseline": float(fails_a), "candidate": float(fails_b),
                      "diff": float(fails_b - fails_a), "ci_low": math.nan, "ci_high": math.nan, "p_worse": math.nan})
        if fails_b > fails_a:
            reasons.append(f"{m}: {fails_b} failures vs {fails_a} in baseline (hard rule)")
    sec_p = {}
    for m in rule.security_tested:
        a, b = _aligned(base, cand, m)
        p = mcnemar_exact(1 - a, 1 - b, "less")[0]          # good = no failure
        sec_p[m] = p
        table.append({"metric": m, "n": int(a.size), "baseline": float(a.sum()), "candidate": float(b.sum()),
                      "diff": float(b.sum() - a.sum()), "ci_low": math.nan, "ci_high": math.nan, "p_worse": p})
    if sec_p:
        sec_rej = holm(sec_p, rule.alpha)
        reasons += [f"{m} significantly more failures (p={sec_p[m]:.4f}, Holm)" for m in sec_p if sec_rej[m]]
    return GateDecision(blocked=bool(reasons), reasons=reasons, table=table)


# ---------------------------------------------------------------------------------------------
# Release gate v3: candidate vs PREVIOUS release (sudden drops) and vs a frozen ANCHOR (the
# ratchet: many sub-threshold drops adding up). Block if either comparison fails; alpha is split
# equally between them. Each release is K >= 1 runs over the same items.
# ---------------------------------------------------------------------------------------------

def item_means(runs: list[list[dict]], metric: str) -> np.ndarray:
    """Per-item mean of a metric over the K runs of one release (NaN where not applicable)."""
    m = np.array([[r[metric] for r in run] for run in runs], float)
    with np.errstate(invalid="ignore"):
        return np.nanmean(m, axis=0) if np.isfinite(m).any() else m[0]


def cluster_sign_flip_test(diff, clusters=None, n_perm: int = 5000, seed: int = 0) -> float:
    """One-sided paired permutation test (H1: mean diff < 0). With `clusters`, signs are flipped
    for whole clusters (all items from one source document together), so correlated items are not
    treated as independent evidence."""
    diff = np.asarray(diff, float)
    if clusters is None:
        units = diff
    else:
        labels = np.asarray(clusters)
        units = np.array([diff[labels == u].sum() for u in np.unique(labels)])
    if np.allclose(units, 0):
        return 1.0
    obs = units.sum()
    rng = np.random.default_rng(seed)
    null = (rng.choice([-1.0, 1.0], size=(n_perm, units.size)) * units).sum(axis=1)
    return float((1 + (null <= obs + 1e-12).sum()) / (n_perm + 1))


def _compare(base_runs, cand_runs, rule: GateRule, alpha: float, label: str, clusters, seed: int,
             security: bool) -> tuple[list[str], list[dict]]:
    reasons, table, pvals = [], [], {}
    k = min(len(base_runs), len(cand_runs))
    metrics = list(rule.primary) + (list(rule.security_tested) if security else [])
    for m in metrics:
        a, b = item_means(base_runs, m), item_means(cand_runs, m)
        keep = ~(np.isnan(a) | np.isnan(b))
        cl = None if clusters is None else np.asarray(clusters)[keep]
        a, b = a[keep], b[keep]
        good_a, good_b = (a, b) if METRICS[m] else (1 - a, 1 - b)
        if k == 1:
            p, test = mcnemar_exact(good_a, good_b, "less")[0], "exact McNemar"
        else:
            p, test = cluster_sign_flip_test(good_b - good_a, cl, rule.n_perm, seed), \
                ("cluster permutation" if cl is not None else "permutation")
        pvals[m] = p
        table.append({"comparison": label, "metric": m, "test": test, "n": int(a.size), "k": k,
                      "baseline": float(a.mean()), "candidate": float(b.mean()),
                      "diff": float((b - a).mean()), "p_worse": p})
    primary_p = {m: pvals[m] for m in rule.primary}
    rej = holm(primary_p, alpha)
    reasons += [f"{label}: {m} significantly worse (p={primary_p[m]:.4f}, Holm at alpha={alpha})"
                for m in rule.primary if rej[m]]
    if security:
        sec_p = {m: pvals[m] for m in rule.security_tested}
        if sec_p:
            sec_rej = holm(sec_p, alpha)
            reasons += [f"{label}: {m} significantly more failures (p={sec_p[m]:.4f})" for m in sec_p if sec_rej[m]]
    for m in rule.hard:      # deterministic: any increase in mean failures per run blocks
        fa = float(np.mean([sum(r[m] for r in run) for run in base_runs]))
        fb = float(np.mean([sum(r[m] for r in run) for run in cand_runs]))
        table.append({"comparison": label, "metric": m, "test": "any increase", "baseline": fa, "candidate": fb,
                      "diff": fb - fa})
        if fb > fa:
            reasons.append(f"{label}: {m} {fb:g} failures/run vs {fa:g} (hard rule)")
    return reasons, table


def perf_noninferior(anchor: list[float], cand: list[float], tolerance: float, stat: str = "p95",
                     n_boot: int = 2000, seed: int = 0) -> dict:
    """Non-inferiority of a performance statistic (p95 latency or mean tokens/request): pass iff the
    bootstrap 95% upper bound of cand/anchor is <= 1 + tolerance."""
    a, c = np.asarray(anchor, float), np.asarray(cand, float)
    f = (lambda x: np.percentile(x, 95)) if stat == "p95" else np.mean
    rng = np.random.default_rng(seed)
    ratios = [f(rng.choice(c, c.size)) / max(f(rng.choice(a, a.size)), 1e-12) for _ in range(n_boot)]
    upper = float(np.quantile(ratios, 0.95))
    return {"stat": stat, "ratio": float(f(c) / max(f(a), 1e-12)), "upper95": upper,
            "tolerance": tolerance, "pass": upper <= 1 + tolerance}


def decide_release(previous: list[list[dict]], anchor: list[list[dict]], candidate: list[list[dict]],
                   rule: GateRule, clusters: list[str] | None = None, perf: dict | None = None,
                   seed: int = 0) -> GateDecision:
    """Gate v3. `perf` (optional): {"anchor": {"latency_ms": [...], "tokens": [...]},
    "candidate": {...}} for the latency and cost non-inferiority checks."""
    for rel in (previous, anchor, candidate):
        if not rel or len({len(run) for run in rel} | {len(candidate[0])}) != 1:
            raise ValueError("every run must cover the same items in the same order")
    a2 = rule.alpha / 2
    r1, t1 = _compare(previous, candidate, rule, a2, "vs previous", clusters, seed, security=False)
    r2, t2 = _compare(anchor, candidate, rule, a2, "vs anchor", clusters, seed + 1, security=True)
    reasons, table = r1 + r2, t1 + t2
    if perf:
        for key, stat in (("latency_ms", "p95"), ("tokens", "mean")):
            res = perf_noninferior(perf["anchor"][key], perf["candidate"][key], rule.perf_tolerance, stat,
                                   rule.n_boot, seed)
            table.append({"comparison": "vs anchor", "metric": f"{key} ({stat})", "test": "non-inferiority",
                          **{k: v for k, v in res.items() if k != "stat"}})
            if not res["pass"]:
                reasons.append(f"vs anchor: {key} {stat} ratio upper bound {res['upper95']:.3f} > "
                               f"{1 + rule.perf_tolerance:.2f}")
    return GateDecision(blocked=bool(reasons), reasons=reasons, table=table)

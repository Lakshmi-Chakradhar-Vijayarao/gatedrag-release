"""Why does a calibrated mean-drop threshold out-catch gate v3 on mid-sized quality regressions?

Measuring-run pools, K = 1 run per simulated release (as in the gate experiment). Each simulated
release records several quality statistics on `correct`; each is then calibrated to the SAME
quality-only false-block rate on no-change releases, and its catch rate on each regression compared.

  mean_prev      mean drop vs previous (the matched naive rule)
  mcn_prev       exact McNemar p vs previous (v3's test, previous only)
  mcn_either     min(p vs previous, p vs anchor) (v3's test, both comparisons)
  z_prev         paired z = mean diff / its SE, vs previous (a continuous paired test)
  v3_correct     v3's `correct` decision as configured (alpha/2 per comparison, Holm over 2 primaries),
                 i.e. the error budget it actually gives quality: not calibrated
  v3_full        gate v3's full decision (all metrics and checks): not calibrated

Document clustering is NOT exercised here: with K = 1, v3 uses exact McNemar, not the clustered
permutation test, so it cannot explain a gap measured at K = 1.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from gatedrag.evaluation.experiment import _draw_releases
from gatedrag.evaluation.gate import decide_release, load_rule
from gatedrag.evaluation.runner import load_pool


def mcnemar_less(a: np.ndarray, b: np.ndarray) -> float:
    lose = int(((a == 1) & (b == 0)).sum()); win = int(((a == 0) & (b == 1)).sum()); n = lose + win
    return 1.0 if n == 0 else sum(math.comb(n, k) for k in range(win + 1)) / 2 ** n


def stats(prev, anchor, cand, rule, clusters, s):
    p, a, c = (np.array([r["correct"] for r in rel[0]], float) for rel in (prev, anchor, cand))
    d = c - p
    sd = d.std(ddof=1)
    mp, ma = mcnemar_less(p, c), mcnemar_less(a, c)
    # v3's quality decision as configured: Holm over 2 primaries at alpha/2 per comparison -> the first
    # rejected p must be <= alpha/4; `correct` alone gets alpha/4 when it is the smaller p, alpha/2 otherwise.
    # Approximated conservatively here by running the real gate with primary = ("correct",) and alpha halved.
    return {"discordant": int((d != 0).sum()), "mean_prev": float(d.mean()), "mcn_prev": mp, "mcn_either": min(mp, ma),
            "z_prev": float(d.mean() / (sd / math.sqrt(d.size))) if sd > 0 else 0.0,
            "v3_full": decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked}


def main(pool_dir: str, out: str, n_sim: int = 2000, seed: int = 0) -> None:
    D = Path(pool_dir)
    rule = load_rule("configs/gate_rule.toml")
    from dataclasses import replace
    quality_only = replace(rule, primary=("correct",), hard=(), security_tested=(), alpha=rule.alpha / 2)
    base = load_pool(D / "pool_baseline.json"); clusters = base["meta"].get("item_clusters")
    regs = {n: load_pool(D / f"pool_{n}.json") for n in
            ("tp_release_2", "no_regenerate", "max_tokens_32", "top_k_2", "real_prompt_edit", "top_k_1")}
    rng = np.random.default_rng(seed)

    def sim(pool):
        rows = []
        for s in range(n_sim):
            if pool is None:
                prev, anchor, cand = _draw_releases(base, rng, 3, 1)
            else:
                prev, anchor = _draw_releases(base, rng, 2, 1); (cand,) = _draw_releases(pool, rng, 1, 1)
            r = stats(prev, anchor, cand, rule, clusters, s)
            r["v3_correct"] = decide_release(prev, anchor, cand, quality_only, clusters=clusters, seed=s).blocked
            rows.append(r)
        return rows

    null = sim(None); res = {n: sim(p) for n, p in regs.items()}
    # lower = more evidence of a drop, for every calibrated statistic
    cal = ("mean_prev", "mcn_prev", "mcn_either", "z_prev")
    out_d = {"n_sim": n_sim, "seed": seed, "uncalibrated_null": {k: float(np.mean([r[k] for r in null]))
                                                              for k in ("v3_full", "v3_correct")},
             "regressions": {}}
    for rate in (0.005, 0.01, 0.02):
        thr = {k: float(np.quantile([r[k] for r in null], rate)) for k in cal}
        # ties (McNemar p is discrete): report the realised null rate, not the target
        out_d[f"rate_{rate}"] = {"thresholds": thr,
                                 "realised_null": {k: float(np.mean([r[k] <= thr[k] for r in null])) for k in cal}}
        for n, rows in res.items():
            out_d["regressions"].setdefault(n, {})[f"rate_{rate}"] = {
                k: float(np.mean([r[k] <= thr[k] for r in rows])) for k in cal}
    out_d["discordant_null_mean"] = float(np.mean([r["discordant"] for r in null]))
    for n, rows in res.items():
        out_d["regressions"][n]["discordant_mean"] = float(np.mean([r["discordant"] for r in rows]))
        out_d["regressions"][n]["mean_drop"] = float(np.mean([r["mean_prev"] for r in rows]))
        out_d["regressions"][n]["v3_full"] = float(np.mean([r["v3_full"] for r in rows]))
        out_d["regressions"][n]["v3_correct"] = float(np.mean([r["v3_correct"] for r in rows]))
    Path(out).write_text(json.dumps(out_d, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2000,
         int(sys.argv[4]) if len(sys.argv) > 4 else 0)

"""One machine-written summary per pool, so every number in a write-up has a log field to trace to.

`gatedrag summarize POOL -o summary.json` writes the quantities the pilot and results documents
quote: noise d and sizing, correctness by answerability, abstention quality averaged over runs,
security counts per run, latency percentiles, and calibration (raw support as a probability, and
isotonic fitted on the first runs and tested on the rest).
"""

from __future__ import annotations

import numpy as np

from gatedrag.evaluation.abstention import abstention_report
from gatedrag.evaluation.calibration import answered_pairs, ece, fit_isotonic
from gatedrag.evaluation.splits import noise_report


def _mean(xs) -> float:
    xs = [x for x in xs if x == x]
    return float(np.mean(xs)) if xs else float("nan")


def summarize(pool: dict) -> dict:
    runs = pool["runs"]
    flat = [r for run in runs for r in run]
    ans = [r for r in flat if r.get("answerable") == 1.0]
    una = [r for r in flat if r.get("answerable") == 0.0]
    ab = [abstention_report(run) for run in runs]
    lat = np.array(pool["meta"].get("latency_ms") or [], float)
    out: dict = {
        "meta": {k: pool["meta"].get(k) for k in ("generator", "k", "n_items", "config_fingerprint", "golden_provenance")},
        "config": pool["meta"].get("config", {}),
        "correct": {"overall": _mean(r["correct"] for r in flat), "answerable": _mean(r["correct"] for r in ans),
                    "unanswerable": _mean(r["correct"] for r in una)},
        "abstention": {k: _mean(a.get(k, float("nan")) for a in ab)
                       for k in ("coverage", "selective_accuracy", "over_abstention", "aurc")},
        "security_per_run": {"leak": _mean(sum(r["leak"] for r in run) for run in runs),
                             "injection_followed": _mean(sum(r["injection_followed"] for r in run) for run in runs)},
        "latency_ms": ({"n": int(lat.size), "p50": float(np.percentile(lat, 50)) if lat.size else None,
                        "p95": float(np.percentile(lat, 95)) if lat.size else None}
                       if (pool["meta"].get("concurrency") or 1) == 1 else
                       {"omitted": f"pool ran with concurrency {pool['meta']['concurrency']}: per-answer times include "
                                   "queueing, so they are not a latency measurement (use `gatedrag loadtest`)"}),
    }
    if len(runs) >= 2:
        out["noise"] = noise_report(pool)
    s, c = answered_pairs(pool)
    if s.size:
        out["calibration"] = {"n_answers": int(s.size), "ece_raw_support": ece(s, c)[0]}
        if len(runs) >= 3:
            n_fit = (len(runs) + 1) // 2          # first half (rounded up) fits, the rest tests
            fit = answered_pairs({"runs": runs[:n_fit]})
            test = answered_pairs({"runs": runs[n_fit:]})
            if fit[0].size >= 20 and test[0].size:
                cal = fit_isotonic(*fit)
                out["calibration"].update({"isotonic_fit_runs": n_fit, "isotonic_test_runs": len(runs) - n_fit,
                                           "ece_isotonic_heldout_runs": ece([cal(x) for x in test[0]], test[1])[0]})
    return out

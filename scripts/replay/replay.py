"""Replay check for a rewrite of `evaluation/stats.py` and `evaluation/gate.py`.

`record` stores what the CURRENT code decides on a fixed set of simulated releases drawn from the
measuring run's pools. `compare`, run after a rewrite, recomputes the same draws with the code then
on disk and reports every difference.

The draws:
  K = 1 run per release: exact McNemar path (what the gate experiment uses)
  K = 3 runs per release: the document-clustered permutation path, which the experiment never exercises
                          (previous and anchor from the baseline's 6 runs, candidate from the release's 3)

Compared per draw: blocked/passed, the reasons, and each comparison's p-value.
  exact tests (McNemar, Holm): must match to 1e-9
  permutation p-values: Monte Carlo, so a rewrite with a different random stream cannot match exactly;
  they must agree within the stated tolerance and on which side of the threshold they fall

Also compared on fixed inputs: mcnemar_exact, holm, wilson_ci, mde_paired_binary, repeated_release_risk.

Usage (from the repo root; needs the measuring run's pools in data/interim/runs/kaggle_qwen7b_measure/out):
  PYTHONPATH=src .venv/bin/python scripts/replay/replay.py record    # once, BEFORE the rewrite
  PYTHONPATH=src .venv/bin/python scripts/replay/replay.py compare   # after the rewrite
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

POOLS = Path("data/interim/runs/kaggle_qwen7b_measure/out")
REF = Path("scripts/replay/reference.json")
RELEASES = ("verifier_always_accept", "max_tokens_32", "top_k_2", "no_regenerate", "tp_release_2", "acl_off",
            "real_prompt_edit", "prompt_plain")
N_K1, N_K3, SEED = 200, 40, 20261120
P_TOL = 0.03   # permutation p-values with 5,000 permutations: Monte Carlo sd at p = 0.05 is about 0.003


def _draws():
    from gatedrag.evaluation.experiment import _draw_releases
    from gatedrag.evaluation.runner import load_pool
    base = load_pool(POOLS / "pool_baseline.json")
    rng = np.random.default_rng(SEED)
    out = []
    for s in range(N_K1):                                         # null releases, K = 1
        p, a, c = _draw_releases(base, rng, 3, 1)
        out.append(("null", 1, s, p, a, c))
    for name in RELEASES:
        pool = load_pool(POOLS / f"pool_{name}.json")
        for s in range(N_K1):
            p, a = _draw_releases(base, rng, 2, 1); (c,) = _draw_releases(pool, rng, 1, 1)
            out.append((name, 1, s, p, a, c))
        for s in range(N_K3):                                     # clustered permutation path
            p, a = _draw_releases(base, rng, 2, 3); (c,) = _draw_releases(pool, rng, 1, 3)
            out.append((name, 3, s, p, a, c))
    return base["meta"].get("item_clusters"), out


def _run() -> dict:
    from gatedrag.evaluation import stats
    from gatedrag.evaluation.gate import decide_release, load_rule
    rule = load_rule("configs/gate_rule.toml")
    clusters, draws = _draws()
    rows = []
    for name, k, s, p, a, c in draws:
        d = decide_release(p, a, c, rule, clusters=clusters, seed=s)
        rows.append({"release": name, "k": k, "draw": s, "blocked": d.blocked, "reasons": sorted(d.reasons),
                     "p": {f"{t['comparison']}|{t['metric']}": t.get("p_worse") for t in d.table},
                     "test": {f"{t['comparison']}|{t['metric']}": t.get("test") for t in d.table}})
    rng = np.random.default_rng(7)
    a = rng.integers(0, 2, 247); b = np.where(rng.random(247) < 0.08, 1 - a, a)
    fixed = {"mcnemar_exact": list(stats.mcnemar_exact(a, b, "less")),
             "holm": stats.holm({"x": 0.004, "y": 0.02, "z": 0.3}, 0.05),
             "wilson_ci": stats.wilson_ci(28, 2000).__dict__,
             "mde_paired_binary": stats.mde_paired_binary(247, 0.0696, 0.025, 0.8),
             "repeated_release_risk": stats.repeated_release_risk(0.014, 50)}
    return {"seed": SEED, "rows": rows, "fixed": fixed}


def _close(x, y, tol):
    if x is None or y is None or (isinstance(x, float) and math.isnan(x)):
        return x == y or (isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y))
    return abs(float(x) - float(y)) <= tol


def compare() -> int:
    ref, now = json.loads(REF.read_text()), _run()
    problems = []
    for r, n in zip(ref["rows"], now["rows"], strict=True):
        where = f"{r['release']} K={r['k']} draw {r['draw']}"
        if r["blocked"] != n["blocked"]:
            problems.append(f"{where}: decision {r['blocked']} -> {n['blocked']}")
        for key, pv in r["p"].items():
            exact = (r["test"].get(key) or "").startswith(("exact", "McNemar")) or r["k"] == 1
            if not _close(pv, n["p"].get(key), 1e-9 if exact else P_TOL):
                problems.append(f"{where}: p[{key}] {pv} -> {n['p'].get(key)}")
    def same(x, y) -> bool:   # numbers within 1e-9, recursively; everything else exactly
        if isinstance(x, dict) and isinstance(y, dict):
            return x.keys() == y.keys() and all(same(x[k], y[k]) for k in x)
        if isinstance(x, list) and isinstance(y, list):
            return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y, strict=True))
        if isinstance(x, bool) or isinstance(y, bool):
            return x == y
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return _close(x, y, 1e-9)
        return x == y
    for name, val in ref["fixed"].items():
        now_val = json.loads(json.dumps(now["fixed"][name], default=str))
        if not same(val, now_val):
            problems.append(f"fixed input {name}: {val} -> {now_val}")
    n_dec = len(ref["rows"])
    print(f"{n_dec} decisions compared ({sum(r['k'] == 3 for r in ref['rows'])} on the clustered path); "
          f"{len(problems)} differences")
    for p in problems[:40]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["record"]:
        REF.write_text(json.dumps(_run(), default=str))
        print(f"recorded {REF}")
    elif sys.argv[1:] == ["compare"]:
        sys.exit(compare())
    else:
        print(__doc__); sys.exit(2)

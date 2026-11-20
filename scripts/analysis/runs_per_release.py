"""Gate v3 at one versus two runs per release, on the measuring run's pools.

With 6 baseline runs, previous, anchor and a no-change candidate can be drawn as three DISJOINT releases
of 2 runs each (3 x 2 = 6), which is the largest K that needs no overlap. At K = 2 the gate averages each
item over its runs and uses the document-clustered permutation test; at K = 1 it uses exact McNemar.

Reported for both K, on the same releases and seed: the no-change false-block rate, the catch rate of
each regression, and the catch rate of a mean-drop rule given the same checks and set to the same
false-block rate.

Run: PYTHONPATH=src .venv/bin/python scripts/analysis/runs_per_release.py N_SIM SEED OUT.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gatedrag.evaluation.experiment import run_experiment
from gatedrag.evaluation.gate import load_rule
from gatedrag.evaluation.runner import load_pool

POOLS = Path("data/interim/runs/kaggle_qwen7b_measure/out")
RELEASES = ("max_tokens_32", "top_k_2", "no_regenerate", "tp_release_2", "verifier_always_accept", "prompt_plain")


def main(n_sim: int, seed: int, out: str) -> None:
    rule = load_rule("configs/gate_rule.toml")
    base = load_pool(POOLS / "pool_baseline.json")
    regs = {n: load_pool(POOLS / f"pool_{n}.json") for n in RELEASES}
    res = {}
    for k in (1, 2):
        t = time.time()
        r = run_experiment(base, regs, rule, n_sim=n_sim, seed=seed, k_release=k)
        res[f"k{k}"] = {
            "seconds": round(time.time() - t, 1),
            "false_block": r["aa"]["rate"],
            "matched_naive": {kk: v for kk, v in r["naive"]["matched_false_block"].items() if kk != "regressions"},
            "catch": {n: {"v3": r["regressions"][n]["rate"]["estimate"],
                          "naive_matched": r["naive"]["matched_false_block"]["regressions"][n],
                          "effect_correct": r["regressions"][n]["effect_correct"]} for n in RELEASES},
        }
    Path(out).write_text(json.dumps({"n_sim": n_sim, "seed": seed, **res}, indent=1))
    print(json.dumps(res, indent=1)[:2500])


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])

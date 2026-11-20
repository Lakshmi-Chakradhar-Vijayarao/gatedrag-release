"""Does document clustering cost the gate power at 2 runs per release?

Same releases, seed and K = 2 as runs_per_release.py, run twice: with the documents as clusters
(signs flipped per document, the gate as configured) and without (signs flipped per item). The
item-level version treats correlated items as independent, so its false-block rate is reported too:
power bought by ignoring clustering is only real if the false-block rate stays near its nominal level.

Run: PYTHONPATH=src .venv/bin/python scripts/analysis/clustering_cost.py N_SIM SEED OUT.json
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from gatedrag.evaluation.experiment import run_experiment
from gatedrag.evaluation.gate import load_rule
from gatedrag.evaluation.runner import load_pool

POOLS = Path("data/interim/runs/kaggle_qwen7b_measure/out")
RELEASES = ("max_tokens_32", "top_k_2", "no_regenerate")


def main(n_sim: int, seed: int, out: str) -> None:
    rule = load_rule("configs/gate_rule.toml")
    base = load_pool(POOLS / "pool_baseline.json")
    regs = {n: load_pool(POOLS / f"pool_{n}.json") for n in RELEASES}
    flat = copy.deepcopy(base)
    flat["meta"]["item_clusters"] = None
    res = {}
    for name, b in (("clustered", base), ("item_level", flat)):
        r = run_experiment(b, regs, rule, n_sim=n_sim, seed=seed, k_release=2)
        res[name] = {"false_block": r["aa"]["rate"]["estimate"],
                     "catch": {n: r["regressions"][n]["rate"]["estimate"] for n in RELEASES}}
    clusters = base["meta"]["item_clusters"]
    res["n_items"], res["n_clusters"] = len(clusters), len(set(clusters))
    Path(out).write_text(json.dumps({"n_sim": n_sim, "seed": seed, **res}, indent=1))
    print(json.dumps(res))


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])

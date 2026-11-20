# Replay check for the statistics rewrite

`reference.json` was recorded from `evaluation/stats.py` and `evaluation/gate.py` as they stood on 20 Nov 2026, before the rewrite. It holds 2,120 gate decisions on draws from the measuring run's pools; 320 of them use the document-clustered permutation path (three runs per release). It also holds exact outputs of `mcnemar_exact`, `holm`, `wilson_ci`, `mde_paired_binary` and `repeated_release_risk` on fixed inputs.

## The rewrite

1. **Rewrite both files from your own understanding.** Keep the public names that the rest of the code and the tests import:
   - from `stats.py`: `bootstrap_ci`, `cluster_bootstrap_ci`, `paired_bootstrap_ci`, `mcnemar_exact`, `sign_flip_test`, `holm`, `wilson_ci`, `mde_paired_binary`, `repeated_release_risk`, `Interval`;
   - from `gate.py`: `GateRule`, `load_rule`, `GateDecision`, `decide`, `decide_release`, `item_means`, `cluster_sign_flip_test`, `perf_noninferior`.
2. **Commit in small steps** as you go.
3. **Run the tests:** `make test`. 123 should pass.
4. **Run the replay:** `PYTHONPATH=src .venv/bin/python scripts/replay/replay.py compare`.
   - Exact tests must match to 1e-9.
   - Permutation p-values must agree within 0.03, because they are Monte Carlo.
   - Every decision must match.

## How you know the check works

A planted bug (Holm without its correction) changed 91 of the 2,120 decisions, and the check flagged all of them.

## Do not

Re-record `reference.json` after you start the rewrite. It would then compare your code with itself.

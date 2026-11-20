import numpy as np
import pytest

from gatedrag.evaluation.calibration import fit_isotonic
from gatedrag.evaluation.operating_points import operating_points, render_markdown
from gatedrag.evaluation.runner import run_pool
from gatedrag.models.router import Decision, route
from gatedrag.models.verify import Verification


def test_open_loop_router_ships_unless_model_abstained(base_cfg):
    cfg = base_cfg.with_(router="open_loop")
    assert route(Verification(0.0, 1, (), False, ()), cfg, already_regenerated=False) is Decision.ACCEPT
    assert route(Verification(1.0, 0, (), True, ()), cfg, already_regenerated=False) is Decision.ABSTAIN


def test_bad_router_rejected(base_cfg):
    with pytest.raises(ValueError):
        base_cfg.with_(router="maybe")


def _pool(support, correct):
    return {"meta": {"config": {"router": "open_loop"}},
            "runs": [[{"abstained": 0.0, "support": s, "correct": c} for s, c in zip(support, correct, strict=True)]]}


def test_higher_wrong_cost_ships_less_and_more_accurately():
    rng = np.random.default_rng(0)
    s = rng.uniform(0, 1, 2000)
    c = (rng.uniform(0, 1, 2000) < s).astype(float)          # P(correct | s) = s
    rows = operating_points(_pool(s, c), fit_isotonic(s, c))
    shipped = [r["shipped_share"] for r in rows]
    acc = [r["selective_accuracy"] for r in rows]
    assert shipped == sorted(shipped, reverse=True)
    assert acc[-1] > acc[0]
    assert rows[0]["p_threshold"] == pytest.approx(1 - 1 / 1.5, abs=1e-4)
    assert "ship if p" in render_markdown(rows)


def test_gated_pool_is_refused(make_pipeline, base_cfg, golden):
    pool = run_pool(make_pipeline(base_cfg), golden, k=1)
    with pytest.raises(ValueError, match="open-loop"):
        operating_points(pool, fit_isotonic(np.array([0.1, 0.9]), np.array([0.0, 1.0])))


def test_open_loop_pool_ships_more_than_gated(make_pipeline, base_cfg, golden):
    gated = run_pool(make_pipeline(base_cfg), golden, k=1)["runs"][0]
    open_ = run_pool(make_pipeline(base_cfg.with_(router="open_loop")), golden, k=1)["runs"][0]
    assert sum(r["abstained"] for r in open_) <= sum(r["abstained"] for r in gated)

import math

from conftest import ROOT
from gatedrag.evaluation.gate import GateRule, decide, load_rule
from gatedrag.evaluation.runner import run_pool


def _row(correct, unsup=0.0, leak=0.0, inj=0.0):
    return {"retrieval_hit": 1.0, "reciprocal_rank": 1.0, "correct": correct, "unsupported_shipped": unsup,
            "abstained": 0.0, "leak": leak, "injection_followed": inj}


def test_frozen_rule_loads():
    rule = load_rule(ROOT / "configs" / "gate_rule.toml")
    assert rule.primary == ("correct", "unsupported_shipped") and rule.alpha == 0.05


def test_identical_runs_pass():
    run = [_row(1.0)] * 30 + [_row(0.0)] * 10
    assert not decide(run, run, GateRule()).blocked


def test_clear_regression_blocks():
    base = [_row(1.0)] * 40
    cand = [_row(0.0)] * 15 + [_row(1.0)] * 25
    d = decide(base, cand, GateRule())
    assert d.blocked and "correct" in d.reasons[0]


def test_small_noise_does_not_block():
    base = [_row(1.0)] * 39 + [_row(0.0)]
    cand = [_row(0.0)] + [_row(1.0)] * 39
    assert not decide(base, cand, GateRule()).blocked


def test_any_new_leak_blocks():
    base = [_row(1.0)] * 20
    cand = [_row(1.0)] * 19 + [_row(1.0, leak=1.0)]
    d = decide(base, cand, GateRule())
    assert d.blocked and any("leak" in r for r in d.reasons)


def test_nan_items_are_excluded_pairwise():
    base = [_row(1.0)] * 10 + [{**_row(1.0), "retrieval_hit": math.nan}]
    assert not decide(base, base, GateRule()).blocked


def test_gate_on_real_pipeline_runs(make_pipeline, golden, base_cfg):
    base = run_pool(make_pipeline(base_cfg), golden, k=1)["runs"][0]
    leaky = run_pool(make_pipeline(base_cfg.with_(acl_mode="off")), golden, k=1)["runs"][0]
    d = decide(base, leaky, GateRule())
    assert d.blocked and any("leak" in r for r in d.reasons)


def test_stochastic_security_metric_needs_significance():
    base = [_row(1.0)] * 30
    one_more = [_row(1.0)] * 29 + [_row(1.0, inj=1.0)]
    many_more = [_row(1.0)] * 22 + [_row(1.0, inj=1.0)] * 8
    assert not decide(base, one_more, GateRule()).blocked
    d = decide(base, many_more, GateRule())
    assert d.blocked and any("injection_followed" in r for r in d.reasons)

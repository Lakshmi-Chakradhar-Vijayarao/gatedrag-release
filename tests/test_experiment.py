import tomllib

import pytest

from conftest import ROOT
from gatedrag.evaluation.experiment import render_markdown, run_experiment
from gatedrag.evaluation.gate import load_rule
from gatedrag.evaluation.runner import run_pool


def test_pool_requires_sampling_for_k_gt_1(make_pipeline, golden, base_cfg):
    with pytest.raises(ValueError):
        run_pool(make_pipeline(base_cfg.with_(temperature=0.0)), golden, k=3)


def test_experiment_end_to_end_on_synthetic_fixture(make_pipeline, golden, base_cfg):
    rule = load_rule(ROOT / "configs" / "gate_rule.toml")
    with open(ROOT / "configs" / "regressions.toml", "rb") as f:
        regs = tomllib.load(f)["regressions"]
    base = run_pool(make_pipeline(base_cfg), golden, k=4, seed=1)
    pools = {name: run_pool(make_pipeline(base_cfg.with_(**delta)), golden, k=4, seed=2) for name, delta in regs.items()}
    res = run_experiment(base, pools, rule, n_sim=40, seed=0)
    assert res["gate_version"] == 3 and "known_misses" in res
    assert res["aa"]["rate"]["estimate"] <= 0.1
    assert res["regressions"]["acl_off"]["rate"]["estimate"] == 1.0          # leaks are deterministic
    assert res["regressions"]["prompt_plain"]["injections"] > 0
    md = render_markdown(res)
    assert "NOT REPORTABLE" in md and "no-change (A/A)" in md and "acl_off" in md


def test_reportable_only_with_human_items_and_real_model():
    from gatedrag.evaluation.golden import is_reportable
    assert is_reportable({"human": 300}, "openai-compatible:qwen")
    assert is_reportable({"human": 200, "human-verified-draft": 150}, "transformers:qwen")
    assert not is_reportable({"human": 299, "llm-draft": 1}, "openai-compatible:qwen")
    assert not is_reportable({"human": 300}, "fake-extractive")
    assert not is_reportable({"synthetic-fixture": 16}, "openai-compatible:qwen")


def test_naive_gates_and_power_curve(make_pipeline, golden, base_cfg):
    from gatedrag.evaluation.experiment import naive_decisions, power_curve
    rel = lambda c: [[{"correct": x} for x in c]]
    assert naive_decisions(rel([1, 1, 1, 1]), rel([1, 1, 1, 0])) == {
        "mean_drop_gt_2pts": True, "any_drop": True, "mean_drop_gt_2pts_plus_checks": True}
    assert naive_decisions(rel([1, 0]), rel([0, 1])) == {
        "mean_drop_gt_2pts": False, "any_drop": False, "mean_drop_gt_2pts_plus_checks": False}
    # the fair ablation: no quality drop, but v3's leak/injection checks fired
    assert naive_decisions(rel([1, 0]), rel([0, 1]), checks_blocked=True)["mean_drop_gt_2pts_plus_checks"]
    rule = load_rule(ROOT / "configs" / "gate_rule.toml")
    base = run_pool(make_pipeline(base_cfg), golden, k=4, seed=1)
    pc = power_curve(base, rule, effects=(0.0, 0.3), n_sim=60)
    lo, hi = pc["rows"]
    assert hi["gate_v3"] >= lo["gate_v3"] and hi["any_drop"] >= lo["any_drop"]
    assert lo["any_drop"] > lo["gate_v3"]          # the naive "any drop" rule false-blocks under no change


def test_simulated_mde_interpolates_the_power_curve():
    from gatedrag.evaluation.experiment import simulated_mde
    rows = [{"true_drop": 0.02, "gate_v3": 0.2}, {"true_drop": 0.05, "gate_v3": 0.72}, {"true_drop": 0.08, "gate_v3": 0.96}]
    assert abs(simulated_mde(rows) - 0.06) < 1e-9
    assert simulated_mde([{"true_drop": 0.1, "gate_v3": 0.5}]) is None


def test_false_block_across_seeds(make_pipeline, golden, base_cfg):
    from gatedrag.evaluation.experiment import false_block_across_seeds
    rule = load_rule(ROOT / "configs" / "gate_rule.toml")
    base = run_pool(make_pipeline(base_cfg.with_(temperature=0.7)), golden, k=3, seed=1)
    r = false_block_across_seeds(base, rule, seeds=range(3), n_sim=30)
    assert len(r["rates"]) == 3 and r["min"] <= r["mean"] <= r["max"]

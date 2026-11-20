
import numpy as np
import pytest

from gatedrag.evaluation.abstention import abstention_report
from gatedrag.evaluation.gate import GateRule, decide
from gatedrag.evaluation.stats import bootstrap_ci, cluster_bootstrap_ci, repeated_release_risk


def test_cluster_ci_is_wider_when_items_are_correlated():
    rng = np.random.default_rng(0)
    clusters = np.repeat(np.arange(20), 15)                     # 20 documents x 15 questions
    doc_effect = rng.normal(0, 1, 20)[clusters]
    x = doc_effect + rng.normal(0, 0.2, clusters.size)
    naive, clustered = bootstrap_ci(x, seed=1), cluster_bootstrap_ci(x, clusters, seed=1)
    assert (clustered.upper - clustered.lower) > 2 * (naive.upper - naive.lower)


def test_cluster_ci_matches_item_ci_when_every_item_is_its_own_cluster():
    x = np.random.default_rng(2).normal(0, 1, 300)
    a, b = bootstrap_ci(x, seed=3), cluster_bootstrap_ci(x, np.arange(300), seed=3)
    assert a.upper - a.lower == pytest.approx(b.upper - b.lower, rel=0.15)


def test_repeated_release_risk():
    r = repeated_release_risk(0.02, 50)
    assert r["expected_false_blocks"] == pytest.approx(1.0)
    assert r["p_at_least_one"] == pytest.approx(1 - 0.98 ** 50)


def _s(correct, abstained, support, answerable=1.0):
    return {"correct": correct, "abstained": abstained, "support": support, "answerable": answerable}


def test_abstention_report():
    rows = [_s(1, 0, 0.9), _s(1, 0, 0.8), _s(0, 0, 0.7), _s(0, 1, 1.0), _s(1, 1, 1.0, answerable=0.0)]
    r = abstention_report(rows)
    assert r["n_answerable"] == 4
    assert r["coverage"] == 0.75 and r["over_abstention"] == 0.25
    assert r["selective_accuracy"] == pytest.approx(2 / 3)
    # risks by rank: 0, 0, 1/3, 2/4 -> mean
    assert r["aurc"] == pytest.approx((0 + 0 + 1 / 3 + 0.5) / 4)


def test_abstention_report_rewards_ranking_errors_last():
    good = [_s(1, 0, 0.9), _s(0, 0, 0.1)]
    bad = [_s(1, 0, 0.1), _s(0, 0, 0.9)]
    assert abstention_report(good)["aurc"] < abstention_report(bad)["aurc"]


def test_gate_reports_cluster_ci():
    row = lambda c: {"correct": c, "unsupported_shipped": 0.0, "leak": 0.0, "injection_followed": 0.0}
    base = [row(1.0)] * 20
    cand = [row(1.0)] * 15 + [row(0.0)] * 5
    d = decide(base, cand, GateRule(), clusters=[f"d{i // 5}" for i in range(20)])
    t = next(r for r in d.table if r["metric"] == "correct")
    assert t["n_clusters"] == 4 and t["cluster_ci_low"] <= t["ci_low"]

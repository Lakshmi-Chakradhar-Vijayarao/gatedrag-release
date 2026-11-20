"""Gate v3: previous + anchor comparisons, K-sample cluster permutation, perf non-inferiority."""

import numpy as np

from gatedrag.evaluation.gate import GateRule, cluster_sign_flip_test, decide_release, perf_noninferior


def _run(correct, leak=None, inj=None):
    n = len(correct)
    leak = leak or [0.0] * n
    inj = inj or [0.0] * n
    return [{"correct": float(c), "unsupported_shipped": 0.0, "leak": float(lk), "injection_followed": float(j)}
            for c, lk, j in zip(correct, leak, inj, strict=True)]


def _release(correct, k=1, **kw):
    return [_run(correct, **kw) for _ in range(k)]


def test_identical_releases_pass_for_k1_and_k3():
    c = [1] * 80 + [0] * 20
    for k in (1, 3):
        d = decide_release(_release(c, k), _release(c, k), _release(c, k), GateRule())
        assert not d.blocked, d.reasons


def test_k_greater_than_one_uses_permutation_test():
    c = [1] * 80 + [0] * 20
    d = decide_release(_release(c, 3), _release(c, 3), _release(c, 3), GateRule())
    assert {r["test"] for r in d.table if r["metric"] == "correct"} == {"permutation"}


def test_ratchet_is_caught_by_the_anchor_not_by_the_previous_release():
    # each step loses 4 items (one-sided McNemar p = 0.5^4 = 0.0625 > 0.025: below threshold);
    # two steps lose 8 vs the anchor (p = 0.5^8 = 0.0039: caught)
    n = 400
    anchor = [1] * n
    previous = [0] * 4 + [1] * (n - 4)
    candidate = [0] * 8 + [1] * (n - 8)
    d = decide_release(_release(previous), _release(anchor), _release(candidate), GateRule())
    assert d.blocked
    assert all(r.startswith("vs anchor") for r in d.reasons), d.reasons


def test_clustered_items_give_weaker_evidence():
    rng = np.random.default_rng(0)
    clusters = np.repeat(np.arange(10), 20)              # 10 documents x 20 questions
    diff = np.repeat(rng.choice([-1.0, -0.6, 0.4], 10), 20) * 0.1
    p_items = cluster_sign_flip_test(diff, None, seed=0)
    p_docs = cluster_sign_flip_test(diff, clusters, seed=0)
    assert p_items < p_docs


def test_new_leak_blocks_against_either_reference():
    c = [1] * 50
    clean, leaky = _release(c), _release(c, leak=[1] + [0] * 49)
    d = decide_release(clean, clean, leaky, GateRule())
    assert d.blocked and any("leak" in r for r in d.reasons)


def test_injection_tested_against_anchor_not_any_increase():
    c = [1] * 60
    anchor = _release(c)
    one_more = _release(c, inj=[1] + [0] * 59)
    assert not decide_release(anchor, anchor, one_more, GateRule()).blocked
    many_more = _release(c, inj=[1] * 10 + [0] * 50)
    assert decide_release(anchor, anchor, many_more, GateRule()).blocked


def test_perf_noninferiority():
    # independent samples, as in real releases; >= 2,000 requests per release is needed for a 10% margin
    # on p95 (at 500, sampling noise alone gave a 1.15 ratio for a true 1.02)
    rng = np.random.default_rng(1)
    n = 5000
    base = rng.gamma(4, 50, n)
    assert perf_noninferior(base, rng.gamma(4, 50, n) * 1.02, 0.10, n_boot=1000)["pass"]
    assert not perf_noninferior(base, rng.gamma(4, 50, n) * 1.30, 0.10, n_boot=1000)["pass"]
    c = [1] * 50
    rel = _release(c)
    perf = {"anchor": {"latency_ms": list(base), "tokens": [300] * n},
            "candidate": {"latency_ms": list(rng.gamma(4, 50, n) * 1.3), "tokens": [300] * n}}
    d = decide_release(rel, rel, rel, GateRule(), perf=perf)
    assert d.blocked and any("latency" in r for r in d.reasons)

import math

import numpy as np
import pytest
from scipy import stats as sps

from gatedrag.evaluation.stats import (
    _norm_ppf,
    bootstrap_ci,
    holm,
    mcnemar_exact,
    mde_paired_binary,
    paired_bootstrap_ci,
    sign_flip_test,
    wilson_ci,
)


@pytest.mark.parametrize("p", [0.001, 0.025, 0.2, 0.5, 0.8, 0.975, 0.999])
def test_norm_ppf_matches_scipy(p):
    assert _norm_ppf(p) == pytest.approx(sps.norm.ppf(p), abs=1e-7)


@pytest.mark.parametrize("b,c", [(10, 2), (3, 3), (0, 7), (25, 11), (1, 0)])
def test_mcnemar_exact_matches_binomtest(b, c):
    base = np.array([1] * b + [0] * c + [1] * 5 + [0] * 4)
    cand = np.array([0] * b + [1] * c + [1] * 5 + [0] * 4)
    p, bb, cc = mcnemar_exact(base, cand, "less")
    assert (bb, cc) == (b, c)
    if b + c:
        assert p == pytest.approx(sps.binomtest(c, b + c, 0.5, alternative="less").pvalue)
        p2, *_ = mcnemar_exact(base, cand, "two-sided")
        assert p2 == pytest.approx(sps.binomtest(c, b + c, 0.5).pvalue)


def test_bootstrap_ci_covers_mean_and_is_reproducible():
    x = np.random.default_rng(1).normal(2.0, 1.0, 400)
    ci = bootstrap_ci(x, seed=3)
    assert ci.lower < x.mean() < ci.upper
    assert ci == bootstrap_ci(x, seed=3)


def test_paired_ci_is_narrower_than_unpaired_for_correlated_data():
    rng = np.random.default_rng(0)
    item = rng.normal(0, 3, 300)
    a, b = item + rng.normal(0, 0.3, 300), item - 0.2 + rng.normal(0, 0.3, 300)
    paired = paired_bootstrap_ci(a, b, seed=0)
    unpaired_se = math.sqrt(a.var(ddof=1) / 300 + b.var(ddof=1) / 300)
    assert paired.upper < 0                       # detects the shift
    assert (paired.upper - paired.lower) < 2 * 1.96 * unpaired_se / 3


def test_sign_flip_detects_shift_and_not_null():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 200)
    assert sign_flip_test(a, a - 0.5, seed=0) < 0.01
    assert sign_flip_test(a, a, seed=0) == 1.0


def test_holm():
    r = holm({"x": 0.01, "y": 0.04, "z": 0.2}, 0.05)
    assert r == {"x": True, "y": False, "z": False}
    assert holm({"x": 0.01, "y": 0.02}, 0.05) == {"x": True, "y": True}


def test_wilson_matches_reference():
    ci = wilson_ci(8, 10)
    assert (ci.lower, ci.upper) == pytest.approx((0.4902, 0.9433), abs=1e-3)


def test_mde_shrinks_with_n():
    assert mde_paired_binary(400, 0.2) < mde_paired_binary(100, 0.2)
    assert mde_paired_binary(100, 0.2) == pytest.approx((sps.norm.ppf(0.95) + sps.norm.ppf(0.8)) * math.sqrt(0.002))

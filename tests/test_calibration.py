import numpy as np
import pytest

from gatedrag.core.config import PipelineConfig
from gatedrag.evaluation.calibration import Calibrator, ece, fit_isotonic, fit_platt
from gatedrag.models.router import Decision, expected_costs, route
from gatedrag.models.verify import Verification


def _data(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    s = rng.uniform(0, 1, n)
    y = (rng.uniform(0, 1, n) < s ** 2).astype(float)       # true P(correct | s) = s^2: miscalibrated raw score
    return s, y


def test_isotonic_is_monotone_and_reduces_ece():
    s, y = _data()
    cal = fit_isotonic(s, y)
    assert all(a <= b + 1e-12 for a, b in zip(cal.ys, cal.ys[1:], strict=False))
    s2, y2 = _data(seed=1)                                   # held-out
    assert ece([cal(x) for x in s2], y2)[0] < ece(s2, y2)[0] / 3


def test_platt_recovers_direction():
    s, y = _data()
    cal = fit_platt(s, y)
    assert cal(0.9) > cal(0.5) > cal(0.1)


def test_calibrator_round_trip(tmp_path):
    cal = fit_isotonic(*_data(500))
    cal.p_regen = 0.4
    cal.save(tmp_path / "c.json")
    back = Calibrator.load(tmp_path / "c.json")
    assert back(0.7) == pytest.approx(cal(0.7)) and back.p_regen == 0.4


def test_cost_rule():
    cfg = PipelineConfig(cost_wrong=4, cost_abstain=1, cost_regen=0.5)
    assert expected_costs(0.9, None, cfg, True) == {"ACCEPT": pytest.approx(0.4), "ABSTAIN": 1}
    c = expected_costs(0.5, 0.9, cfg, True)
    assert c["REGENERATE"] == pytest.approx(0.5 + 0.4) and c["ACCEPT"] == pytest.approx(2.0)


def test_route_with_calibrator():
    cfg = PipelineConfig(cost_wrong=4, cost_abstain=1, cost_regen=0.5)
    v = lambda s: Verification(s, 1, (), False, ())
    platt_like = Calibrator("platt", [], [0.0, 0.0])            # p = 0.5 for every score
    assert route(v(0.99), cfg, False, platt_like) is Decision.ABSTAIN          # 2.0 > 1.0, no p_regen
    platt_like.p_regen = 0.95                                                   # retry cost 0.5 + 0.2 = 0.7 < 1
    assert route(v(0.99), cfg, False, platt_like) is Decision.REGENERATE
    assert route(v(0.99), cfg, True, platt_like) is Decision.ABSTAIN           # retry budget spent
    sure = Calibrator("platt", [], [10.0, 0.0])                                 # p ~ 1
    assert route(v(0.1), cfg, False, sure) is Decision.ACCEPT

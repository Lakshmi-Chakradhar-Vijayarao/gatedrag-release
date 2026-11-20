"""Runtime guardrail: ACCEPT / REGENERATE / ABSTAIN from verified support and explicit costs."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from gatedrag.core.config import PipelineConfig
from gatedrag.models.verify import Verification

if TYPE_CHECKING:
    from gatedrag.evaluation.calibration import Calibrator


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REGENERATE = "REGENERATE"
    ABSTAIN = "ABSTAIN"


def expected_costs(p: float, p_regen: float | None, cfg: PipelineConfig, can_regenerate: bool) -> dict[str, float]:
    """Expected cost of each action, with p = calibrated P(answer correct):
        accept     (1 - p) * c_wrong
        regenerate c_regen + (1 - p_regen) * c_wrong     (only if a retry is allowed and p_regen is known)
        abstain    c_abstain
    """
    costs = {"ACCEPT": (1 - p) * cfg.cost_wrong, "ABSTAIN": cfg.cost_abstain}
    if can_regenerate and p_regen is not None:
        costs["REGENERATE"] = cfg.cost_regen + (1 - p_regen) * cfg.cost_wrong
    return costs


def route(v: Verification, cfg: PipelineConfig, already_regenerated: bool,
          calibrator: Calibrator | None = None) -> Decision:
    """Without a calibrator (uncalibrated support score): accept iff support >= 1 - c_abstain/c_wrong,
    retry once if support is within `regenerate_band` below that threshold, else abstain.

    With a calibrator fitted on the dev split: choose the action with the lowest expected cost,
    accept iff (1-p) c_wrong <= min(c_abstain, c_regen + (1-p_regen) c_wrong). Ties go to ACCEPT,
    then REGENERATE. With p_regen unknown, a retry has no demonstrated benefit and is not chosen.
    """
    if v.abstained:
        return Decision.ABSTAIN
    if cfg.router == "open_loop":     # measurement mode: no gating, support is still recorded
        return Decision.ACCEPT
    can_regen = cfg.regenerate and not already_regenerated
    if calibrator is None:
        thr = cfg.accept_threshold
        if v.support >= thr:
            return Decision.ACCEPT
        if can_regen and v.support >= thr - cfg.regenerate_band:
            return Decision.REGENERATE
        return Decision.ABSTAIN
    costs = expected_costs(calibrator(v.support), calibrator.p_regen, cfg, can_regen)
    best = min(costs.values())
    for action in ("ACCEPT", "REGENERATE", "ABSTAIN"):
        if action in costs and costs[action] <= best + 1e-12:
            return Decision(action)
    return Decision.ABSTAIN

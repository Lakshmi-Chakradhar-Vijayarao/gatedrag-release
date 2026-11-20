"""Calibrate the verifier's support score into p = P(answer is correct).

Fit on the DEV split only; report on the TEST split. Two calibrators:
  isotonic  monotone step function (pool-adjacent-violators); no shape assumption
  platt     logistic regression on the support score (1 feature, Newton's method)
Plus ECE and a reliability table.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Calibrator:
    kind: str
    xs: list[float]                 # isotonic: block upper edges; platt: unused
    ys: list[float]                 # isotonic: block values;      platt: [intercept, slope]
    p_regen: float | None = None    # mean correctness of regenerated answers on dev (None = unknown)

    def __call__(self, s: float) -> float:
        if self.kind == "platt":
            a, b = self.ys
            return 1.0 / (1.0 + math.exp(-(a + b * s)))
        i = int(np.searchsorted(self.xs, s, side="left"))
        return float(self.ys[min(i, len(self.ys) - 1)])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.__dict__, indent=2))

    @staticmethod
    def load(path: str | Path) -> Calibrator:
        return Calibrator(**json.loads(Path(path).read_text()))


def fit_isotonic(scores, labels) -> Calibrator:
    x = np.asarray(scores, float)
    y = np.asarray(labels, float)
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    blocks = [[y[i], 1.0, x[i]] for i in range(len(x))]          # [mean, weight, max x]
    merged: list[list[float]] = []
    for b in blocks:
        merged.append(b)
        while len(merged) > 1 and merged[-2][0] > merged[-1][0]:  # pool adjacent violators
            m2, m1 = merged.pop(), merged.pop()
            w = m1[1] + m2[1]
            merged.append([(m1[0] * m1[1] + m2[0] * m2[1]) / w, w, m2[2]])
    return Calibrator("isotonic", [b[2] for b in merged], [b[0] for b in merged])


def fit_platt(scores, labels, iters: int = 50) -> Calibrator:
    x = np.asarray(scores, float)
    y = np.asarray(labels, float)
    X = np.column_stack([np.ones_like(x), x])
    w = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (y - p)
        H = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(2)
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-9:
            break
    return Calibrator("platt", [], [float(w[0]), float(w[1])])


def ece(probs, labels, bins: int = 10) -> tuple[float, list[dict]]:
    """Expected calibration error with equal-width bins, and the reliability table."""
    p = np.asarray(probs, float)
    y = np.asarray(labels, float)
    edges = np.linspace(0, 1, bins + 1)
    table, total = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if m.any():
            conf, acc = float(p[m].mean()), float(y[m].mean())
            total += m.mean() * abs(conf - acc)
            table.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_p": conf, "accuracy": acc})
    return float(total), table


def answered_pairs(pool: dict) -> tuple[np.ndarray, np.ndarray]:
    """(support, correct) for every answer that was shipped (not abstained), across the pool's runs."""
    s, c = [], []
    for run in pool["runs"]:
        for r in run:
            if r.get("abstained") == 0.0 and "support" in r:
                s.append(r["support"])
                c.append(r["correct"])
    return np.array(s), np.array(c)

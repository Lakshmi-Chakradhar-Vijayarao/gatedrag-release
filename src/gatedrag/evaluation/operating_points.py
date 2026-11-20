"""How the router's operating point moves when the stated costs change.

Needs an OPEN-LOOP pool (`router = "open_loop"`): every generated answer is shipped and scored, so
the support score and correctness are known for answers the cost router would have rejected. A
pool from the gated release only contains answers that passed its own threshold, so a sweep or a
calibrator fitted on it is selection-biased.

With p = calibrated P(correct) and no retry, the router ships iff (1 - p) c_wrong <= c_abstain,
i.e. p >= 1 - c_abstain / c_wrong. Costs are in units of c_abstain.
"""

from __future__ import annotations

import numpy as np

from gatedrag.evaluation.calibration import Calibrator, answered_pairs

DEFAULT_RATIOS = (1.5, 2.0, 3.0, 4.0, 6.0, 10.0)


def operating_points(pool: dict, calibrator: Calibrator, ratios=DEFAULT_RATIOS) -> list[dict]:
    if pool["meta"]["config"].get("router") != "open_loop":
        raise ValueError("operating points need an open-loop pool (router=open_loop); a gated pool is selection-biased")
    support, correct = answered_pairs(pool)
    if support.size == 0:
        raise ValueError("no generated answers in the pool")
    p = np.array([calibrator(float(x)) for x in support])
    rows = []
    for r in ratios:
        thr = 1 - 1 / r
        ship = p >= thr
        cost = np.where(ship, (1 - correct) * r, 1.0)
        rows.append({
            "c_wrong_over_c_abstain": r, "p_threshold": round(thr, 4),
            "shipped_share": float(ship.mean()),
            "selective_accuracy": float(correct[ship].mean()) if ship.any() else None,
            "wrong_shipped_per_100": float(100 * ((1 - correct) * ship).mean()),
            "expected_cost_per_answer": float(cost.mean()),
        })
    return rows


def render_markdown(rows: list[dict]) -> str:
    lines = ["| c_wrong / c_abstain | ship if p ≥ | shipped | selective accuracy | wrong shipped /100 | cost per answer |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        acc = "—" if r["selective_accuracy"] is None else f"{r['selective_accuracy']:.3f}"
        lines.append(f"| {r['c_wrong_over_c_abstain']:g} | {r['p_threshold']:.2f} | {r['shipped_share']:.3f} | {acc} | "
                     f"{r['wrong_shipped_per_100']:.1f} | {r['expected_cost_per_answer']:.3f} |")
    return "\n".join(lines) + "\n"

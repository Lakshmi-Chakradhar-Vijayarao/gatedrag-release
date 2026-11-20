"""Abstention quality: does the router abstain on the right questions, or just abstain a lot?

On answerable items only:
  coverage            fraction of questions answered (not abstained)
  selective accuracy  accuracy among answered questions
  over-abstention     fraction of answerable questions the system abstained on
  AURC                area under the risk-coverage curve when answers are ranked by verifier
                      support (lower is better; abstentions rank last)
"""

from __future__ import annotations

import math

import numpy as np


def abstention_report(scores: list[dict]) -> dict:
    rows = [s for s in scores if s.get("answerable") == 1.0]
    if not rows:
        return {"n_answerable": 0}
    answered = np.array([s["abstained"] == 0.0 for s in rows])
    correct = np.array([s["correct"] for s in rows], dtype=float)
    conf = np.array([s["support"] if s["abstained"] == 0.0 else -math.inf for s in rows], dtype=float)
    order = np.argsort(-conf, kind="stable")
    errors = 1.0 - correct[order]
    risks = np.cumsum(errors) / np.arange(1, len(rows) + 1)
    return {
        "n_answerable": len(rows),
        "coverage": float(answered.mean()),
        "selective_accuracy": float(correct[answered].mean()) if answered.any() else math.nan,
        "over_abstention": float(1.0 - answered.mean()),
        "aurc": float(risks.mean()),
    }

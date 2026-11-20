"""Audit the automatic `correct` scorer against human labels.

`correct` on an answerable item is a token-recall rule (reference facts present in the shipped
answer). That is cheap and deterministic but can be wrong: a paraphrase misses tokens, a wrong
answer can still mention them. Before the gate's verdicts are trusted, a human labels a sample of
shipped answers and we measure how often the rule agrees.

Sampling is stratified by the automatic label (half auto-correct, half auto-wrong) so both error
directions are estimated even when one label is rare. Within-stratum rates are unbiased:
  precision = P(human correct | auto correct)   -> how often the rule credits a wrong answer
  npv       = P(human wrong   | auto wrong)     -> how often the rule penalises a right answer
Overall agreement is reweighted by each stratum's share of all shipped answers.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from gatedrag.evaluation.golden import GoldenItem
from gatedrag.evaluation.stats import wilson_ci


def shipped_answers(pool: dict, golden: list[GoldenItem]) -> list[dict]:
    """Every ACCEPTed answer to an answerable item, with its automatic label."""
    if "records" not in pool:
        raise ValueError("pool has no answer records; re-run `gatedrag pool` (records are stored by default)")
    by_id = {g.id: g for g in golden}
    ids = pool["meta"]["item_ids"]
    out = []
    for k, (scores, recs) in enumerate(zip(pool["runs"], pool["records"], strict=True)):
        for item_id, sc, rec in zip(ids, scores, recs, strict=True):
            g = by_id.get(item_id)
            if g is None or not g.answerable or rec["decision"] != "ACCEPT":
                continue
            out.append({"item": item_id, "run": k, "question": g.question, "reference": g.reference,
                        "answer": rec["answer"], "auto_correct": int(sc["correct"]), "human_correct": None})
    return out


def audit_sample(pool: dict, golden: list[GoldenItem], n: int, seed: int = 0) -> dict:
    rows = shipped_answers(pool, golden)
    rng = np.random.default_rng(seed)
    strata = {lab: [r for r in rows if r["auto_correct"] == lab] for lab in (1, 0)}
    # one answer per item per stratum, so a single item cannot dominate the sample
    sample = []
    for lab, group in strata.items():
        seen: set[str] = set()
        uniq = []
        for i in rng.permutation(len(group)):
            if group[i]["item"] not in seen:
                seen.add(group[i]["item"])
                uniq.append(group[i])
        sample += uniq[: n // 2 if lab == 1 else n - n // 2]
    order = rng.permutation(len(sample))   # labeller must not see the strata in blocks
    return {"population": {str(lab): len(g) for lab, g in strata.items()},
            "rows": [sample[i] for i in order]}


def save_sample(audit: dict, path: str | Path) -> None:
    with open(path, "w") as f:
        f.write(json.dumps({"population": audit["population"]}) + "\n")
        for r in audit["rows"]:
            f.write(json.dumps(r) + "\n")


def load_sample(path: str | Path) -> dict:
    lines = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    return {"population": lines[0]["population"], "rows": lines[1:]}


def agreement(audit: dict) -> dict:
    rows = audit["rows"]
    missing = [r["item"] for r in rows if r["human_correct"] not in (0, 1)]
    if missing:
        raise ValueError(f"{len(missing)} row(s) have no human label (set human_correct to 0 or 1)")
    pos = [r for r in rows if r["auto_correct"] == 1]
    neg = [r for r in rows if r["auto_correct"] == 0]

    def rate(group: list[dict], want: int) -> dict:
        k = sum(1 for r in group if r["human_correct"] == want)
        if not group:
            return {"value": None, "k": 0, "n": 0, "ci95": [None, None]}
        ci = wilson_ci(k, len(group))
        return {"value": k / len(group), "k": k, "n": len(group), "ci95": [ci.lower, ci.upper]}

    prec, npv = rate(pos, 1), rate(neg, 0)
    pop = {int(k): v for k, v in audit["population"].items()}
    total = pop.get(1, 0) + pop.get(0, 0)
    overall = None
    if total and prec["value"] is not None and npv["value"] is not None:
        overall = (pop.get(1, 0) * prec["value"] + pop.get(0, 0) * npv["value"]) / total
    return {"n_labelled": len(rows), "precision_auto_correct": prec, "npv_auto_wrong": npv,
            "agreement_reweighted": overall, "population": pop,
            "false_credit": [r["item"] for r in pos if r["human_correct"] == 0],
            "false_penalty": [r["item"] for r in neg if r["human_correct"] == 1]}

"""Retrieval quality measured separately from answer quality: doc-level recall@k and MRR on the
answerable golden items, per retrieval configuration, with paired bootstrap CIs against a baseline."""

from __future__ import annotations

from typing import Any

import numpy as np

from gatedrag.core.config import PipelineConfig
from gatedrag.evaluation.golden import GoldenItem
from gatedrag.evaluation.stats import bootstrap_ci, paired_bootstrap_ci
from gatedrag.models.retrieval import Retriever


def per_item(retriever: Retriever, items: list[GoldenItem], cfg: PipelineConfig) -> dict[str, np.ndarray]:
    hit, rr = [], []
    for it in items:
        hits = retriever.search(it.question, set(it.groups), cfg)
        docs = [h.chunk.doc_id for h in hits]
        ranks = [i for i, d in enumerate(docs) if d in it.gold_docs]
        hit.append(1.0 if ranks else 0.0)
        rr.append(1.0 / (ranks[0] + 1) if ranks else 0.0)
    return {"recall_at_k": np.array(hit), "mrr": np.array(rr)}


def compare(retriever: Retriever, items: list[GoldenItem], configs: dict[str, PipelineConfig],
            baseline: str) -> dict:
    items = [i for i in items if i.answerable]
    if not items:
        raise ValueError("no answerable items")
    scores = {name: per_item(retriever, items, cfg) for name, cfg in configs.items()}
    out: dict[str, Any] = {"n_items": len(items), "baseline": baseline, "rows": []}
    for name, s in scores.items():
        row: dict[str, Any] = {"config": name, "top_k": configs[name].top_k}
        for m in ("recall_at_k", "mrr"):
            ci = bootstrap_ci(s[m], seed=0)
            row[m] = {"estimate": ci.estimate, "lower": ci.lower, "upper": ci.upper}
            if name != baseline:
                d = paired_bootstrap_ci(scores[baseline][m], s[m], seed=0)
                row[m]["diff_vs_baseline"] = {"estimate": d.estimate, "lower": d.lower, "upper": d.upper}
        out["rows"].append(row)
    return out


def _cell(row: dict, m: str) -> str:
    v = row[m]
    return f"{v['estimate']:.3f} [{v['lower']:.3f}, {v['upper']:.3f}]"


def _delta(row: dict, m: str) -> str:
    d = row[m].get("diff_vs_baseline")
    return f"{d['estimate']:+.3f} [{d['lower']:+.3f}, {d['upper']:+.3f}]" if d else "—"


def render(res: dict, provenance: dict) -> str:
    from gatedrag.evaluation.golden import REPORTABLE_PROVENANCE

    lines = []
    if not set(provenance) <= REPORTABLE_PROVENANCE:
        lines += [f"> **NOT REPORTABLE.** Golden items are not all human-verified ({provenance}).", ""]
    lines += [f"Answerable items: {res['n_items']}. Paired differences are vs `{res['baseline']}`.", "",
              "| Config | top-k | Recall@k [95% CI] | Δ recall | MRR [95% CI] | Δ MRR |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {r['config']} | {r['top_k']} | {_cell(r, 'recall_at_k')} | {_delta(r, 'recall_at_k')} | "
                     f"{_cell(r, 'mrr')} | {_delta(r, 'mrr')} |")
    return "\n".join(lines)

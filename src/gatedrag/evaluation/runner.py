"""Run a configuration over the golden set K times (sampled decoding) and store the per-item scores.

A 'pool' is K complete runs. `records` (parallel to `runs`) keeps each answer's text, decision and
citations, so the automatic `correct` scorer can be audited against human labels (scorer_audit.py). The gate experiment draws simulated releases from pools, so the
no-change false-block rate reflects real run-to-run variation instead of being 0 by construction.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gatedrag.core.config import PipelineConfig
from gatedrag.evaluation.golden import GoldenItem, provenance_summary
from gatedrag.evaluation.metrics import score_item
from gatedrag.models.pipeline import Pipeline


def _record(r) -> dict:
    """What a human needs to audit the automatic scores: the shipped text and the decision."""
    return {"answer": r.answer, "decision": r.decision, "support": round(float(r.support), 4),
            "regenerated": bool(r.regenerated), "citations": list(r.citations),
            "retrieved_docs": list(r.retrieved_docs), "retrieved": list(r.retrieved),
            "mean_logprob": r.mean_logprob}


def _forbidden_snippets(pipeline: Pipeline, golden: list[GoldenItem]) -> dict[str, list[str]]:
    """For each forbidden document, distinctive 80-character snippets of its chunks (whitespace-normalised),
    so the evaluator can see a leak in the prompt text itself."""
    wanted = {d for g in golden for d in g.forbidden_docs}
    out: dict[str, list[str]] = {}
    for c in getattr(pipeline.retriever, "chunks", []):
        if c.doc_id in wanted:
            t = " ".join(c.text.split())
            out.setdefault(c.doc_id, []).append(t[:80] if len(t) >= 40 else t)
    return out


def run_pool(pipeline: Pipeline, golden: list[GoldenItem], k: int, seed: int = 0,
             store_answers: bool = True, concurrency: int = 1) -> dict:
    """`concurrency` > 1 answers items in parallel threads (for a batching server such as vLLM).
    Seeds depend only on (run, item), and results keep item order, so the pool is the same
    whatever the concurrency, up to the server's own nondeterminism."""
    if k < 1:
        raise ValueError("k >= 1")
    if pipeline.cfg.temperature == 0 and k > 1:
        raise ValueError("k > 1 needs temperature > 0, otherwise the runs are identical copies")
    runs, records, latencies, tokens = [], [], [], []
    forbidden_text = _forbidden_snippets(pipeline, golden)
    for s in range(k):
        scores, recs = [], []

        def ask(i: int, item: GoldenItem, s: int = s):
            return pipeline.answer(item.question, set(item.groups), seed=seed + 1000 * s + i)

        if concurrency > 1:
            with ThreadPoolExecutor(concurrency) as ex:
                responses = list(ex.map(ask, range(len(golden)), golden))
        else:
            responses = [ask(i, item) for i, item in enumerate(golden)]
        for item, r in zip(golden, responses, strict=True):
            scores.append(score_item(item, r, forbidden_text=forbidden_text))
            recs.append(_record(r))
            latencies.append(r.timings_ms["total"])
            tokens.append(r.prompt_tokens + r.completion_tokens)
        runs.append(scores)
        records.append(recs)
    return {
        "meta": {
            "config": pipeline.cfg.to_dict(), "config_fingerprint": pipeline.cfg.fingerprint(),
            "generator": pipeline.generator.name, "k": k, "concurrency": concurrency, "seed": seed, "n_items": len(golden),
            "item_ids": [g.id for g in golden], "item_clusters": [g.cluster_key for g in golden],
            "n_injection_items": sum(1 for g in golden if g.canary),
            "golden_provenance": provenance_summary(golden),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "latency_ms": latencies, "tokens": tokens,
        },
        "runs": runs,
        **({"records": records} if store_answers else {}),
    }


def save_pool(pool: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(pool))


def load_pool(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def config_from_pool(pool: dict) -> PipelineConfig:
    return PipelineConfig(**pool["meta"]["config"])

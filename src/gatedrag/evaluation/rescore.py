"""Re-grade stored pools when a metric definition changes, without re-running any model.

Pools keep each answer's text, decision and retrieved chunk ids, so evaluator-side metrics can be
recomputed from them. Currently: `unsupported_shipped` from evaluator-side lexical support (see
metrics.py), which a release that weakens its own verifier cannot influence.
"""

from __future__ import annotations

from gatedrag.data.corpus import Chunk
from gatedrag.models.retrieval import Hit
from gatedrag.models.verify import verify


def rescore_unsupported(pool: dict, chunks: list[Chunk]) -> dict:
    if "records" not in pool:
        raise ValueError("pool has no answer records; it cannot be re-graded")
    by_id = {c.chunk_id: c for c in chunks}
    changed = 0
    for scores, recs in zip(pool["runs"], pool["records"], strict=True):
        for sc, rec in zip(scores, recs, strict=True):
            hits = [Hit(by_id[cid], 0.0, k) for k, cid in enumerate(rec.get("retrieved") or []) if cid in by_id]
            lex = verify(rec["answer"], hits, mode="lexical").support if rec["decision"] == "ACCEPT" else 0.0
            new = float(rec["decision"] == "ACCEPT" and lex < 0.6)
            changed += int(new != sc["unsupported_shipped"])
            sc["unsupported_shipped"] = new
    pool["meta"]["rescored"] = {"unsupported_shipped": "evaluator-side lexical support", "changed": changed}
    return pool

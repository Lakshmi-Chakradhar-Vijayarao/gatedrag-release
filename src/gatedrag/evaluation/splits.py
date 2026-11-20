"""Golden-set splitting and freezing.

- Cap: at most `cap_per_doc` items per source document (cluster key), so one document cannot
  dominate the test set. Dropped items are listed, not silently discarded.
- Split by WHOLE documents: every item from a document lands in the same split, so the dev split
  (used for calibration and configuration) cannot leak a document's facts into the test split.
- Freeze: writes dev/test JSONL plus MANIFEST.json with SHA-256 hashes and counts. A measuring run
  records the manifest hash; any edit produces a new version.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from gatedrag.evaluation.golden import REPORTABLE_PROVENANCE, GoldenItem


def cap_per_document(items: list[GoldenItem], cap: int, seed: int = 0) -> tuple[list[GoldenItem], list[str]]:
    rng = np.random.default_rng(seed)
    by_doc: dict[str, list[GoldenItem]] = defaultdict(list)
    for it in items:
        by_doc[it.cluster_key].append(it)
    kept, dropped = [], []
    for doc in sorted(by_doc):
        group = by_doc[doc]
        order = rng.permutation(len(group))
        kept += [group[i] for i in sorted(order[:cap])]
        dropped += [group[i].id for i in sorted(order[cap:])]
    keep_ids = {i.id for i in kept}
    return [i for i in items if i.id in keep_ids], dropped


def split_by_document(items: list[GoldenItem], dev_fraction: float, seed: int = 0) -> tuple[list[GoldenItem], list[GoldenItem]]:
    if not 0 < dev_fraction < 1:
        raise ValueError("dev_fraction must be in (0, 1)")
    # Stratified by slice: each document is assigned to its majority slice, and within each slice
    # whole documents fill the dev split up to dev_fraction, so slice shares match across splits.
    doc_items: dict[str, list[GoldenItem]] = defaultdict(list)
    for i in items:
        doc_items[i.cluster_key].append(i)
    strata: dict[str, list[str]] = defaultdict(list)
    for doc, its in doc_items.items():
        counts: dict[str, int] = defaultdict(int)
        for i in its:
            counts[i.slice] += 1
        strata[max(sorted(counts), key=lambda s: counts[s])].append(doc)
    rng = np.random.default_rng(seed)
    dev_docs: set[str] = set()
    for stratum in sorted(strata):
        docs = sorted(strata[stratum])
        rng.shuffle(docs)
        target = dev_fraction * sum(len(doc_items[d]) for d in docs)
        count = 0
        for d in docs:
            if count >= target:
                break
            dev_docs.add(d)
            count += len(doc_items[d])
    dev = [i for i in items if i.cluster_key in dev_docs]
    test = [i for i in items if i.cluster_key not in dev_docs]
    return dev, test


def _dump(items: list[GoldenItem], path: Path) -> str:
    lines = []
    for it in items:
        d = {k: (list(v) if isinstance(v, tuple) else v) for k, v in it.__dict__.items() if v not in ("", ())}
        d.setdefault("answerable", it.answerable)
        lines.append(json.dumps(d, sort_keys=True))
    data = ("\n".join(lines) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def doc_hashes(chunks) -> dict[str, str]:
    """SHA-256 (16 hex) of each document's text, from ingested chunks."""
    text: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        text[c.doc_id].append(c.text)
    return {d: hashlib.sha256("\n".join(t).encode()).hexdigest()[:16] for d, t in text.items()}


def gold_hashes(manifest: dict) -> dict[str, str]:
    """doc -> hash. Current format: two parallel lists, `gold_doc_ids` and `gold_doc_sha256_16`, so no hash
    sits next to a document name. Secret scanners flagged hex fingerprints of public pages such as
    '.../securing_nats/auth_intro/tls_mutual_auth' as leaked credentials when the two were adjacent,
    first as {doc: hash}, then as {"doc", "sha256_16"} records. Both older formats are still read."""
    if "gold_doc_ids" in manifest:
        return dict(zip(manifest["gold_doc_ids"], manifest["gold_doc_sha256_16"], strict=True))
    raw = manifest.get("gold_doc_hashes") or {}
    if isinstance(raw, dict):
        return dict(raw)
    return {r["doc"]: r["sha256_16"] for r in raw}


def stale_items(manifest: dict, chunks) -> list[dict]:
    """Items whose gold document changed (or vanished) since the golden set was frozen."""
    current = doc_hashes(chunks)
    frozen = gold_hashes(manifest)
    changed = {d for d, h in frozen.items() if current.get(d) != h}
    return [{"item": i, "doc": d, "now": "missing" if d not in current else "changed"}
            for i, docs in (manifest.get("item_gold_docs") or {}).items() for d in docs if d in changed]


def freeze(items: list[GoldenItem], out_dir: str | Path, dev_fraction: float = 0.25, cap: int = 5, seed: int = 0,
           allow_unverified: bool = False, chunks=None) -> dict:
    prov = {i.provenance for i in items}
    if not allow_unverified and not prov <= REPORTABLE_PROVENANCE:
        raise ValueError(f"refusing to freeze unverified items {sorted(prov - REPORTABLE_PROVENANCE)}; "
                         "pass allow_unverified=True only for a pilot")
    capped, dropped = cap_per_document(items, cap, seed)
    dev, test = split_by_document(capped, dev_fraction, seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": seed, "cap_per_document": cap,
        "dev_fraction": dev_fraction, "dropped_by_cap": dropped, "pilot_only": not prov <= REPORTABLE_PROVENANCE,
        "splits": {},
    }
    for name, part in (("dev", dev), ("test", test)):
        digest = _dump(part, out / f"{name}.jsonl")
        slices: dict[str, int] = defaultdict(int)
        for i in part:
            slices[i.slice] += 1
        manifest["splits"][name] = {"sha256": digest, "n_items": len(part), "n_documents": len({i.cluster_key for i in part}),
                                    "unanswerable": sum(1 for i in part if not i.answerable), "slices": dict(slices)}
    if chunks is not None:
        hashes = doc_hashes(chunks)
        used = sorted({d for i in dev + test for d in i.gold_docs})
        missing = [d for d in used if d not in hashes]
        if missing:
            raise ValueError(f"gold docs not in the corpus: {missing[:5]}")
        manifest["gold_doc_ids"] = used
        manifest["gold_doc_sha256_16"] = [hashes[d] for d in used]
        manifest["item_gold_docs"] = {i.id: list(i.gold_docs) for i in dev + test if i.gold_docs}
    manifest["version_hash"] = hashlib.sha256(json.dumps(manifest["splits"], sort_keys=True).encode()).hexdigest()[:16]
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def noise_report(pool: dict, metric: str = "correct", alpha_per_comparison: float = 0.025,
                 mdes: tuple[float, ...] = (0.03, 0.05, 0.10)) -> dict:
    """Measured run-to-run noise d (share of items whose metric flips between two unchanged runs,
    averaged over all pairs of the pool's K runs) and the test-set size each MDE requires."""
    from gatedrag.evaluation.stats import _norm_ppf

    runs = pool["runs"]
    if len(runs) < 2:
        raise ValueError("need K >= 2 unchanged runs to measure noise")
    mats = np.array([[r[metric] for r in run] for run in runs], float)
    pairs = [(a, b) for a in range(len(runs)) for b in range(a + 1, len(runs))]
    flips = [float(np.nanmean(mats[a] != mats[b])) for a, b in pairs]
    d = float(np.mean(flips))
    z = _norm_ppf(1 - alpha_per_comparison) + _norm_ppf(0.8)
    return {"k_runs": len(runs), "n_items": mats.shape[1], "metric": metric, "d": d,
            "d_range": [float(min(flips)), float(max(flips))],
            "required_n": {f"{m:.2f}": int(np.ceil(z * z * d / (m * m))) if d > 0 else None for m in mdes},
            "alpha_per_comparison": alpha_per_comparison, "power": 0.8}

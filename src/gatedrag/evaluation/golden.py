"""Golden-set schema. Items are written (or verified) by a human BEFORE any tuning, and every item
carries its provenance so synthetic fixtures can never be reported as a real evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

PROVENANCE = ("human", "human-verified-draft", "llm-draft", "synthetic-fixture")
# Only these count toward a reportable result. `llm-draft` becomes `human-verified-draft`
# ONLY when a human has checked the item; tooling must never write that value itself.
REPORTABLE_PROVENANCE = frozenset({"human", "human-verified-draft"})


def is_reportable(provenance_counts: dict[str, int], generator: str) -> bool:
    """A result is reportable only if every golden item is human-written or human-verified
    and the generator is a real model."""
    return (not generator.startswith("fake")) and bool(provenance_counts) and \
        set(provenance_counts) <= REPORTABLE_PROVENANCE


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    answerable: bool
    gold_docs: tuple[str, ...] = ()          # doc ids that contain the answer
    reference: str = ""                       # short reference answer (key facts)
    slice: str = "general"                    # e.g. general | multi-hop | unanswerable | security
    groups: tuple[str, ...] = ("public",)     # access groups of the asking user
    forbidden_docs: tuple[str, ...] = ()      # docs this user must never retrieve
    canary: str = ""                          # string that appears only if an injected instruction was followed
    provenance: str = "human"
    cluster: str = ""                         # correlation group (default: first gold doc, else the item id)
    evidence: str = ""                        # verbatim supporting snippet, for fast human verification
    notes: str = ""                           # reviewer notes
    gold_sections: tuple[str, ...] = ()       # section heading(s) holding the evidence (provenance)

    @property
    def cluster_key(self) -> str:
        return self.cluster or (self.gold_docs[0] if self.gold_docs else self.id)

    def __post_init__(self):
        if self.provenance not in PROVENANCE:
            raise ValueError(f"{self.id}: provenance must be one of {PROVENANCE}")
        if self.answerable and not (self.gold_docs and self.reference):
            raise ValueError(f"{self.id}: answerable items need gold_docs and a reference")


def load_golden(path: str | Path) -> list[GoldenItem]:
    items, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            d = json.loads(line)
            for k in ("flags", "nearest_passage"):          # review-only fields from draft checking
                d.pop(k, None)
            for k in ("gold_docs", "groups", "forbidden_docs", "gold_sections"):
                if k in d:
                    d[k] = tuple(d[k])
            item = GoldenItem(**d)
            if item.id in seen:
                raise ValueError(f"line {n}: duplicate id {item.id}")
            seen.add(item.id)
            items.append(item)
    if not items:
        raise ValueError("empty golden set")
    return items


def golden_fingerprint(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def provenance_summary(items: list[GoldenItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i.provenance] = out.get(i.provenance, 0) + 1
    return out

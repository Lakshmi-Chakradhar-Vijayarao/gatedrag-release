"""Automatic checks on golden-set drafts before a human reviews them.

Never changes provenance. It only attaches flags so the reviewer can spend their minute per
item where it matters:
  missing_gold_doc     gold doc id not in the corpus
  reference_not_in_doc a reference content word does not appear in the gold docs
  evidence_not_verbatim evidence snippet is not a verbatim substring of the gold docs
  copied_wording       question shares >= 6 consecutive words with a gold doc (inflates BM25/verifier)
  weak_reference       reference is only short tokens/numbers (easy to match by accident)
  maybe_answerable     an 'unanswerable' item whose nearest corpus passage covers most of its key terms
  duplicate_question   same question text as an earlier item
  injection_unreached  an injection item whose planted page is not retrieved at release settings
                       (top_k = 5, the asking user's groups): it could never show injection-following
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from gatedrag.core.config import PipelineConfig
from gatedrag.data.corpus import Chunk
from gatedrag.models.retrieval import Retriever, tokenize

_STOP = frozenset("a an the is are was were be of to in on for and or what which who how when where does do did "
                  "with by from as at it its this that can i my me you your should should there any if not no "
                  "will would much many".split())


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def check_drafts(items: list[dict], chunks: list[Chunk], copy_n: int = 6,
                 answerable_overlap: float = 0.75, release_cfg: PipelineConfig | None = None) -> list[dict]:
    docs: dict[str, str] = defaultdict(str)
    for c in chunks:
        docs[c.doc_id] += "\n" + c.text
    doc_norm = {d: _norm(t) for d, t in docs.items()}
    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.doc_id].append(c)
    doc_tokens = {d: set(tokenize(t)) for d, t in docs.items()}
    retriever = Retriever(chunks)
    cfg = PipelineConfig(top_k=3, acl_mode="pre")
    rel = release_cfg or PipelineConfig(acl_mode="pre")
    seen_q: dict[str, str] = {}
    out = []
    for it in items:
        flags: list[str] = []
        gold = list(it.get("gold_docs") or [])
        if it.get("answerable"):
            missing = [g for g in gold if g not in docs]
            if missing:
                flags.append(f"missing_gold_doc:{','.join(missing)}")
            present = [g for g in gold if g in docs]
            ref_words = set(tokenize(it.get("reference", ""))) - _STOP
            pool = set().union(*(doc_tokens[g] for g in present)) if present else set()
            absent = sorted(ref_words - pool)
            if present and absent:
                flags.append(f"reference_not_in_doc:{','.join(absent)}")
            sections = []
            for snip in [s for s in (it.get("evidence") or "").split(" || ") if s.strip()]:
                if present and not any(_norm(snip) in doc_norm[g] for g in present):
                    flags.append("evidence_not_verbatim")
                    break
                # provenance: the section (heading) whose chunk holds this snippet
                hit = next((c for g in present for c in by_doc.get(g, []) if _norm(snip) in _norm(c.text)), None)
                if hit is not None:
                    sections.append(f"{hit.doc_id} § {hit.title}")
            if sections:
                it = {**it, "gold_sections": sections}
            qwords = tokenize(it["question"])
            for g in present:
                if _ngrams(qwords, copy_n) & _ngrams(tokenize(docs[g]), copy_n):
                    flags.append(f"copied_wording:{g}")
                    break
            # weak = nothing specific: no word of 4+ letters and no number of 2+ digits ("3", "max 1")
            if ref_words and not any((w.isdigit() and len(w) >= 2) or (not w.isdigit() and len(w) >= 4)
                                     for w in ref_words):
                flags.append("weak_reference")
        else:
            key = set(tokenize(it["question"])) - _STOP
            hits = retriever.search(it["question"], set(it.get("groups") or ["public"]), cfg)
            if hits and key:
                best = max(hits, key=lambda h: len(key & set(tokenize(h.chunk.text))))
                cover = len(key & set(tokenize(best.chunk.text))) / len(key)
                it = {**it, "nearest_passage": f"{best.chunk.chunk_id}: {' '.join(best.chunk.text.split())[:300]}"}
                if cover >= answerable_overlap and not it.get("forbidden_docs"):
                    flags.append(f"maybe_answerable:{best.chunk.doc_id}")
        if it.get("canary") and gold:
            got = {h.chunk.doc_id for h in retriever.search(it["question"], set(it.get("groups") or ["public"]), rel)}
            if not set(gold) & got:
                flags.append(f"injection_unreached:{gold[0]}")
        # the same question asked by users with different access groups is intentional (ACL tests)
        qn = _norm(it["question"]) + "|" + ",".join(sorted(it.get("groups") or ["public"]))
        if qn in seen_q:
            flags.append(f"duplicate_question:{seen_q[qn]}")
        seen_q.setdefault(qn, it["id"])
        if it.get("_note"):
            flags.append(f"note:{it['_note']}")
        out.append({**{k: v for k, v in it.items() if k != "_note"}, "flags": flags})
    return out


def report_markdown(checked: list[dict]) -> str:
    n = len(checked)
    flagged = [c for c in checked if c["flags"]]
    by_flag: dict[str, int] = defaultdict(int)
    for c in checked:
        for f in c["flags"]:
            by_flag[f.split(":")[0]] += 1
    slices: dict[str, int] = defaultdict(int)
    for c in checked:
        slices[c.get("slice", "general")] += 1
    lines = [f"# Draft check: {n} items, {len(flagged)} flagged", "",
             "Slices: " + ", ".join(f"{k} {v}" for k, v in sorted(slices.items())), "",
             "| Flag | Items |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(by_flag.items(), key=lambda kv: -kv[1])]
    lines += ["", "## Flagged items", ""]
    for c in flagged:
        lines.append(f"- **{c['id']}** ({c.get('slice', 'general')}): {'; '.join(c['flags'])} — {c['question']}")
    return "\n".join(lines) + "\n"


def load_drafts(folder: str | Path) -> list[dict]:
    """All part_*.jsonl drafts; notes from reviewer_notes.json (if present) are attached as flags."""
    notes_path = Path(folder) / "reviewer_notes.json"
    notes = {k: v for k, v in json.loads(notes_path.read_text()).items() if not k.startswith("_")} \
        if notes_path.exists() else {}
    items = []
    for p in sorted(Path(folder).glob("part_*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("provenance") != "llm-draft":
                    raise ValueError(f"{p.name}:{d.get('id')}: drafts must carry provenance llm-draft")
                if d["id"] in notes:
                    d["_note"] = notes[d["id"]]
                items.append(d)
    return items

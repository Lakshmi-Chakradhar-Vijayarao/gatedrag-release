"""Interactive human review of golden-set drafts.

Only a person at a terminal can mark an item verified: the command refuses to run when stdin is
not a TTY, so no script or agent can upgrade `llm-draft` to `human-verified-draft`.

Keys per item:  a = accept   e = edit then accept   r = reject   s = skip   q = save and quit
Progress is resumable: accepted items go to the output file, rejected ids to <output>.rejected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EDITABLE = ("question", "reference", "answerable", "gold_docs", "slice")


def accept(item: dict, edits: dict | None = None) -> dict:
    """Return the verified version of an item. Pure function (unit-tested)."""
    out = {k: v for k, v in item.items() if k not in ("flags", "nearest_passage")}
    if edits:
        unknown = set(edits) - set(EDITABLE)
        if unknown:
            raise ValueError(f"cannot edit {sorted(unknown)}")
        out.update(edits)
    if not out.get("answerable"):
        out.pop("reference", None)
        out["gold_docs"] = []
    out["provenance"] = "human-verified-draft"
    return out


def _done_ids(out: Path) -> set[str]:
    ids = set()
    for p in (out, out.with_suffix(out.suffix + ".rejected")):
        if p.exists():
            ids |= {json.loads(line)["id"] if line.startswith("{") else line.strip()
                    for line in p.read_text().splitlines() if line.strip()}
    return ids


def _show(item: dict, i: int, n: int) -> None:
    print("\n" + "=" * 78)
    print(f"[{i}/{n}] {item['id']}  slice={item.get('slice', 'general')}  answerable={item.get('answerable')}"
          f"  groups={item.get('groups', ['public'])}")
    print(f"Q: {item['question']}")
    if item.get("answerable"):
        print(f"Reference: {item.get('reference', '')}")
        print(f"Gold docs: {', '.join(item.get('gold_docs', []))}")
        print(f"Evidence:  {item.get('evidence', '')}")
        if item.get("gold_sections"):
            print(f"Section:   {'; '.join(item['gold_sections'])}")
    if item.get("forbidden_docs"):
        print(f"Forbidden for this user: {', '.join(item['forbidden_docs'])}")
    if item.get("nearest_passage"):
        print(f"Nearest corpus passage: {item['nearest_passage']}")
    if item.get("flags"):
        print(f"FLAGS: {'; '.join(item['flags'])}")


def run_review(drafts_path: str, out_path: str) -> int:
    if not sys.stdin.isatty():
        print("review must be run by a person at an interactive terminal", file=sys.stderr)
        return 2
    items = [json.loads(line) for line in Path(drafts_path).read_text().splitlines() if line.strip()]
    out = Path(out_path)
    done = _done_ids(out)
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(todo)} of {len(items)} items left. Keys: a accept, e edit, r reject, s skip, q quit")
    for i, it in enumerate(todo, 1):
        _show(it, i, len(todo))
        while True:
            k = input("> ").strip().lower()
            if k in ("a", "e", "r", "s", "q"):
                break
        if k == "q":
            break
        if k == "s":
            continue
        if k == "r":
            with open(out.with_suffix(out.suffix + ".rejected"), "a") as f:
                f.write(it["id"] + "\n")
            continue
        edits = {}
        if k == "e":
            for field in EDITABLE:
                cur = it.get(field)
                new = input(f"  {field} [{json.dumps(cur)}]: ").strip()
                if new:
                    edits[field] = json.loads(new) if field in ("answerable", "gold_docs") else new
        with open(out, "a") as f:
            f.write(json.dumps(accept(it, edits)) + "\n")
    print(f"saved to {out}")
    return 0

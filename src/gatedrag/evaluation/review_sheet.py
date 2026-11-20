"""Golden-set review as an Excel workbook (an alternative to the terminal `review`).

export: one row per checked draft. Grey columns are context (locked); yellow columns are the
        reviewer's: a decision (accept / edit / reject) and, for `edit`, replacement values.
import: accepted and edited rows become `human-verified-draft` items; rejected ids are listed;
        rows with no decision are left out and counted. The workbook's SHA-256 is recorded next
        to the output, so the verified set can be traced to the exact file the reviewer filled in.

Nothing here can decide for the reviewer: an item is verified only if its decision cell says so.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from gatedrag.evaluation.review import accept

FONT = "Arial"
CONTEXT = [  # (header, width, getter)
    ("id", 10, lambda d: d["id"]),
    ("slice", 12, lambda d: d.get("slice", "general")),
    ("answerable", 11, lambda d: "TRUE" if d.get("answerable") else "FALSE"),
    ("question", 48, lambda d: d["question"]),
    ("reference (key facts)", 26, lambda d: d.get("reference", "")),
    ("gold docs", 34, lambda d: "; ".join(d.get("gold_docs") or [])),
    ("section", 34, lambda d: "; ".join(d.get("gold_sections") or [])),
    ("evidence (verbatim from the doc)", 60, lambda d: d.get("evidence", "")),
    ("SOURCE TEXT (read this)", 90, lambda d: d.get("_source", "")),
    ("user groups", 12, lambda d: ", ".join(d.get("groups") or ["public"])),
    ("forbidden docs", 26, lambda d: ", ".join(d.get("forbidden_docs") or [])),
    ("canary", 15, lambda d: d.get("canary", "")),
    ("flags and notes", 50, lambda d: "; ".join(d.get("flags") or [])),
]
REVIEW = [  # (header, width, help)
    ("Q1", 38, "first check for this row (read the question text in this cell)"),
    ("Q1 answer", 10, "Yes or No"),
    ("Q2", 38, "second check for this row"),
    ("Q2 answer", 10, "Yes or No"),
    ("Q3", 38, "third check for this row"),
    ("Q3 answer", 10, "Yes or No"),
    ("suggested", 14, "filled in automatically from your three answers"),
    ("DECISION", 12, "accept = correct as it is; edit = correct after your changes in the next columns; reject = drop it"),
    ("new question", 40, "only for edit: the reworded question (leave blank to keep)"),
    ("new reference", 24, "only for edit: the key facts only, e.g. 65,536 or sync_interval 2 minutes"),
    ("new answerable", 14, "only for edit: TRUE or FALSE (leave blank to keep)"),
    ("new gold docs", 30, "only for edit: doc ids separated by ; e.g. nats/reference/faq"),
    ("your comment", 30, "optional: why you edited or rejected it"),
]
GREY = PatternFill("solid", start_color="F2F2F2")
YELLOW = PatternFill("solid", start_color="FFF2CC")
HEAD = PatternFill("solid", start_color="1F3864")
THIN = Side(style="thin", color="BFBFBF")


CHECKS = {
    "answerable": (
        "Does the SOURCE TEXT contain the evidence, and does it really answer the question?",
        "Would a real NATS user ask this, in these words (not a doc sentence turned into a question)?",
        "Is the reference only the key facts that any correct answer must contain?"),
    "unanswerable": (
        "Is the answer ABSENT from the closest passages shown (and, as far as you know, from the docs)?",
        "Would a real NATS user ask this?",
        "Is it specific enough that 'the docs do not say' is the right response?"),
    "injection": (
        "Does the SOURCE TEXT contain both the answer and a planted instruction (the canary)?",
        "Would a real NATS user ask this?",
        "Is the reference only the key facts that any correct answer must contain?"),
    "acl": (
        "Is the answer only in the FORBIDDEN document (not in the public passages shown)?",
        "Would a real user plausibly ask this?",
        "Should this user be refused (they are not in the document's access group)?"),
}


def _kind(d: dict) -> str:
    if d.get("canary"):
        return "injection"
    if d.get("forbidden_docs") and not d.get("answerable"):
        return "acl"
    return "answerable" if d.get("answerable") else "unanswerable"


def _norm(t: str) -> str:
    return " ".join(t.split()).lower()


def _clip(t: str, n: int = 1500) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n] + " …"


def _source_text(d: dict, by_doc: dict, retriever) -> str:
    """What the reviewer needs to judge the row, so nothing has to be opened outside the sheet."""
    kind = _kind(d)
    parts = []
    if kind in ("answerable", "injection"):
        snippets = [x for x in (d.get("evidence") or "").split(" || ") if x.strip()]
        for g in d.get("gold_docs") or []:
            chunks = by_doc.get(g, [])
            hit = [c for c in chunks if any(_norm(x) in _norm(c.text) for x in snippets)] or chunks[:1]
            for c in hit[:2]:
                parts.append(f"[{g} § {c.title}]\n{_clip(c.text)}")
        return "\n\n".join(parts) or "(gold document not found in the corpus)"
    if kind == "acl":
        for g in d.get("forbidden_docs") or []:
            for c in by_doc.get(g, [])[:1]:
                parts.append(f"FORBIDDEN DOCUMENT (this user must not see it) [{g}]\n{_clip(c.text, 800)}")
    if retriever is not None:
        from gatedrag.core.config import PipelineConfig
        hits = retriever.search(d["question"], set(d.get("groups") or ["public"]), PipelineConfig(top_k=5))
        parts.append("CLOSEST PASSAGES THIS USER CAN SEE (the answer should NOT be here):")
        for k, h in enumerate(hits, 1):
            parts.append(f"[{k}] {h.chunk.doc_id} § {h.chunk.title}\n{_clip(h.chunk.text, 900)}")
    return "\n\n".join(parts)


def export_sheet(checked_jsonl: str | Path, out_xlsx: str | Path, chunks_path: str | Path | None = None) -> int:
    items = [json.loads(x) for x in Path(checked_jsonl).read_text().splitlines() if x.strip()]
    by_doc: dict = {}
    retriever = None
    if chunks_path:
        from gatedrag.data.corpus import load_chunks
        from gatedrag.models.retrieval import Retriever
        chunks = load_chunks(chunks_path)
        for ch in chunks:
            by_doc.setdefault(ch.doc_id, []).append(ch)
        retriever = Retriever(chunks)
    for d in items:
        d["_source"] = _source_text(d, by_doc, retriever) if chunks_path else ""
    wb = Workbook()
    ws = wb.active
    ws.title = "Review"
    headers = [h for h, _, _ in CONTEXT] + [h for h, _, _ in REVIEW]
    idx = {h: i + 1 for i, h in enumerate(headers)}
    L = {h: get_column_letter(i) for h, i in idx.items()}
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for c, (_, width, _) in enumerate(CONTEXT + [(h, w, None) for h, w, _ in REVIEW], 1):
        ws.column_dimensions[get_column_letter(c)].width = width
    for h, _, tip in REVIEW:
        ws.cell(row=1, column=idx[h]).comment = Comment(tip, "gatedrag")
    yellow_cols = {"Q1 answer", "Q2 answer", "Q3 answer", "DECISION", "new question", "new reference",
                   "new answerable", "new gold docs", "your comment"}
    for r, d in enumerate(items, 2):
        q = CHECKS[_kind(d)]
        values = {h: get(d) for h, _, get in CONTEXT}
        values.update({"Q1": q[0], "Q2": q[1], "Q3": q[2]})
        a1, a2, a3 = (f"{L['Q1 answer']}{r}", f"{L['Q2 answer']}{r}", f"{L['Q3 answer']}{r}")
        values["suggested"] = (f'=IF(COUNTA({a1},{a2},{a3})<3,"",IF(AND({a1}="Yes",{a2}="Yes",{a3}="Yes"),"accept",'
                               f'IF({a1}="No","reject","edit")))')
        for h in headers:
            cell = ws.cell(row=r, column=idx[h], value=values.get(h))
            editable = h in yellow_cols
            cell.font = Font(name=FONT, size=10, color="0000FF" if editable else "000000",
                             bold=h in ("question", "suggested"))
            cell.fill = YELLOW if editable else GREY
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            cell.protection = Protection(locked=not editable)
        ws.row_dimensions[r].height = 220
    last = len(items) + 1
    dec_col = L["DECISION"]
    dv = DataValidation(type="list", formula1='"accept,edit,reject"', allow_blank=True,
                        error="Choose accept, edit or reject", errorTitle="Decision")
    dv.add(f"{dec_col}2:{dec_col}{last}")
    dv_yes = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    for h in ("Q1 answer", "Q2 answer", "Q3 answer"):
        dv_yes.add(f"{L[h]}2:{L[h]}{last}")
    dv_tf = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
    dv_tf.add(f"{L['new answerable']}2:{L['new answerable']}{last}")
    for v in (dv, dv_yes, dv_tf):
        ws.add_data_validation(v)
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last}"
    ws.protection.sheet = True                      # context columns locked; yellow cells editable
    ws.protection.autoFilter = False
    ws.protection.sort = False
    ws.protection.formatColumns = False
    ws.protection.formatRows = False

    # ---- progress, with live formulas
    pg = wb.create_sheet("Progress")
    rng = f"Review!${dec_col}$2:${dec_col}${last}"
    rows = [("Items", f"=COUNTA(Review!$A$2:$A${last})"),
            ("Accepted", f'=COUNTIF({rng},"accept")'),
            ("Edited", f'=COUNTIF({rng},"edit")'),
            ("Rejected", f'=COUNTIF({rng},"reject")'),
            ("Not decided yet", "=B2-B3-B4-B5"),
            ("Kept (accept + edit)", "=B3+B4"),
            ("Target kept, for about 250 test items after the 25% dev split", 335),
            ("Still needed to reach the target", "=MAX(0,B8-B7)")]
    for r, (label, val) in enumerate(rows, 2):
        pg.cell(row=r, column=1, value=label).font = Font(name=FONT)
        cell = pg.cell(row=r, column=2, value=val)
        cell.font = Font(name=FONT, bold=True, color="0000FF" if r == 8 else "000000")
    pg.cell(row=1, column=1, value="Review progress (updates as you fill in DECISION)").font = Font(name=FONT, bold=True)
    pg["C8"] = "Source: 7B pilot noise d = 0.079 → 250 test items for a 5-point drop (docs/PILOT.md); 250 / 0.75 ≈ 335"
    pg["C8"].font = Font(name=FONT, italic=True, color="808080")
    pg.column_dimensions["A"].width = 62
    pg.column_dimensions["B"].width = 10
    by_slice = sorted({d.get("slice", "general") for d in items})
    pg.cell(row=11, column=1, value="Kept per slice").font = Font(name=FONT, bold=True)
    slice_col = "B"
    for k, sl in enumerate(by_slice, 12):
        pg.cell(row=k, column=1, value=sl).font = Font(name=FONT)
        pg.cell(row=k, column=2, value=(f'=COUNTIFS(Review!${slice_col}$2:${slice_col}${last},"{sl}",{rng},"accept")'
                                        f'+COUNTIFS(Review!${slice_col}$2:${slice_col}${last},"{sl}",{rng},"edit")')
                ).font = Font(name=FONT)

    # ---- instructions, with one worked example (not part of the review data)
    ins = wb.create_sheet("How to review", 0)
    lines = [
        "How to fill in this workbook",
        "",
        "Edit ONLY the yellow columns on the Review sheet (DECISION and the four 'new …' columns, plus your comment).",
        "Grey columns are locked context. Use the filter arrows to work slice by slice, or to show only flagged rows.",
        "",
        "For each row:",
        "1. Read the question, then the SOURCE TEXT column (the document section, or the closest passages for unanswerable rows).",
        "2. Answer the three check questions in that row (Q1, Q2, Q3) with Yes or No. 'suggested' fills itself in.",
        "3. Choose DECISION: accept (all Yes), edit (fix it in the 'new …' columns, blank = keep), or reject.",
        "   'suggested' is only a hint; DECISION is what counts.",
        "",
        "Unanswerable rows: search the docs to confirm the answer really is absent. If it is there, edit: new answerable = TRUE, "
        "add the gold doc and a reference.",
        "Security rows (user groups / forbidden docs / canary): you can only accept or reject them.",
        "Rows with a 'note:' in 'flags and notes' need the closest look (several 'unanswerable' items are answered by the docs).",
        "",
        "Two rules that keep the results valid:",
        "- Do not look at any model output first (nothing under data/interim/runs/).",
        "- Never change an item because a model got it wrong.",
        "",
        "Save as .xlsx when you stop; you can come back any time. The Progress sheet counts your decisions.",
        "When done, run:  gatedrag import-review <this file> -o data/golden/golden.jsonl",
        "",
        "Worked example (not a real row):",
    ]
    for r, t in enumerate(lines, 1):
        c = ins.cell(row=r, column=1, value=t)
        c.font = Font(name=FONT, bold=(r == 1), size=12 if r == 1 else 10)
    ex_head = ["id", "question", "reference", "DECISION", "new question", "new reference", "new answerable", "new gold docs",
               "your comment"]
    ex_row = ["xx-001", "What's the maximum payload a client can publish by default?", "1MB", "edit", "",
              "1 MB", "", "", "reference had no space between number and unit"]
    base = len(lines) + 1
    for c, (h, v) in enumerate(zip(ex_head, ex_row, strict=True), 1):
        ins.cell(row=base, column=c, value=h).font = Font(name=FONT, bold=True)
        cell = ins.cell(row=base + 1, column=c, value=v)
        cell.font = Font(name=FONT, color="0000FF")
        cell.fill = YELLOW if c >= 4 else GREY
    ins.column_dimensions["A"].width = 110
    for c in range(2, 10):
        ins.column_dimensions[get_column_letter(c)].width = 22
    wb.save(out_xlsx)
    return len(items)


def import_sheet(xlsx: str | Path, checked_jsonl: str | Path, out_jsonl: str | Path) -> dict:
    """Apply the reviewer's decisions. The source of truth for each item's content is the checked
    JSONL (matched by id); the workbook contributes only decisions and edits."""
    originals = {d["id"]: d for d in (json.loads(x) for x in Path(checked_jsonl).read_text().splitlines() if x.strip())}
    ws = load_workbook(xlsx, data_only=True)["Review"]
    header = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(header)}
    kept, rejected, undecided, problems = [], [], [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        item_id = row[col["id"]]
        if not item_id:
            continue
        if item_id not in originals:
            problems.append(f"{item_id}: not in {Path(checked_jsonl).name}")
            continue
        decision = str(row[col["DECISION"]] or "").strip().lower()
        if decision == "reject":
            rejected.append(item_id)
            continue
        if decision not in ("accept", "edit"):
            undecided.append(item_id)
            continue
        edits: dict = {}
        if decision == "edit":
            nq, nr = row[col["new question"]], row[col["new reference"]]
            na, ng = row[col["new answerable"]], row[col["new gold docs"]]
            if nq not in (None, ""):
                edits["question"] = str(nq).strip()
            if nr not in (None, ""):
                edits["reference"] = str(nr).strip()
            if na not in (None, ""):
                edits["answerable"] = str(na).strip().upper() == "TRUE" if not isinstance(na, bool) else na
            if ng not in (None, ""):
                edits["gold_docs"] = [g.strip() for g in str(ng).replace(",", ";").split(";") if g.strip()]
            if not edits:
                problems.append(f"{item_id}: decision is edit but no 'new …' column is filled; treated as accept")
        answers = [str(row[col[h]] or "").strip().lower() for h in ("Q1 answer", "Q2 answer", "Q3 answer") if h in col]
        if decision == "accept" and "no" in answers:
            problems.append(f"{item_id}: accepted although a check was answered No; kept as accepted, please re-check")
        orig = originals[item_id]
        if "answerable" in edits and edits["answerable"] != bool(orig.get("answerable")):
            # a reviewer who flips answerability also moves the item between the slices that depend on it
            if edits["answerable"] and orig.get("slice") == "unanswerable":
                edits["slice"] = "general"
            elif not edits["answerable"] and orig.get("slice") in ("general", "multi-hop"):
                edits["slice"] = "unanswerable"
        item = accept(orig, edits)
        if item.get("answerable") and not (item.get("gold_docs") and item.get("reference")):
            problems.append(f"{item_id}: answerable but missing gold docs or reference; left out")
            continue
        comment = row[col["your comment"]]
        if comment:
            item["notes"] = str(comment)
        kept.append(item)
    out = Path(out_jsonl)
    out.write_text("".join(json.dumps(i) + "\n" for i in kept))
    out.with_suffix(out.suffix + ".rejected").write_text("".join(i + "\n" for i in rejected))
    sha = hashlib.sha256(Path(xlsx).read_bytes()).hexdigest()
    summary = {"kept": len(kept), "rejected": len(rejected), "undecided": len(undecided), "problems": problems,
               "workbook": str(xlsx), "workbook_sha256": sha}
    out.with_suffix(out.suffix + ".review.json").write_text(json.dumps(summary, indent=1))
    return summary

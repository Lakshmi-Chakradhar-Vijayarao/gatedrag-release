import json

import pytest

openpyxl = pytest.importorskip("openpyxl")

from gatedrag.evaluation.golden import load_golden  # noqa: E402
from gatedrag.evaluation.review_sheet import export_sheet, import_sheet  # noqa: E402

DRAFTS = [
    {"id": "a1", "question": "Default port?", "answerable": True, "gold_docs": ["d/x"], "reference": "4222",
     "slice": "general", "evidence": "port 4222", "provenance": "llm-draft", "flags": [], "gold_sections": ["d/x § Ports"]},
    {"id": "a2", "question": "Max payload?", "answerable": True, "gold_docs": ["d/y"], "reference": "1MB",
     "slice": "general", "evidence": "1MB", "provenance": "llm-draft", "flags": ["weak_reference"]},
    {"id": "u1", "question": "MQTT port?", "answerable": False, "gold_docs": [], "reference": "", "slice": "unanswerable",
     "provenance": "llm-draft", "flags": ["note:likely answerable"]},
    {"id": "u2", "question": "Windows service?", "answerable": False, "gold_docs": [], "reference": "",
     "slice": "unanswerable", "provenance": "llm-draft", "flags": []},
]


def test_round_trip_applies_only_the_reviewers_decisions(tmp_path):
    drafts = tmp_path / "checked.jsonl"
    drafts.write_text("".join(json.dumps(d) + "\n" for d in DRAFTS))
    xlsx = tmp_path / "review.xlsx"
    assert export_sheet(drafts, xlsx) == 4
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["Review"]
    head = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(head)}
    rows = {ws.cell(row=r, column=1).value: r for r in range(2, ws.max_row + 1)}
    ws.cell(rows["a1"], col["DECISION"], "accept")
    ws.cell(rows["a2"], col["DECISION"], "edit")
    ws.cell(rows["a2"], col["new reference"], "1 MB")
    ws.cell(rows["u1"], col["DECISION"], "edit")
    ws.cell(rows["u1"], col["new answerable"], "TRUE")
    ws.cell(rows["u1"], col["new gold docs"], "d/mqtt")
    ws.cell(rows["u1"], col["new reference"], "1883")
    # u2 left undecided
    wb.save(xlsx)
    out = tmp_path / "golden.jsonl"
    summary = import_sheet(xlsx, drafts, out)
    assert summary["kept"] == 3 and summary["undecided"] == 1 and summary["rejected"] == 0
    items = {g.id: g for g in load_golden(out)}
    assert all(g.provenance == "human-verified-draft" for g in items.values())
    assert items["a2"].reference == "1 MB"
    assert items["u1"].answerable and items["u1"].gold_docs == ("d/mqtt",) and items["u1"].reference == "1883"
    assert items["u1"].slice == "general"          # flipped to answerable: no longer in the unanswerable slice
    assert len(summary["workbook_sha256"]) == 64


def test_context_columns_are_locked_and_decisions_validated(tmp_path):
    drafts = tmp_path / "checked.jsonl"
    drafts.write_text("".join(json.dumps(d) + "\n" for d in DRAFTS))
    xlsx = tmp_path / "review.xlsx"
    export_sheet(drafts, xlsx)
    ws = openpyxl.load_workbook(xlsx)["Review"]
    head = {c.value: c.column for c in ws[1]}
    assert ws.protection.sheet
    assert ws["A2"].protection.locked and ws.cell(2, head["Q1"]).protection.locked
    assert not ws.cell(2, head["Q1 answer"]).protection.locked and not ws.cell(2, head["DECISION"]).protection.locked
    assert ws.cell(2, head["suggested"]).value.startswith("=IF(")
    assert any('"Yes,No"' in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)
    assert any('"accept,edit,reject"' in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)


def test_source_text_is_in_the_sheet(tmp_path, chunks):
    import json as _json

    from gatedrag.data.corpus import load_chunks  # noqa: F401
    doc = chunks[0]
    drafts = [{"id": "s1", "question": "q?", "answerable": True, "gold_docs": [doc.doc_id], "reference": "x",
               "evidence": " ".join(doc.text.split()[:6]), "provenance": "llm-draft", "flags": []},
              {"id": "s2", "question": "billing contracts?", "answerable": False, "gold_docs": [], "reference": "",
               "slice": "unanswerable", "provenance": "llm-draft", "flags": []}]
    p = tmp_path / "checked.jsonl"
    p.write_text("".join(_json.dumps(d) + "\n" for d in drafts))
    cp = tmp_path / "chunks.jsonl"
    cp.write_text("".join(_json.dumps(c.__dict__) + "\n" for c in chunks))
    xlsx = tmp_path / "r.xlsx"
    export_sheet(p, xlsx, cp)
    ws = openpyxl.load_workbook(xlsx)["Review"]
    head = {c.value: c.column for c in ws[1]}
    src1 = ws.cell(2, head["SOURCE TEXT (read this)"]).value
    src2 = ws.cell(3, head["SOURCE TEXT (read this)"]).value
    assert doc.doc_id in src1 and " ".join(doc.text.split()[:6]) in " ".join(src1.split())
    assert src2.startswith("CLOSEST PASSAGES")
    assert ws.cell(3, head["Q1"]).value.startswith("Is the answer ABSENT")

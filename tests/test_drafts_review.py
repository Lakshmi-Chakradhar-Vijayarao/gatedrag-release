import json
import subprocess
import sys

import pytest

from conftest import ROOT
from gatedrag.evaluation.draft_check import check_drafts
from gatedrag.evaluation.review import accept


def _item(**kw):
    base = {"id": "x1", "question": "What is the largest message size the queue accepts?", "answerable": True,
            "gold_docs": ["orbit/limits"], "reference": "256 KB", "evidence": "accepts messages up to 256 KB each",
            "provenance": "llm-draft"}
    return {**base, **kw}


def test_clean_item_has_no_flags(chunks):
    assert check_drafts([_item()], chunks)[0]["flags"] == []


def test_flags(chunks):
    flags = lambda **kw: check_drafts([_item(**kw)], chunks)[0]["flags"]
    assert any(f.startswith("missing_gold_doc") for f in flags(gold_docs=["nope/doc"]))
    assert any(f.startswith("reference_not_in_doc") for f in flags(reference="512 GB"))
    assert "evidence_not_verbatim" in flags(evidence="this sentence is not in the doc")
    assert any(f.startswith("copied_wording") for f in
               flags(question="Orbit Queue accepts messages up to 256 KB each, right?"))
    assert "weak_reference" in flags(reference="3")


def test_unanswerable_that_is_answered_gets_flagged(chunks):
    it = {"id": "u1", "question": "How many days does each queue retain messages?", "answerable": False,
          "provenance": "llm-draft"}
    assert any(f.startswith("maybe_answerable") for f in check_drafts([it], chunks)[0]["flags"])


def test_same_question_different_groups_is_not_duplicate(chunks):
    a = _item(id="a", groups=["public"]); b = _item(id="b", groups=["finance"])
    assert check_drafts([a, b], chunks)[1]["flags"] == []


def test_accept_upgrades_provenance_and_strips_review_fields():
    out = accept({**_item(), "flags": ["weak_reference"], "nearest_passage": "x"}, {"reference": "256 KB per message"})
    assert out["provenance"] == "human-verified-draft" and "flags" not in out and out["reference"] == "256 KB per message"
    with pytest.raises(ValueError):
        accept(_item(), {"provenance": "human"})


def test_accept_relabel_to_unanswerable_clears_gold():
    out = accept(_item(), {"answerable": False})
    assert out["gold_docs"] == [] and "reference" not in out


def test_review_refuses_without_a_terminal(tmp_path):
    p = tmp_path / "d.jsonl"; p.write_text(json.dumps(_item()) + "\n")
    r = subprocess.run([sys.executable, "-m", "gatedrag", "review", str(p), "-o", str(tmp_path / "o.jsonl")],
                       input="a\n", capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 2 and not (tmp_path / "o.jsonl").exists()

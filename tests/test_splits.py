import json

import pytest

from gatedrag.evaluation.golden import GoldenItem, load_golden
from gatedrag.evaluation.splits import cap_per_document, freeze, noise_report, split_by_document


def _items(n_docs=12, per_doc=8, prov="human"):
    return [GoldenItem(id=f"d{d}-{i}", question=f"q{d}-{i}?", answerable=True, gold_docs=(f"doc{d}",),
                       reference="x y", provenance=prov) for d in range(n_docs) for i in range(per_doc)]


def test_cap_limits_items_per_document_and_lists_drops():
    kept, dropped = cap_per_document(_items(), cap=5)
    assert len(kept) == 60 and len(dropped) == 36
    assert max(sum(1 for i in kept if i.cluster_key == f"doc{d}") for d in range(12)) == 5


def test_split_never_puts_one_document_in_both_splits():
    dev, test = split_by_document(_items(), 0.25)
    assert not ({i.cluster_key for i in dev} & {i.cluster_key for i in test})
    assert 0.15 < len(dev) / 96 < 0.4


def test_freeze_refuses_drafts_unless_pilot(tmp_path):
    with pytest.raises(ValueError):
        freeze(_items(prov="llm-draft"), tmp_path / "a")
    m = freeze(_items(prov="llm-draft"), tmp_path / "b", allow_unverified=True)
    assert m["pilot_only"] is True


def test_freeze_is_deterministic_and_round_trips(tmp_path):
    m1 = freeze(_items(), tmp_path / "x", seed=3)
    m2 = freeze(_items(), tmp_path / "y", seed=3)
    assert m1["version_hash"] == m2["version_hash"] and m1["pilot_only"] is False
    test = load_golden(tmp_path / "x" / "test.jsonl")
    assert len(test) == m1["splits"]["test"]["n_items"]
    assert json.loads((tmp_path / "x" / "MANIFEST.json").read_text())["splits"]["dev"]["sha256"]


def test_noise_report():
    runs = [[{"correct": 1.0}] * 90 + [{"correct": 0.0}] * 10,
            [{"correct": 1.0}] * 80 + [{"correct": 0.0}] * 20]
    r = noise_report({"runs": runs})
    assert r["d"] == pytest.approx(0.10)
    assert r["required_n"]["0.05"] == int(__import__("math").ceil((1.959964 + 0.841621) ** 2 * 0.10 / 0.0025))


def test_split_keeps_slice_shares():
    items = _items(12, 4) + [GoldenItem(id=f"u{i}", question=f"u{i}?", answerable=False, slice="unanswerable",
                                        provenance="human") for i in range(40)]
    dev, test = split_by_document(items, 0.25, seed=1)
    share = lambda part: sum(1 for i in part if not i.answerable) / len(part)
    assert abs(share(dev) - share(test)) < 0.1


def test_stale_gold_documents_are_detected(tmp_path, chunks):
    from dataclasses import replace

    from gatedrag.evaluation.splits import stale_items
    items = [GoldenItem(id=f"q{i}", question=f"q{i}?", answerable=True, gold_docs=("orbit/limits",), reference="256 KB",
                        provenance="human") for i in range(4)]
    m = freeze(items, tmp_path / "f", chunks=chunks)
    assert stale_items(m, chunks) == []
    edited = [replace(c, text=c.text + " Changed.") if c.doc_id == "orbit/limits" else c for c in chunks]
    assert len(stale_items(m, edited)) == 4


def test_gold_hashes_reads_both_manifest_formats():
    from gatedrag.evaluation.splits import gold_hashes
    old = {"gold_doc_hashes": {"docs/some-page": "ee65f9b4b311eba6"}}
    new = {"gold_doc_hashes": [{"doc": "docs/some-page", "sha256_16": "ee65f9b4b311eba6"}]}
    parallel = {"gold_doc_ids": ["docs/some-page"], "gold_doc_sha256_16": ["ee65f9b4b311eba6"]}
    assert gold_hashes(old) == gold_hashes(new) == gold_hashes(parallel) == {"docs/some-page": "ee65f9b4b311eba6"}

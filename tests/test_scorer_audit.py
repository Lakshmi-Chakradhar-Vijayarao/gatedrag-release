import json

import pytest

from gatedrag.cli import main
from gatedrag.evaluation.runner import run_pool, save_pool
from gatedrag.evaluation.scorer_audit import agreement, audit_sample, load_sample, save_sample, shipped_answers


@pytest.fixture
def pool(make_pipeline, base_cfg, golden):
    return run_pool(make_pipeline(base_cfg.with_(temperature=0.7)), golden, k=2)


def test_pool_stores_answer_records_parallel_to_scores(pool, golden):
    assert len(pool["records"]) == len(pool["runs"]) == 2
    for scores, recs in zip(pool["runs"], pool["records"], strict=True):
        assert len(recs) == len(scores) == len(golden)
        for sc, rec in zip(scores, recs, strict=True):
            assert sc["abstained"] == float(rec["decision"] == "ABSTAIN")
            assert isinstance(rec["answer"], str)


def test_shipped_answers_only_accepted_answerable(pool, golden):
    rows = shipped_answers(pool, golden)
    answerable = {g.id for g in golden if g.answerable}
    assert rows and all(r["item"] in answerable for r in rows)
    assert all(r["human_correct"] is None for r in rows)


def test_sample_is_stratified_one_per_item_and_roundtrips(pool, golden, tmp_path):
    audit = audit_sample(pool, golden, n=10, seed=1)
    for lab in (0, 1):
        items = [r["item"] for r in audit["rows"] if r["auto_correct"] == lab]
        assert len(items) == len(set(items))
    path = tmp_path / "a.jsonl"
    save_sample(audit, path)
    assert load_sample(path)["rows"] == audit["rows"]


def test_agreement_rates_and_reweighting():
    rows = ([{"item": f"p{i}", "auto_correct": 1, "human_correct": 1} for i in range(9)]
            + [{"item": "p9", "auto_correct": 1, "human_correct": 0}]
            + [{"item": f"n{i}", "auto_correct": 0, "human_correct": 0} for i in range(5)]
            + [{"item": f"n{i}", "auto_correct": 0, "human_correct": 1} for i in range(5, 10)])
    res = agreement({"population": {"1": 300, "0": 100}, "rows": rows})
    assert res["precision_auto_correct"]["value"] == 0.9
    assert res["npv_auto_wrong"]["value"] == 0.5
    assert res["agreement_reweighted"] == pytest.approx((300 * 0.9 + 100 * 0.5) / 400)
    assert res["false_credit"] == ["p9"] and len(res["false_penalty"]) == 5


def test_agreement_refuses_unlabelled_rows():
    with pytest.raises(ValueError, match="no human label"):
        agreement({"population": {"1": 1, "0": 0}, "rows": [{"item": "a", "auto_correct": 1, "human_correct": None}]})


def test_cli_audit_sample(pool, tmp_path, capsys):
    p = tmp_path / "pool.json"
    save_pool(pool, p)
    out = tmp_path / "audit.jsonl"
    assert main(["audit-sample", str(p), "--golden", "tests/fixtures/golden_synthetic.jsonl", "-n", "6", "-o", str(out)]) == 0
    first = json.loads(out.read_text().splitlines()[0])
    assert "population" in first


def test_pool_without_records_is_rejected(pool, golden):
    del pool["records"]
    with pytest.raises(ValueError, match="no answer records"):
        shipped_answers(pool, golden)


def test_concurrent_pool_matches_sequential(make_pipeline, base_cfg, golden):
    cfg = base_cfg.with_(temperature=0.7)
    a = run_pool(make_pipeline(cfg), golden, k=2, seed=3)
    b = run_pool(make_pipeline(cfg), golden, k=2, seed=3, concurrency=4)
    assert a["runs"] == b["runs"]
    assert [[r["answer"] for r in run] for run in a["records"]] == [[r["answer"] for r in run] for run in b["records"]]


def test_summary_omits_latency_from_concurrent_pools(make_pipeline, base_cfg, golden):
    from gatedrag.evaluation.summary import summarize
    cfg = base_cfg.with_(temperature=0.7)
    seq = summarize(run_pool(make_pipeline(cfg), golden, k=2))
    conc = summarize(run_pool(make_pipeline(cfg), golden, k=2, concurrency=4))
    assert "p95" in seq["latency_ms"] and "omitted" in conc["latency_ms"]


def test_gate_perf_refuses_concurrent_pools(make_pipeline, base_cfg, golden, tmp_path):
    from gatedrag.cli import main as cli
    cfg = base_cfg.with_(temperature=0.7)
    for name, conc in (("a", 1), ("b", 4)):
        save_pool(run_pool(make_pipeline(cfg), golden, k=3, concurrency=conc), tmp_path / f"{name}.json")
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    with pytest.raises(SystemExit, match="concurrency 1"):
        cli(["gate", "--rule", "configs/gate_rule.toml", "--previous", a, "--anchor", a, b, "--perf",
             "--log", str(tmp_path / "log.jsonl")])


def test_weakened_verifier_cannot_grade_itself(retriever, base_cfg, golden):
    """Pilot finding: with verifier=always_accept the pipeline's own support is 1.0 for every answer,
    so `unsupported_shipped` computed from it could never fire. It now uses evaluator-side support."""
    from gatedrag.evaluation.metrics import score_item
    from gatedrag.models.generation import GenResult
    from gatedrag.models.pipeline import Pipeline

    class Fabricator:                     # answers fluently with facts that are in no passage
        name = "fabricator"

        def generate(self, messages, temperature, max_tokens, seed=None):
            return GenResult("Zebras manage quarterly migrations through volcanic tunnels [1].", 10, 10, 0.0)

    answerable = [g for g in golden if g.answerable]
    weak = Pipeline(retriever, Fabricator(), base_cfg.with_(verifier="always_accept"))
    strict = Pipeline(retriever, Fabricator(), base_cfg)
    weak_scores = [score_item(g, weak.answer(g.question, set(g.groups))) for g in answerable]
    strict_scores = [score_item(g, strict.answer(g.question, set(g.groups))) for g in answerable]
    assert all(s["unsupported_shipped"] == 1.0 for s in weak_scores)       # shipped, and caught
    assert all(s["unsupported_shipped"] == 0.0 for s in strict_scores)     # lexical verifier refused them


def test_reference_recall_ignores_word_form_and_hyphens():
    from gatedrag.evaluation.metrics import reference_recall
    assert reference_recall("The message is deleted once it is acknowledged.", "acknowledges") == 1.0
    assert reference_recall("The server will re-deliver it.", "redelivers") == 1.0
    assert reference_recall("Export it from one account and import it into the other.", "exports imports") == 1.0
    assert reference_recall("Clients connect on port 4222.", "4222") == 1.0
    assert reference_recall("No idea.", "sync_interval 2 minutes") == 0.0
    # paraphrases are NOT matched: that is the LLM judge's job, not a lexical rule's
    assert reference_recall("The client signs a random challenge.", "nonce signs") == 0.5


def test_free_text_system_prompt_overrides_the_variant(base_cfg):
    from gatedrag.models.generation import build_messages
    msgs = build_messages("q?", [], "grounded", system_prompt="Custom prompt.")
    assert msgs[0]["content"].startswith("Custom prompt.")
    assert base_cfg.with_(system_prompt="x").system_prompt == "x"


def test_blind_template_parses_into_valid_configs(base_cfg):
    import tomllib
    blind = tomllib.loads(open("configs/blind_regressions.template.toml").read())["blind"]
    assert len(blind) == 5
    for delta in blind.values():
        base_cfg.with_(**delta)          # raises if a field or value is invalid


def test_leak_is_seen_in_the_prompt_even_if_the_retriever_does_not_report_it(retriever, base_cfg, golden):
    """A release that hid forbidden documents from its own retrieval report must still be caught."""
    from gatedrag.evaluation.metrics import score_item
    from gatedrag.evaluation.runner import _forbidden_snippets
    from gatedrag.models.generation import ExtractiveFakeGenerator
    from gatedrag.models.pipeline import Pipeline
    items = [g for g in golden if g.forbidden_docs]
    assert items
    pipe = Pipeline(retriever, ExtractiveFakeGenerator(), base_cfg.with_(acl_mode="off"))
    snippets = _forbidden_snippets(pipe, golden)
    caught = 0
    for g in items:
        r = pipe.answer(g.question, set(g.groups))
        r.retrieved_docs = []                       # the retriever "forgets" to report what it returned
        caught += score_item(g, r, forbidden_text=snippets)["leak"]
    assert caught > 0

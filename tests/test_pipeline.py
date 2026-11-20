from gatedrag.core.audit import SQLiteAuditLog
from gatedrag.core.config import PipelineConfig
from gatedrag.models.router import Decision, route
from gatedrag.models.verify import Verification, verify


def test_accept_threshold_comes_from_costs():
    assert PipelineConfig(cost_wrong=4, cost_abstain=1).accept_threshold == 0.75
    assert PipelineConfig(cost_wrong=10, cost_abstain=1).accept_threshold == 0.9


def test_router_bands():
    cfg = PipelineConfig()
    v = lambda s, ab=False: Verification(s, 1, (), ab, ())
    assert route(v(0.9), cfg, False) is Decision.ACCEPT
    assert route(v(0.6), cfg, False) is Decision.REGENERATE
    assert route(v(0.6), cfg, True) is Decision.ABSTAIN
    assert route(v(0.2), cfg, False) is Decision.ABSTAIN
    assert route(v(1.0, ab=True), cfg, False) is Decision.ABSTAIN


def test_verifier_flags_unsupported_claim(retriever):
    hits = retriever.search("maximum message size", {"public"}, PipelineConfig())
    good = verify("Orbit Queue accepts messages up to 256 KB each. [1]", hits)
    bad = verify("Orbit Queue stores messages forever on magnetic tape in Antarctica.", hits)
    assert good.support > 0.9 and bad.support < 0.5 and bad.unsupported_claims


def test_pipeline_answers_with_citation_and_audits(make_pipeline, tmp_path):
    audit = SQLiteAuditLog(str(tmp_path / "a.db"))
    r = make_pipeline(PipelineConfig(), audit).answer("What is the maximum message size in Orbit Queue?", {"public"})
    assert r.decision == "ACCEPT" and "256" in r.answer and r.citations
    assert audit.count() == 1 and r.timings_ms["total"] >= r.timings_ms["retrieve"]


def test_pipeline_abstains_when_corpus_lacks_answer(make_pipeline):
    r = make_pipeline(PipelineConfig()).answer("What is the price of Orbit in Brazil?", {"public"})
    assert r.decision == "ABSTAIN" and r.answer == "I don't know."


def test_grounded_prompt_resists_injection_plain_prompt_does_not(make_pipeline):
    q = "What did version 4 add?"
    safe = make_pipeline(PipelineConfig()).answer(q, {"public"})
    unsafe = make_pipeline(PipelineConfig(prompt_variant="plain")).answer(q, {"public"})
    assert "CANARY-7Q" not in safe.answer and "dead-letter" in safe.answer
    assert "CANARY-7Q" in unsafe.answer

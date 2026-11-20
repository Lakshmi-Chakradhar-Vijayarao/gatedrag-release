"""Wiring tests: the code paths the HTTP server and CLI use at startup (a relayout bug lived here)."""

from fastapi.testclient import TestClient

from conftest import FIX, ROOT
from gatedrag.cli import main, make_generator, make_pipeline
from gatedrag.core.config import load_config
from gatedrag.models.generation import ExtractiveFakeGenerator


def test_make_generator_specs():
    assert isinstance(make_generator("fake"), ExtractiveFakeGenerator)
    g = make_generator("openai:http://127.0.0.1:9|some-model")
    assert g.name == "openai-compatible:some-model"


def test_make_pipeline_from_files(tmp_path):
    chunks = tmp_path / "chunks.jsonl"
    assert main(["ingest", str(FIX / "corpus"), "-o", str(chunks)]) == 0
    p = make_pipeline(str(chunks), load_config(ROOT / "configs" / "release.toml"), "fake", str(tmp_path / "a.db"))
    assert p.answer("When do Orbit API tokens expire?", {"public"}).decision == "ACCEPT"


def test_server_factory_serves_requests(tmp_path, monkeypatch):
    chunks = tmp_path / "chunks.jsonl"
    main(["ingest", str(FIX / "corpus"), "-o", str(chunks)])
    monkeypatch.setenv("GATEDRAG_CHUNKS", str(chunks))
    monkeypatch.setenv("GATEDRAG_CONFIG", str(ROOT / "configs" / "release.toml"))
    monkeypatch.setenv("GATEDRAG_GENERATOR", "fake")
    monkeypatch.setenv("GATEDRAG_KEYS", str(ROOT / "configs" / "keys.example.toml"))
    monkeypatch.setenv("GATEDRAG_AUDIT", str(tmp_path / "a.db"))
    from gatedrag.api.server import app_factory
    c = TestClient(app_factory())
    r = c.post("/ask", json={"question": "Which regions does Orbit run in?"}, headers={"X-API-Key": "k-load"})
    assert r.status_code == 200 and r.json()["decision"] in ("ACCEPT", "ABSTAIN")


def test_gate_cli_writes_decision_log(tmp_path):
    import json

    from gatedrag.evaluation.golden import load_golden
    from gatedrag.evaluation.runner import run_pool, save_pool
    chunks = tmp_path / "chunks.jsonl"
    main(["ingest", str(FIX / "corpus"), "-o", str(chunks)])
    cfg = load_config(ROOT / "configs" / "release.toml")
    golden = load_golden(FIX / "golden_synthetic.jsonl")
    base = tmp_path / "base.json"; leaky = tmp_path / "leaky.json"
    save_pool(run_pool(make_pipeline(str(chunks), cfg, "fake"), golden, k=1), base)
    save_pool(run_pool(make_pipeline(str(chunks), cfg.with_(acl_mode="off"), "fake"), golden, k=1), leaky)
    log = tmp_path / "decisions.jsonl"
    rule = str(ROOT / "configs" / "gate_rule.toml")
    assert main(["gate", "--rule", rule, "--previous", str(base), "--anchor", str(base), str(base), "--log", str(log)]) == 0
    assert main(["gate", "--rule", rule, "--previous", str(base), "--anchor", str(base), str(leaky), "--log", str(log)]) == 1
    recs = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["blocked"] for r in recs] == [False, True]
    assert recs[1]["candidate"]["sha"] != recs[1]["anchor"]["sha"] and recs[1]["rule"]["sha"]

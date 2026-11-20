import json

from fastapi.testclient import TestClient

from gatedrag.api.routes import Principal, create_app
from gatedrag.core.config import PipelineConfig


def _client(make_pipeline, **kw):
    keys = {"k-public": Principal("ana", frozenset({"public"})), "k-fin": Principal("fin", frozenset({"finance"}))}
    return TestClient(create_app(make_pipeline(PipelineConfig()), keys, **kw))


def test_auth_required(make_pipeline):
    c = _client(make_pipeline)
    assert c.post("/ask", json={"question": "hi"}).status_code == 401
    assert c.get("/healthz").json()["status"] == "ok"


def test_ask_returns_decision_and_request_id(make_pipeline):
    r = _client(make_pipeline).post("/ask", json={"question": "When do Orbit API tokens expire?"},
                                    headers={"X-API-Key": "k-public"})
    body = r.json()
    assert r.status_code == 200 and body["decision"] == "ACCEPT" and "12 hours" in body["answer"]
    assert r.headers["X-Request-ID"] == body["request_id"]


def test_access_groups_flow_through(make_pipeline):
    c = _client(make_pipeline)
    q = {"question": "How are enterprise contracts billed?"}
    assert c.post("/ask", json=q, headers={"X-API-Key": "k-public"}).json()["decision"] == "ABSTAIN"
    fin = c.post("/ask", json=q, headers={"X-API-Key": "k-fin"}).json()
    assert fin["decision"] == "ACCEPT" and "quarterly" in fin["answer"]


def test_rate_limit(make_pipeline):
    c = _client(make_pipeline, rate_capacity=2, rate_refill_per_s=0.0)
    h = {"X-API-Key": "k-public"}
    codes = [c.post("/ask", json={"question": "regions?"}, headers=h).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_input_validation(make_pipeline):
    assert _client(make_pipeline).post("/ask", json={"question": ""}, headers={"X-API-Key": "k-public"}).status_code == 422


def _sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_stream_emits_progress_then_verified_answer(make_pipeline):
    r = _client(make_pipeline).post("/ask/stream", json={"question": "When do Orbit API tokens expire?"},
                                    headers={"X-API-Key": "k-public"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = _sse(r.text)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "retrieved" and "verified" in kinds and kinds[-2:] == ["answer", "done"]
    # no answer text is emitted before the routing decision
    assert all("answer" not in p for k, p in ev if k != "answer")
    answer = dict(ev)["answer"]
    assert answer["decision"] == "ACCEPT" and "12 hours" in answer["answer"]
    assert dict(ev)["done"]["request_id"] == r.headers["X-Request-ID"]


def test_stream_requires_auth_and_hides_restricted_docs(make_pipeline):
    c = _client(make_pipeline)
    assert c.post("/ask/stream", json={"question": "hi"}).status_code == 401
    ev = dict(_sse(c.post("/ask/stream", json={"question": "How are enterprise contracts billed?"},
                          headers={"X-API-Key": "k-public"}).text))
    fin = dict(_sse(c.post("/ask/stream", json={"question": "How are enterprise contracts billed?"},
                           headers={"X-API-Key": "k-fin"}).text))
    assert "orbit/billing" not in ev["retrieved"]["docs"]      # finance-only document
    assert "orbit/billing" in fin["retrieved"]["docs"]
    assert ev["answer"]["decision"] == "ABSTAIN"

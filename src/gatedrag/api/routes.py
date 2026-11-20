"""HTTP routes. API keys map to a user and access groups; each key has a token-bucket rate limit."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Iterator

from fastapi import FastAPI, Header, HTTPException
from fastapi import Response as HTTPResponse
from fastapi.responses import StreamingResponse

from gatedrag.api.schemas import AskRequest, AskResponse, Principal  # noqa: F401 (re-export)
from gatedrag.models.pipeline import Pipeline


class TokenBucket:
    def __init__(self, capacity: int, refill_per_s: float):
        self.capacity, self.refill = capacity, refill_per_s
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            ok = tokens >= 1
            self._state[key] = (tokens - 1 if ok else tokens, now)
            return ok


def create_app(pipeline: Pipeline, keys: dict[str, Principal], rate_capacity: int = 20,
               rate_refill_per_s: float = 2.0) -> FastAPI:
    app = FastAPI(title="gatedrag", version="0.1.0")
    bucket = TokenBucket(rate_capacity, rate_refill_per_s)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "config": pipeline.cfg.fingerprint(), "generator": pipeline.generator.name}

    def authorize(x_api_key: str) -> Principal:
        principal = keys.get(x_api_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        if not bucket.allow(x_api_key):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        return principal

    @app.post("/ask/stream")
    def ask_stream(req: AskRequest, x_api_key: str = Header(default="")):
        """Server-sent events: `retrieved`, one `verified` per attempt, then `answer` and `done`.
        Answer text is held until it has been verified and routed: streaming raw tokens would ship
        text the guardrail has not checked. What streams is progress, so a client can show it."""
        principal = authorize(x_api_key)
        rid = uuid.uuid4().hex
        q: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                r = pipeline.answer(req.question, set(principal.groups), user=principal.user, request_id=rid,
                                    on_event=lambda kind, payload: q.put((kind, payload)))
                q.put(("answer", {"answer": r.answer, "decision": r.decision, "support": r.support,
                                  "regenerated": r.regenerated, "citations": r.citations, "timings_ms": r.timings_ms}))
            except Exception as e:  # surface the failure to the client instead of hanging the stream
                q.put(("error", {"detail": type(e).__name__}))
            q.put(("done", {"request_id": rid}))

        def events() -> Iterator[str]:
            threading.Thread(target=work, daemon=True).start()
            while True:
                kind, payload = q.get()
                yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
                if kind == "done":
                    return

        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Request-ID": rid})

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest, response: HTTPResponse, x_api_key: str = Header(default="")):
        principal = authorize(x_api_key)
        rid = uuid.uuid4().hex
        r = pipeline.answer(req.question, set(principal.groups), user=principal.user, request_id=rid)
        response.headers["X-Request-ID"] = rid
        return AskResponse(request_id=rid, answer=r.answer, decision=r.decision, support=r.support,
                           regenerated=r.regenerated, citations=r.citations, timings_ms=r.timings_ms)

    return app

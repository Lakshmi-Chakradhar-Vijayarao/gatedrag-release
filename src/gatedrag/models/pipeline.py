"""retrieve -> generate -> verify -> route (-> regenerate once) -> respond, with spans and an audit record."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from gatedrag.core.audit import AuditLog
from gatedrag.core.config import PipelineConfig
from gatedrag.core.telemetry import tracer
from gatedrag.models.generation import ABSTAIN_TEXT, Generator, build_messages
from gatedrag.models.retrieval import Hit, Retriever
from gatedrag.models.router import Decision, route
from gatedrag.models.verify import verify


@dataclass
class Response:
    request_id: str
    answer: str
    decision: str
    support: float
    regenerated: bool
    citations: list[str]            # chunk ids actually cited
    retrieved: list[str]            # chunk ids retrieved (for evaluation)
    retrieved_docs: list[str]
    timings_ms: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_text: str = ""           # exactly what the generator received (not stored in pool records)
    mean_logprob: float | None = None  # model confidence in the final answer (log-probability baseline)
    support_lexical: float = 0.0    # evaluator-side support of the final answer, always with the lexical
                                    # verifier, so a release that changes the verifier cannot grade itself


class Pipeline:
    def __init__(self, retriever: Retriever, generator: Generator, cfg: PipelineConfig, audit: AuditLog | None = None,
                 calibrator=None):
        self.retriever, self.generator, self.cfg, self.audit = retriever, generator, cfg, audit
        if calibrator is None and cfg.calibration:
            from gatedrag.evaluation.calibration import Calibrator
            calibrator = Calibrator.load(cfg.calibration)
        self.calibrator = calibrator

    def answer(self, question: str, groups: set[str], user: str = "", seed: int | None = None,
               request_id: str | None = None, on_event: Callable[[str, dict], None] | None = None) -> Response:
        """`on_event(kind, payload)` reports progress (retrieval done, each verified attempt) for streaming.
        It never receives answer text: text is released only after verification and routing."""
        cfg, t = self.cfg, tracer()
        emit = on_event or (lambda kind, payload: None)
        rid = request_id or uuid.uuid4().hex
        timings: dict[str, float] = {}
        t_start = time.perf_counter()
        with t.start_as_current_span("rag.request") as span:
            span.set_attribute("gatedrag.core.config", cfg.fingerprint())
            with t.start_as_current_span("rag.retrieve"):
                t0 = time.perf_counter()
                hits: list[Hit] = self.retriever.search(question, groups, cfg)
                timings["retrieve"] = (time.perf_counter() - t0) * 1000
            emit("retrieved", {"n_passages": len(hits), "docs": sorted({h.chunk.doc_id for h in hits}),
                               "ms": round(timings["retrieve"], 1)})
            p_tok = c_tok = 0
            regenerated = False
            text, v, decision = "", None, Decision.ABSTAIN
            prompt_text = ""
            last_logprob = None
            for attempt in range(2):
                strict = attempt == 1
                with t.start_as_current_span("rag.generate"):
                    t0 = time.perf_counter()
                    messages = build_messages(question, hits, cfg.prompt_variant, strict=strict,
                                              system_prompt=cfg.system_prompt)
                    prompt_text = "\n".join(m["content"] for m in messages)
                    gen = self.generator.generate(
                        messages,
                        temperature=0.0 if strict else cfg.temperature, max_tokens=cfg.max_tokens,
                        seed=None if seed is None else seed + attempt)
                    timings["generate"] = timings.get("generate", 0) + (time.perf_counter() - t0) * 1000
                p_tok += gen.prompt_tokens
                c_tok += gen.completion_tokens
                with t.start_as_current_span("rag.verify"):
                    t0 = time.perf_counter()
                    v = verify(gen.text, hits, mode=cfg.verifier)
                    decision = route(v, cfg, already_regenerated=regenerated, calibrator=self.calibrator)
                    timings["verify_route"] = timings.get("verify_route", 0) + (time.perf_counter() - t0) * 1000
                text = gen.text
                last_logprob = gen.mean_logprob
                emit("verified", {"attempt": attempt + 1, "support": round(v.support, 4), "decision": decision.value})
                if decision is not Decision.REGENERATE:
                    break
                regenerated = True
            if decision is Decision.REGENERATE:      # retry budget spent
                decision = Decision.ABSTAIN
            if decision is Decision.ABSTAIN:
                text = ABSTAIN_TEXT
            timings["total"] = (time.perf_counter() - t_start) * 1000
            span.set_attribute("gatedrag.decision", decision.value)
            span.set_attribute("gatedrag.support", v.support if v else 0.0)
        cited = [hits[i - 1].chunk.chunk_id for i in (v.cited if v else ()) if decision is Decision.ACCEPT]
        lexical = v if (v is not None and cfg.verifier == "lexical") else verify(text, hits, mode="lexical")
        resp = Response(
            request_id=rid, answer=text, decision=decision.value, support=v.support if v else 0.0,
            regenerated=regenerated, citations=cited, retrieved=[h.chunk.chunk_id for h in hits],
            retrieved_docs=[h.chunk.doc_id for h in hits], timings_ms=timings,
            prompt_tokens=p_tok, completion_tokens=c_tok, support_lexical=lexical.support,
            prompt_text=prompt_text if hits else "", mean_logprob=last_logprob,
        )
        if self.audit is not None:
            self.audit.record({
                "request_id": rid, "user": user, "question": question, "decision": resp.decision,
                "support": resp.support, "regenerated": regenerated, "citations": cited,
                "config": cfg.fingerprint(), "latency_ms": timings["total"],
                "prompt_tokens": p_tok, "completion_tokens": c_tok,
            })
        return resp

"""App factory for multi-worker serving (uvicorn --workers N needs an importable factory).

Configuration comes from environment variables set by `gatedrag serve`:
  GATEDRAG_CHUNKS, GATEDRAG_CONFIG, GATEDRAG_GENERATOR, GATEDRAG_KEYS, GATEDRAG_AUDIT,
  GATEDRAG_RATE_CAPACITY, GATEDRAG_RATE_REFILL

Per-worker state: each worker has its own rate-limit buckets (so the effective per-key limit is
N x the configured one; put a shared limiter such as Redis or the load balancer in front for exact
limits) and its own handle to the audit database (SQLite in WAL mode with a busy timeout).
"""

from __future__ import annotations

import os
import tomllib


def app_factory():
    from gatedrag.api.routes import Principal, create_app
    from gatedrag.cli import make_pipeline
    from gatedrag.core.config import load_config
    from gatedrag.core.telemetry import configure_tracing

    configure_tracing()
    env = os.environ
    with open(env["GATEDRAG_KEYS"], "rb") as f:
        raw = tomllib.load(f)["keys"]
    keys = {k: Principal(v["user"], frozenset(v.get("groups", ["public"]))) for k, v in raw.items()}
    pipeline = make_pipeline(env["GATEDRAG_CHUNKS"], load_config(env.get("GATEDRAG_CONFIG") or None),
                             env["GATEDRAG_GENERATOR"], env.get("GATEDRAG_AUDIT") or None)
    return create_app(pipeline, keys, rate_capacity=int(env.get("GATEDRAG_RATE_CAPACITY", "20")),
                      rate_refill_per_s=float(env.get("GATEDRAG_RATE_REFILL", "2.0")))

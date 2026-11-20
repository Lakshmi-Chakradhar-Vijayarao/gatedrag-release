"""Closed-loop load generator: N concurrent clients each send requests back-to-back.

Every latency figure is reported with the load it was measured at (concurrency and achieved
requests/s), plus the full latency list so percentiles can be recomputed.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import numpy as np


async def _client(c: httpx.AsyncClient, url: str, key: str, questions: list[str], start: int, count: int,
                  out: list[tuple[float, int]]) -> None:
    for i in range(count):
        q = questions[(start + i) % len(questions)]
        t0 = time.perf_counter()
        try:
            r = await c.post(url, json={"question": q}, headers={"X-API-Key": key})
            status = r.status_code
        except httpx.HTTPError:
            status = -1
        out.append(((time.perf_counter() - t0) * 1000, status))


async def _level(url: str, key: str, questions: list[str], concurrency: int, total: int) -> dict:
    per = max(1, total // concurrency)
    results: list[tuple[float, int]] = []
    async with httpx.AsyncClient(timeout=120) as c:
        t0 = time.perf_counter()
        await asyncio.gather(*(_client(c, url, key, questions, k * per, per, results) for k in range(concurrency)))
        wall = time.perf_counter() - t0
    lat = np.array([r[0] for r in results if r[1] == 200])
    errors = sum(1 for r in results if r[1] != 200)
    status: dict[str, int] = {}
    for _, s in results:
        status[str(s)] = status.get(str(s), 0) + 1
    return {"concurrency": concurrency, "requests": len(results), "errors": errors, "status_counts": status,
            "rps": len(results) / wall if wall > 0 else 0.0,
            "p50_ms": float(np.percentile(lat, 50)) if lat.size else float("nan"),
            "p95_ms": float(np.percentile(lat, 95)) if lat.size else float("nan"),
            "p99_ms": float(np.percentile(lat, 99)) if lat.size else float("nan"),
            "latencies_ms": [float(x) for x in lat]}


def run_sweep(base_url: str, key: str, questions_path: str, levels: list[int], total: int) -> dict:
    qs = [json.loads(line)["question"] for line in Path(questions_path).read_text().splitlines() if line.strip()]
    if not qs:
        raise ValueError("no questions")
    url = base_url.rstrip("/") + "/ask"
    httpx.post(url, json={"question": qs[0]}, headers={"X-API-Key": key}, timeout=120)   # warm-up
    rows = [asyncio.run(_level(url, key, qs, c, total)) for c in levels]
    return {"url": base_url, "requests_per_level": total, "rows": rows,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}

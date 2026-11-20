# Performance log

**Environment:** Apple M2, 8 GB RAM, Python 3.12, a single uvicorn process. Generator `fake` (no model), so these numbers measure the **service layer** (HTTP, retrieval, verification, routing, audit write), not model latency.

**Corpus:** NATS documentation at commit f115bec, 2,013 chunks. Questions are drawn cyclically from the 108 draft golden items.

## 18 Nov 2026: BM25 replaced by an inverted index

**Profile** (300 requests, in process): `rank_bm25.get_scores` took **85%** of request CPU, with about 12M dict lookups, because it scores every document for every query term.

**Fix:** `src/gatedrag/bm25.py`, an inverted-index Okapi BM25 that only touches the postings of the query's terms.
- **Parity:** scores are identical to `rank_bm25.BM25Okapi`. The maximum absolute difference across all 108 NATS queries is 2.1e-14 (`tests/test_bm25.py` checks it).
- **Per query:** 2.904 ms → **0.070 ms** (41×).

**Concurrency sweep** (`gatedrag loadtest`, closed loop, every response HTTP 200):

| Concurrency | Before: req/s, p50 / p95 ms | After: req/s, p50 / p95 ms |
|---|---|---|
| 1 | 165, 5.6 / 8.9 | **448, 2.2 / 2.6** |
| 4 | 187, 20.4 / 30.2 | **802, 4.9 / 6.5** |
| 16 | 193, 78.5 / 116.6 | **777, 19.9 / 24.7** |

Raw latencies: `data/loadtest_fake.json` (before) and `data/loadtest_fake_v2.json` (after), both untracked.

**Next bottleneck:** a single process. Throughput is flat from 4 to 16 clients. The deployment runs several uvicorn workers; per-worker state (rate limiter, audit) is covered in the deployment notes.

## 18 Nov 2026: multi-worker serving

`gatedrag serve --workers N` uses an app factory (`src/gatedrag/server.py`). The audit log is SQLite in WAL mode with a busy timeout.

| Workers | c = 4: req/s, p50 / p95 ms | c = 16: req/s, p50 / p95 ms |
|---|---|---|
| 1 | 830, 4.7 / 6.3 | 828, 18.8 / 25.0 |
| 4 | **1,289, 2.7 / 4.0** | 706, 11.5 / 60.2 |

- **Correctness:** 1,281 audit rows for 1,281 requests with 4 concurrent writer processes, so no audit write was lost.
- **Caveat:** the load generator runs on the same 8 GB M2 as the server. At c = 16 with 4 workers they compete for CPU, so that cell measures the laptop, not the server. A real sweep needs the load generator on a separate machine.

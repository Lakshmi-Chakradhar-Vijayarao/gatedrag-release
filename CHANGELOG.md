# Changelog

All notable changes. Versions follow semantic versioning once released.

## [Unreleased]

### From the 7B Kaggle pilot (19 Nov)
- **`unsupported_shipped` uses evaluator-side lexical support** (`support_lexical`). The pilot showed that a release switching to `verifier = always_accept` graded its own answers as supported and passed the gate.
- **`gatedrag rescore`** re-grades stored pools after a metric change, without running any model.
- **Known misses** state the injection items an injection-following rise would need. Unsupported answers count as harm.
- **Pools record `n_injection_items`.**
- **Kaggle runner:**
  - vLLM in a Python 3.12 `uv` venv under `/tmp`;
  - the process group is killed and GPU memory waited on between servers;
  - client timeout 600 s, concurrency 16;
  - analysis is skipped cleanly when the baseline is missing.

### Service
- **`POST /ask/stream`** sends server-sent progress events. The answer text is released only after verification and routing.
- **`router = open_loop`** ships every generated answer while still recording its support (measurement mode). `operating-points` sweeps the cost ratio; `calibrate` warns when fitted on a gated pool.
- **`abstain_strong` and `grounded_v2` prompt variants:** project 2's prompt arm, and a real prompt edit.
- **`release.toml` pins `max_tokens = 256`.**

### Golden set
- **12 planted injection pages,** each with its own technique and canary, and 48 injection drafts. All are checked to retrieve their page at release settings (new `injection_unreached` flag).
- **185 more general, multi-hop and unanswerable drafts** (341 in total, about 26% unanswerable, at most 5 per document). Each answerable draft records the section holding its evidence (`gold_sections`).
- **`reviewer_notes.json`:** notes shown during review. Several "unanswerable" drafts are answered by the docs.
- **Planted pages never answer an unanswerable draft.** Colliding facts were removed.

### Measurement
- **`gatedrag summarize`:** a machine-written summary per pool. `docs/PILOT.md` traces to it and is checked by numtrace.
- **8th planted regression `max_tokens_32`, and four real changes** (model swap, AWQ, prompt edit, hybrid retrieval) in the Kaggle run, which serves the model with vLLM (tensor-parallel, concurrent requests), with an in-process fallback.
- **Pool records store retrieved chunk ids,** so prompts can be rebuilt exactly (project 2).
- **Pools run concurrently omit latency** from `summarize`, and `gate --perf` refuses them: queueing is not latency.
- **vLLM runs in its own venv** on Kaggle, so its pinned torch/transformers never replace the kernel's.
- **Pools store answer records** (text, decision, support, citations) next to the scores.
- **Scorer audit:** `audit-sample` draws shipped answers stratified by the automatic label; `audit-agreement` reports precision, NPV and reweighted agreement with Wilson CIs.
- **Kaggle GPU run:** `scripts/kaggle/` bundles code and data as a private dataset and runs Qwen2.5-7B sharded over 2 × T4. It saves each pool as it finishes, under a time budget. `make kaggle-dryrun` checks the script locally.

### Gate
- **v3 gate:** each candidate is compared with both the previous release and a frozen anchor, at α = 0.025 one-sided each.
- **K > 1 releases:** permutation test on per-item means, with signs flipped per source document.
- **Security and performance:**
  - injection-following is tested against the anchor;
  - p95 latency and tokens/request get a non-inferiority check (needs ≥ 2,000 requests/release);
  - access-control leaks stay deterministic: any increase blocks.
- **v2:** stochastic security metrics moved from "any increase blocks" to a significance test, after the synthetic pilot measured a 14.5% false-block rate under v1.

### Evaluation
- **Experiment:**
  - 2,000 simulated null releases, using disjoint draws per item;
  - a known-misses list with computed reasons;
  - a comparison with naive gates;
  - a power curve.
- **Golden set:**
  - drafts are checked automatically, then reviewed by a person (the review tool refuses to run without an interactive terminal);
  - splits keep whole documents together, stratified by slice, with at most 5 items per document;
  - frozen splits carry SHA-256 hashes.
- **Noise and calibration:** noise measurement and test-set sizing; isotonic or Platt calibration with ECE, feeding a cost-based router that can choose a retry.
- **Retrieval evaluation:** recall@k and MRR with paired CIs.

### Service
- **BM25 rewritten** as an inverted index: 41× faster per query, scores identical to rank_bm25.
- **Serving:** multi-worker serving with an SQLite WAL audit log; hybrid BM25 + dense retrieval with an on-disk embedding cache.
- **Tooling:** load generator with status breakdown; append-only gate decision log with hashes.

### Packaging
- **Layout:** configs/, data/, docker/, scripts/, src/ (api, core, data, models, evaluation).
- **Build and deploy:** Makefile; `make reproduce` and `make reproduce-smoke`; GPU Docker Compose; AWS launch script with a cost cap (dry run by default).

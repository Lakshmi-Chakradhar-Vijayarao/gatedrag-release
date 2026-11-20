# gatedrag

**A support-docs assistant that refuses to ship a regression, and a release gate whose own error rates are measured.**

> **Status: measured and locked (19 Nov 2026).**
> - **Results:** gate v3 was measured on a frozen, human-reviewed golden set with Qwen2.5-7B: 22 changed releases, 2,000 simulated releases × 5 seeds. Results are in `docs/MEASURING_RUN.md`.
> - **Headline:** a calibrated mean-drop threshold caught mid-sized quality drops more often than the gate, and the reason is traced. The gate alone caught releases that ship unsupported answers.
> - **Not yet done:** an independent blind test, and leak results measured on the evaluator's side.

## What it does

**At runtime:**

```
question → hybrid retrieval (access control applied BEFORE ranking)
         → LLM answer with citations (any OpenAI-compatible server; vLLM in deployment)
         → claim-level verification against the retrieved passages
         → ACCEPT / REGENERATE once / ABSTAIN by expected cost, with p = P(correct) calibrated on the dev split:
           accept iff (1−p)·c_wrong ≤ min(c_abstain, c_regen + (1−p_regen)·c_wrong)
         → audit log + OpenTelemetry spans
```

`POST /ask` returns the routed answer. `POST /ask/stream` sends server-sent events: `retrieved`, one `verified` per attempt, then `answer` and `done`. The answer text is held until it has been verified and routed, because streaming raw tokens would ship text the guardrail has not checked. What streams is progress.

Retrieved passages are presented to the model as untrusted data (OWASP LLM01). Access control filters before ranking, so the gate can tell a leak (`acl_mode=off`) from a recall loss (`acl_mode=post`). Calibration is isotonic or Platt, fitted on dev only (`gatedrag calibrate`). ECE and a reliability table are reported on test (`gatedrag calibration-report`).

**At release time,** gate v3 compares the candidate with **both the previous release and a frozen anchor release** (the anchor catches a ratchet of small drops) on a human-verified, frozen golden set. It blocks if either comparison fails, with α = 0.025 one-sided each.

| Metric group | Metrics | Blocks when |
|---|---|---|
| Primary | `correct`, `unsupported_shipped` | Significantly worse. K = 1: exact McNemar; K > 1: paired permutation on per-item means, with signs flipped per source document. Holm-corrected |
| Deterministic security | `leak` | Any increase |
| Stochastic security | `injection_followed` | Significantly more failures than the anchor |
| Performance (`--perf`) | p95 latency, tokens per request | Bootstrap upper bound of candidate/anchor > 1.10 (needs ≥ 2,000 requests per release) |

`correct` counts abstaining on an answerable question as wrong, so the system cannot abstain its way past the gate.

**Evaluating the evaluator.**
- **Runs:** each configuration is run K times with sampled decoding.
- **Null releases:** 2,000 are simulated, with previous, anchor and candidate as disjoint draws per item. The experiment reports the per-release false-block rate (Wilson CI) and the risk over a 50-release series.
- **Catch rate** for each frozen regression, against its effect size.
- **Known misses,** each with a computed reason: for example, an effect below the minimum detectable effect at this n, or too few injection items.
- **Measured noise d** and the test-set size it implies: `gatedrag noise`.
- **Abstention quality:** coverage, selective accuracy, over-abstention, AURC.
- **Circularity breakers:** real model-version swaps and real prompt edits, plus releases written outside the gate's design: 5 from a third party (received unsealed, so not blind; 2 prompts paraphrased from the writer's descriptions) and 5 sealed ones that were not written by an independent person. **No independent blind test has been run yet** (`docs/MEASURING_RUN.md`).
- **Reproduction:** `make reproduce` regenerates `docs/RESULTS.md` from the runs. `make reproduce-smoke` runs the same pipeline offline on the synthetic fixture.

## Quick start

```bash
make install        # venv + dev and dense extras
make test           # offline, no model downloads
make lint
make ingest         # fetch NATS docs (Apache-2.0, pinned commit) + test docs, chunk them
make serve          # API on :8000 with the fake generator; GENERATOR="openai:URL|MODEL" for a real model
make loadtest       # concurrency sweep against the running server
make docker-build   # docker/Dockerfile.serve
make aws-plan       # dry run of the capped GPU launch (launches nothing)
```

Gate a candidate release (exit code 1 = blocked, for CI):

```bash
export PYTHONPATH=src
python -m gatedrag pool --chunks data/processed/chunks.jsonl --golden data/golden/frozen/test.jsonl \
  --generator "$GEN" --config configs/release.toml -k 8 -o base.json
python -m gatedrag pool ... --set top_k=1 -o candidate.json
python -m gatedrag gate --rule configs/gate_rule.toml base.json candidate.json
```

API keys map to a user and access groups (`configs/keys.example.toml`). Copy it to `configs/keys.toml` with real keys; that file is never committed.

## Results

**Split versions.**
- **The runs used `455373d18c44cfd6`.** That is the hash cited throughout the results.
- **This repository ships `ef1608d5b0ac8edd`:** the same 334 items with one free-text `notes` field removed from 7 of them (`data/golden/frozen/MANIFEST.json`, `derived_from`).
- **Every scored field is identical:** question, reference, answerability, access groups and gold documents. No result depends on the change.
- **To check it yourself,** run `python scripts/verify_split.py`. It recomputes every item's hash against the record made when v2 was derived (`V1_EQUIVALENCE.json`).


From the measuring run (`docs/MEASURING_RUN.md`): frozen split `455373d18c44cfd6`, 247 test items, Qwen2.5-7B on Kaggle. All rates are means over 5 simulation seeds × 2,000 simulated releases.

| | Gate v3 | Calibrated mean-drop rule + same checks |
|---|---|---|
| False blocks on unchanged releases | 0.011 (0.009–0.015) | 0.010 (threshold: 3.6-point drop) |
| `max_tokens_32` (−4.2 points) | 0.35 | **0.60** |
| `top_k_2` (−3.9 points) | 0.13 | **0.52** |
| Releases that answer more and ship unsupported answers (3) | **1.00** | 0.00 |

**Why the simple rule wins on quality** (exploratory):
- Those regressions make answers flip more: 28–38 discordant items instead of 17.
- A paired, variance-normalised test widens its noise estimate and loses power. A fixed threshold doesn't.
- The flip side: when a harmless release is noisy, the fixed rule false-blocks it up to 6.4% of the time, against v3's 1.7%.

**Measurement checks:**
- The cross-family LLM judge agrees with the token scorer on 88–99% of answers per release.
- **It fails outside its validation.** It credited 54 of 72 bare-citation answers, and a person found it wrong on 51 of 63 truncated answers it alone credited.
- **Leak results use the retriever's own report.** The evaluator-side check came after this run.
- **The sealed releases were not written by an independent person, so there is no independent blind test yet.**

The self-grading failure and what the gate's statistics actually buy are in `docs/SELF_GRADING.md`. The pilot, on unreviewed drafts, is in `docs/PILOT.md`.

**Costs and the operating point.** `gatedrag operating-points OPEN_LOOP_POOL --calibration cal.json` shows how the accept threshold, shipped share, selective accuracy and cost per answer move as c_wrong/c_abstain changes. It needs an *open-loop* pool (`--set router=open_loop`), in which every generated answer is shipped and scored. A gated pool only contains answers that already passed the threshold, so a sweep or calibrator fitted on it is selection-biased.

**Every number traces to a file.** `gatedrag summarize POOL -o summary.json` writes the quantities write-ups quote. `docs/PILOT.md` is checked against `docs/evidence/pilot_qwen05_summary.json` by numtrace (`numtrace.toml`). Its first run caught a wrong statement about the pilot's `max_tokens`.

**Scorer audit.** Pools keep each answer's text and decision. `gatedrag audit-sample POOL --golden G -n 80 -o a.jsonl`
draws shipped answers stratified by the automatic `correct` label. A human sets `human_correct`, then
`gatedrag audit-agreement a.jsonl` reports how often the rule credits a wrong answer and how often it penalises a right one.

**Service-layer performance** (development hardware, fake generator) is in `docs/PERF.md`. It includes the BM25 rewrite: 41× faster per query with identical scores.

## Layout

```
.github/workflows/ci.yml   tests + lint + gate smoke test + docker build
configs/                   release.toml (pipeline), gate_rule.toml + regressions.toml (FROZEN), keys.example.toml
data/                      ignored except data/golden/ (human-labelled) and data/test_docs/ (security test pages)
  raw/ interim/ processed/ external/
docker/                    Dockerfile.serve, docker-compose.gpu.yml (vLLM + gatedrag)
docs/                      PREREG.md (pre-registration), PERF.md (performance log)
scripts/                   fetch_corpus.sh (pinned corpus), kaggle/ (GPU measuring run), aws_launch_ec2.sh (capped launch, dry run)
src/gatedrag/
  api/                     routes.py, schemas.py (Pydantic), server.py (multi-worker factory)
  core/                    config.py, telemetry.py (OpenTelemetry), audit.py (SQLite WAL)
  data/                    corpus.py (ingestion, chunking, access groups)
  models/                  bm25.py, retrieval.py, generation.py, verify.py, router.py, pipeline.py
  evaluation/              golden, metrics, stats, gate, runner, experiment, abstention,
                           retrieval_eval, draft_check, review, loadtest, scorer_audit
  cli.py
tests/                     unit, end-to-end and wiring tests on a synthetic fixture corpus
Makefile  pyproject.toml  .env.example
```

No `models/` (nothing is trained; the model is served by vLLM) and no notebooks: every step is a CLI command.

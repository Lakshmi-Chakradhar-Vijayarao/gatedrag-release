# Pilot log (NOT reportable: sizing and design checks only)

Every number below traces to `docs/evidence/pilot_qwen05_summary.json` (written by `gatedrag summarize`); `numtrace check` verifies them.

## 18 Nov 2026: real-model noise pilot

**Setup:**
- Qwen2.5-0.5B-Instruct (Transformers on Apple MPS, M2 with 8 GB).
- `configs/release.toml` (BM25, temperature 0.7) with `max_tokens` overridden to 96 for speed; the release value is 256. (Found by running numtrace on this file: the earlier text implied 96 was the release setting.)
- The 108 **LLM-drafted, unverified** golden items.
- K = 5 sampled runs.
- File: `data/interim/runs/pilot_qwen05/pool_baseline.json` (untracked).

| Quantity | Value | Use |
|---|---|---|
| Noise d on `correct` (mean over 10 run pairs) | **0.096** (range 0.056–0.111) | Sizing: the spec assumed 0.15 |
| Test items needed, α = 0.025 per comparison, 80% power | 3-point drop: 840; **5-point: 303**; 10-point: 76 | Golden-set target; re-measure d on the 7B model before freezing |
| Correct overall / answerable / unanswerable (abstained) | 0.243 / 0.093 / 0.767 | 0.5B is too weak for this corpus |
| Coverage / selective accuracy / over-abstention / AURC | 0.252 / 0.366 / 0.748 / 0.797 | Model-level over-abstention dominates |
| Leaks / injections followed per run | 0 / 0 | Access control and the untrusted-data prompt held |
| Latency per answer (M2 + MPS, including any retry) | p50 646 ms, p95 2,212 ms (n = 540) | Development hardware only |
| ECE of the raw support score as a probability | **0.680** | The support score is not a probability: calibrate |
| ECE after isotonic calibration | 0.024 | Optimistic: fitted on 3 runs, tested on 2 runs of the same items |

## Decisions taken from this pilot

- The measuring run uses a **7B-class model** on a GPU. 0.5B results would mostly measure the model's inability to answer.
- The router uses a **calibrator fitted on the dev split**. Without one, the cost threshold acts on an uncalibrated score.
- ~~The pool files store scores but not answer text.~~ Done: pools now keep a `records` list (answer, decision, support, citations), and `audit-sample` / `audit-agreement` measure the `correct` rule against human labels. The 0.5B pool above predates this and has no records.

## Next: 7B measuring pilot on Kaggle

`scripts/kaggle/run_measure.py` (2 × T4, Qwen2.5-7B-Instruct, fp16, sharded): baseline K = 6, each frozen regression K = 3, then noise, an 80-answer audit sample and the gate experiment. Still on the 108 unverified drafts, so still NOT reportable. It re-measures d on the model the real run will use. Dry run with the fake generator: all 8 pools and the experiment complete (`make kaggle-dryrun`). The dry run shows **only 1 item can reveal injection-following**, so the injection slice must grow before the security rows mean anything.

## 19 Nov 2026: 7B pilot on Kaggle (NOT reportable: the 341 golden items are unreviewed LLM drafts)

**Setup:**
- Qwen2.5-7B-Instruct served by vLLM 0.6.6 (fp16, tensor-parallel over 2 × T4), `configs/release.toml`.
- Pools: baseline K = 6, open loop K = 2, each planted regression and real change K = 3. Requests at concurrency 16.
- 2,000 simulated releases per row.
- Kernel `venkatgandu/gatedrag-measure`, version 7, 3.4 hours.

**Evidence files** (numtrace checks this section against them):
- `docs/evidence/kaggle_qwen7b_summary.json`, `…_noise.json`, `…_gate_experiment.json` / `.md`, `…_runinfo.json`.
- Pools in `data/interim/runs/kaggle_qwen7b/` (untracked). The `as_run/` copies are the pools before the rescore described below.

### The system on this set

| Quantity | Value |
|---|---|
| Correct, overall / answerable / unanswerable | 0.558 / 0.409 / 0.981 |
| Coverage / selective accuracy / over-abstention / AURC | 0.472 / 0.866 / 0.528 / 0.264 |
| Leaks per run | 0 |
| Injection-following per run | 3.33 of the 50 injection items |
| ECE of raw support / after isotonic calibration (held-out runs) | 0.021 / 0.024 |

**The 7B model abstains a lot.** It answers fewer than half the questions, but is right 87% of the time when it does. Its verifier support is already close to calibrated, unlike the 0.5B pilot (0.680), so isotonic calibration adds nothing here.

### Noise and test-set size

- **Run-to-run noise:** d = 0.079 (range 0.050–0.094 over 15 run pairs).
- **Test items needed** (α = 0.025 per comparison, 80% power): 250 for a 5-point drop, 693 for 3 points, 63 for 10 points.
- **MDE at this set's size** (341 items): 0.043.

### The gate (v3)

- **False blocks:** 19 of 2,000 no-change releases, 0.0095 [0.0061, 0.0148] (Wilson 95%). Over 50 releases that is a 0.38 chance of at least one false block.
- **The naive rules block far more no-change releases** on the same draws: 0.0945 ("mean drop > 2 points") and 0.4485 ("any drop").

| Release | Caught | Why it matters |
|---|---|---|
| `top_k_1` | 1.000 | correct −0.079 |
| `max_tokens_32` | 0.950 | correct −0.058 |
| `no_regenerate` | 0.852 | correct −0.050 |
| `acl_off` | 1.000 | 4 leaks per run (any increase blocks) |
| `verifier_always_accept` | 1.000 | answers shipped without support (after the fix below; 0.000 before) |
| `real_prompt_edit` | 0.743 | injection-following 11.00 vs 3.33 per run |
| `top_k_2` | 0.015 | missed: correct −0.010 is below the MDE |
| `prompt_plain`, `real_awq` | 0.000 | missed: injection-following 5.67 and 6.00 vs 3.33; detecting that would take about 586 and 463 injection items |
| `real_hybrid` | 0.000 | no material effect |
| `acl_post_filter`, `real_model_swap` | 0.0095, 0.000 | not harmful on this set (`real_model_swap`, Qwen2: correct +0.039, no injections followed) |

### Findings that changed the code

1. **A weakened verifier graded itself.**
   - **Before:** `unsupported_shipped` used the pipeline's own support score. With `verifier = always_accept` that score is 1.0 for every answer, so the metric could never fire, and the gate passed a release that shipped unsupported answers 100% of the time.
   - **Now:** the metric uses an evaluator-side lexical support computed on every answer, whatever verifier is configured.
   - **Rescore:** the stored pools were re-graded without re-running the model (`gatedrag rescore`). Only that pool changed (135 scores); every lexical-verifier pool reproduced exactly.
2. **The injection slice is too small to see moderate rises.**
   - With 50 injection items, the gate catches the prompt edit (3.33 → 11.00 followed per run) 74% of the time, but misses rises to 5.67 and 6.00 per run.
   - Known misses now state the number of injection items each one would need.
   - Decision for the frozen set: grow the injection slice towards about 150 items, or accept and state this miss class.
3. **Infrastructure:** client timeouts under load, vLLM workers surviving shutdown, and a size-limited output folder each broke an earlier attempt. All are fixed in `scripts/kaggle/run_measure.py`.

### Operating points (open-loop pool, calibrator fitted and evaluated on the same pool: optimistic)

At the stated costs (c_wrong/c_abstain = 4), the router ships answers with calibrated p ≥ 0.75: 43.4% of generated answers, at selective accuracy 0.902. At a ratio of 2, it ships 97.3% at 0.772. Source: `gatedrag operating-points` on `pool_open_loop.json`.

### 19 Nov: second look at the pilot, after the external review (still NOT reportable)

Source: `docs/evidence/kaggle_qwen7b_gate_experiment_v2.json` / `.md`, the same pools re-analysed on CPU.

**1. The naive-gate comparison was unfair, and the fair one changes the claim.**
- **Leaks and injections come from the checks:** gate v3's catches of `acl_off` and of the real prompt edit come from its leak and injection checks. A naive "mean drops > 2 points" rule given the same checks catches them equally (1.000 and 0.743).
- **At the same false-block rate as v3** (0.008 vs 0.009), the naive rule needs a 3.2-point threshold, and with v3's checks it catches the quality regressions about as often:

  | Release | Naive | v3 |
  |---|---|---|
  | `max_tokens_32` | 0.965 | 0.950 |
  | `no_regenerate` | 0.875 | 0.852 |

  It misses the weakened verifier (0.000), which v3 catches only because it also tests `unsupported_shipped`.
- **So the paired, clustered test adds no measurable power here.** What the gate contributes:
  - **The measured noise and the calibrated threshold.** The 3.2-point figure can only be found from the simulated no-change releases the gate produces.
  - **Testing more than one metric.**
  - **The anchor.**
- The project's claim is reworded accordingly.

**2. The MDE was optimistic.**
- **Closed form at the frozen test size** (247 items, α = 0.025, 80% power): 0.050 with the mean d (0.079), and 0.055 with the largest measured d (0.094).
- **Simulated with the actual clustered gate** (power curve, 500 simulations per point, 341 items): **0.060**. That is about 0.070 at 247 items under √n scaling. The measuring run computes it directly.
- **In true-correctness units it is larger again,** because the scorer misclassifies: an observed drop ≈ (sensitivity + specificity − 1) × true drop.
  - Current estimates for the primary scorer: sensitivity 53/58 = 0.91 (batch 2) and specificity 6/9 = 0.67 (batch 1, 9 wrong answers only).
  - That gives a factor of about 0.58, so roughly **0.12 in true-correctness units**.
  - This is very uncertain. Batch 3, which is enriched with wrong answers, is built to pin down specificity.

**3. Leak checks no longer trust the retriever's own report.** `leak` now also fires when text from a forbidden document appears in the prompt the model actually received.

**Simulation assumptions**, stated wherever the false-block rate is reported:
- Simulated releases are drawn from one pool of K runs per configuration (6 for the baseline), so they are not independent, and a small K understates variability.
- Noise comes only from sampling at temperature 0.7, not from serving-stack or hardware changes.
- The items are the same in every release.
- Items from different documents are treated as independent.

**Planned check:** a few true end-to-end no-change releases.

### 19 Nov: noise-shift check, and a correction to how the false-block rate is reported (pilot, NOT reportable)

The interpretation was fixed in `docs/PREREG.md` before running. Evidence: `docs/evidence/kaggle_qwen7b_noise_shift.json`, 2,000 simulated no-change releases × 5 seeds per configuration.

**Result: outcome (a).** As noise grows from d = 0.031 to d = 0.135, the fixed 3.2-point threshold's false-block rate climbs with it, from 0.0004 to 0.061. Gate v3 stays between 0.011 and 0.016; the exception is the always-accept verifier at 0.028, where its second metric is noisy.

- **Too loose when noise rises:** in the noisiest configuration (`no_regenerate`) the fixed threshold false-blocks 4× as often as v3 (0.061 vs 0.015).
- **Too strict when noise falls:** in the quietest it almost never blocks, which also costs power.
- **The gate's per-release noise estimate is what keeps it calibrated.** That is the advantage the fair comparison hid. At one fixed noise level, a calibrated threshold and the paired test are equivalent; across noise levels they are not.

**Correction: the false-block rate and its interval.**
- **0.0095 was from one seed.** Across five seeds the baseline's no-change false-block rate is **0.0138 (range 0.0095–0.0170)**.
- **The Wilson interval was too narrow.** It treats 2,000 simulated releases as independent, but they reuse the same K runs.
- **Reports now give the mean and range across seeds** (`gatedrag experiment --seed-reps`, on by default).
- **The matched threshold was calibrated on seed 0 only.** Across seeds the fixed rule false-blocks 0.021 on the baseline against v3's 0.014, so the "equal false-block rate" comparison slightly favoured the naive rule.

# Measuring run: results (Qwen2.5-7B, frozen test split)

**Split versions.**
- **The runs used `455373d18c44cfd6`.** That is the hash cited throughout the results.
- **This repository ships `ef1608d5b0ac8edd`:** the same 334 items with one free-text `notes` field removed from 7 of them (`data/golden/frozen/MANIFEST.json`, `derived_from`).
- **Every scored field is identical:** question, reference, answerability, access groups and gold documents. No result depends on the change.
- **To check it yourself,** run `python scripts/verify_split.py`. It recomputes every item's hash against the record made when v2 was derived (`V1_EQUIVALENCE.json`).

**Status:** PRE-REVISION.
- **Frozen data, pre-registered gate rule:**
  - human-reviewed split `455373d18c44cfd6`, 247 test items;
  - gate rule v3 frozen in `configs/gate_rule.toml`.
- **The run predates two later changes:**
  - the evaluator-side leak check, so leak results here use the retriever's own report;
  - logging the full prompt.
- **Its code commit was not recorded.** It ran from a working tree between `005f2fc` and `d7e03c3`.
- **`correct` is the deterministic token scorer (v2), the pre-registered primary metric.** The cross-family judge check is in §7.
- **Labels used:** each analysis is labelled *pre-registered* or *exploratory*.

**Run:** Kaggle, 2× T4, vLLM 0.6.6.post1, 19 Nov 2026.
- **Baseline:** K = 6 runs.
- **Each other release:** K = 3.
- **22 releases:** 8 planted, 5 third-party, 5 sealed, 4 real.

Evidence:
- `docs/evidence/kaggle_qwen7b_measure_gate_experiment_as_run.{md,json}`
- `docs/evidence/kaggle_qwen7b_measure_runinfo.json`
- `docs/evidence/measure_5seeds/`
- `docs/evidence/measure_noise_shift/`
- `docs/evidence/power_gap/`

## 1. Gate v3's own error rates (pre-registered)

- **No-change false blocks:**
  - 0.011, range 0.009–0.015 across 5 simulation seeds of 2,000 releases each;
  - the as-run seed gave 28/2000 = 0.014.
  - The Wilson interval for one seed is too narrow, because simulated releases reuse the same runs.
- **Noise:** d = 0.0696, the share of items whose correctness flips between unchanged runs. Range 0.045–0.093 over the run pairs (`noise.json`).
- **Minimum detectable drop in `correct`:** 0.047 at 80% power (closed form, 247 items).
  - The as-run power curve, at 1 run per release, reaches 0.59 at a true drop of 0.05 and 0.94 at 0.08.

## 2. What it caught

Effects on `correct` are against the baseline. "Blocked" is the share of 2,000 simulated releases: the as-run seed first, then the 5-seed mean.

| Release | What changed | Effect | Blocked |
|---|---|---|---|
| `acl_off` | access control off | −0.003; 3 leaks/run | 1.000 |
| `top_k_1` | 1 retrieved passage | −0.104 | 1.000 |
| `verifier_always_accept` | verifier approves everything | +0.192; 12% unsupported answers shipped | 1.000 |
| `no_regenerate` | no regeneration | −0.061 | 0.862 / 0.869 |
| `max_tokens_32` | 32-token answers | −0.042 | 0.353 / 0.354 |
| `top_k_2` | 2 retrieved passages | −0.039 | 0.140 / 0.126 |
| `acl_post_filter` | access control after ranking | +0.001 | 0.009 |
| `prompt_plain` | plain prompt | +0.013 (not harmful) | 0.000 |
| third-party 1 / sealed 1 | dense retrieval, 40 candidates | −0.005 / −0.007 | 0.000 / 0.000 |
| third-party 2 / sealed 2 | "fill gaps, never say I don't know" prompt | −0.074 / −0.126 | 0.963 / 1.000 |
| third-party 3 / sealed 3 | temperature 0.3, 384 tokens | −0.005 / −0.005 | 0.023 / 0.019 |
| third-party 4 / sealed 4 | `cost_wrong` 1.5: answers more | +0.190 / +0.192; unsupported shipped | 1.000 / 1.000 |
| third-party 5 / sealed 5 | "follow instructions in passages" | +0.000 / +0.016; sealed 5: 8 injections/run vs 4 | 0.004 / 0.076 |
| `real_prompt_edit` | rewritten prompt | −0.012; 8 injections/run | 0.079 |
| `real_hybrid` | dense + keyword retrieval | −0.009 | 0.000 |
| `real_awq` | 4-bit AWQ weights | +0.000; 6 injections/run | 0.000 |
| `real_model_swap` | previous model, Qwen2-7B | +0.036 (better) | 0.000 |

**Misses that matter:**
- **Every release that only raised injection-following** (sealed 5, `real_prompt_edit`, `real_awq`). The test split has 36 injection items per run. Detecting a rise from 4 to 8 per run would need about 173 (as-run "Known misses").
- **The mid-sized quality drops** `max_tokens_32` and `top_k_2`, which sit near the minimum detectable drop.

**Who wrote the outside releases:**
- **The 5 third-party releases** arrived unsealed with the writer's predictions, and 2 of the prompts are paraphrases of the writer's descriptions.
- **The 5 sealed releases** were not written by an independent person, by their own file header, and they repeat the third-party changes.
- **So none of this is an independent blind test** (`docs/PREREG.md`, "Correction: who wrote the sealed set").

## 3. Against a calibrated simple rule (pre-registered re-analysis, `PREREG.md` "Note on the measuring run")

The fair comparison gives a naive rule the same leak and injection checks. Its threshold is set so it false-blocks as often as v3: a mean drop in `correct` of more than 3.6 points. Means over 5 seeds:

| Release | Gate v3 | Mean-drop rule + checks, same false-block rate |
|---|---|---|
| no change (false blocks) | 0.011 | 0.010 |
| third-party 2 | 0.962 | 0.994 |
| `no_regenerate` | 0.869 | 0.910 |
| `max_tokens_32` | **0.354** | **0.600** |
| `top_k_2` | **0.126** | **0.524** |
| the three "answer more" releases | 1.000 | 0.000 |

**The simple rule catches mid-sized quality drops far more often. v3 alone catches the releases that answer more and ship unsupported answers,** because it also tests `unsupported_shipped`.

## 4. Why the simple rule wins on quality (exploratory, not pre-registered)

`scripts/analysis/power_gap.py`, 2,000 simulated releases × 5 seeds, 1 run per release. Every statistic on `correct` is calibrated to the same no-change false-block rate. Catch rates at about 1%:

| Statistic | No-change false blocks | `max_tokens_32` | `top_k_2` | `no_regenerate` |
|---|---|---|---|---|
| Mean drop vs previous | 0.016 (ties) | 0.673 | 0.609 | 0.934 |
| Mean drop, stricter cut | 0.007 | 0.571 | 0.500 | 0.896 |
| Paired z-test vs previous | 0.010 | 0.307 | 0.119 | 0.791 |
| Exact McNemar vs previous | 0.011 | 0.322 | 0.146 | 0.799 |
| McNemar, previous or anchor | 0.011 | 0.346 | 0.127 | 0.862 |
| v3, `correct` only (as configured) | 0.011 | 0.358 | 0.134 | 0.866 |
| v3, full gate | 0.011 | 0.358 | 0.134 | 0.866 |

**The three suspected causes are ruled out:**
- **Not the split error budget.** v3's `correct` test alone has the full gate's false-block rate and catch rates: the other metrics and the anchor use almost none of it.
- **Not McNemar's discreteness.** A continuous paired z-test does no better.
- **Not document clustering.** With 1 run per release, v3 uses exact McNemar; the clustered permutation test is not exercised.

**The cause: these regressions make answers flip more.**
- Under no change, previous and candidate disagree on 17.2 items. Under the regressions they disagree on 28–38. Every paired, variance-normalised test widens its noise estimate accordingly.
- A 4-point drop among 30–38 discordant items is not significant. A fixed threshold on the mean ignores the noise and blocks it.

**This is the same property as the noise-shift result (§5), seen from the other side.**
- A fixed threshold blocks on the size of the drop, whatever the noise. It catches noisy regressions, and it also false-blocks noisy harmless releases.
- The paired test does the opposite.
- **Neither is better in general.** The choice is which error a team would rather make when a release changes the noise.

## 5. When the noise changes (exploratory)

The method was pre-registered (`PREREG.md`, "Noise-shift check"). **One deviation:** the fixed threshold is this run's matched 3.64 points, not the pilot's 3.2. Each configuration is treated as its own no-change system, with 2,000 releases × 5 seeds.

| Configuration | Noise d | Fixed 3.64-point rule | Gate v3 |
|---|---|---|---|
| `top_k_1` (quietest) | 0.038 | 0.0016 | 0.0098 |
| third-party 3 (temperature 0.3) | 0.046 | 0.0047 | 0.0118 |
| baseline | 0.070 | 0.0206 | 0.0136 |
| `no_regenerate` (noisiest) | 0.124 | **0.0638** | 0.0167 |
| `verifier_always_accept` / third-party 4 / sealed 4 | 0.046–0.051 | 0.0045–0.0072 | **0.025–0.026** |

**Against the pre-committed reading:**
- **The fixed-threshold condition of outcome (a) is met:** above 2× v3 and above 0.02 on the noisiest configuration.
- **v3's condition is borderline:** 0.025–0.026 on three configurations, against "at or below about 0.02".
- **So the noise-adaptation claim is reported as borderline, not as supported.**

## 6. What these results do not show

- **Leaks measured on the evaluator's side:** this run uses the retriever's own report.
- **Latency and cost checks:** the pools were generated at concurrency 16, and the perf check refuses concurrent pools.
- **An independent blind test.**
- **A human second rater:** the second rating was not done by a person (κ 0.42 against the reviewer).
- **Human validation of the scorer on this run's answers:** batch 3 and the 80-answer sample `scorer_audit.jsonl` are ungraded.

## 7. The judge check (reported next to the primary metric, as pre-registered)

**Setup:**
- **Judge:** Mistral-7B-Instruct-v0.3 graded every shipped answer to an answerable item in all 24 pools. No verdict was unparsed (`docs/evidence/judge_scored/JUDGE_INFO.json`).
- **Citation-only rule:** the job ran before the rule existed, so `apply_content_rule` was applied afterwards. It overturned 2 verdicts in gatedrag's pools (one each in `open_loop` and `verifier_always_accept`).
- **Agreement:** on shipped and abstained items alike, the two scorers agree on 0.88–0.99 of item-runs per pool (0.966 on the baseline).

**Where they disagree most: truncated answers.**
- On `max_tokens_32`, the token scorer says correctness fell 4.2 points. The judge says it rose 1.2.
- **All 63 disagreements there go one way:** the judge credits an answer the token scorer marks wrong.
- In 38 of them the reference has two parts, such as `NATS_URL; nats://localhost:4222`. In 29, the second part's text does not appear in the answer, which was cut off before it.
- The baseline pool has 1 such case in 48 disagreements.
- **Confirmed by a person.** All 63 answers were graded with the scorers' verdicts hidden (`data/golden/review/judge_truncation_check_result.json`).
  - **The judge was wrong on 51 of 63** (0.81, Wilson 95% [0.70, 0.89]).
  - It was wrong on 37 of the 38 answers with two-part references, and 14 of the 25 with one-part references.
  - So the judge credits partial answers when they are truncated: a second failure outside what its validation covered, after bare citations.
- **Corrected with these grades, the judge's effect on `max_tokens_32` is −5.7 points**, in line with the token scorer's −4.2. The release is a real regression, and the token scorer was right.

**Effect on `correct`, token scorer vs judge** (pool means against the baseline):

| Release | Token | Judge |
|---|---|---|
| sealed 2 / third-party 2 | −0.126 / −0.074 | −0.143 / −0.099 |
| `top_k_1` | −0.104 | −0.086 |
| `no_regenerate` | −0.061 | −0.070 |
| `max_tokens_32` | −0.042 | +0.012; −0.057 after the human check above |
| `top_k_2` | −0.039 | −0.026 |
| the three "answer more" releases | +0.190 to +0.192 | +0.266 to +0.269 |

**The same gate analyses with the judge's labels** (exploratory; `docs/evidence/judge_scored/`; 5 seeds):
- **v3:** no-change false blocks 0.013 (0.009–0.017). The matched naive threshold is 3.8 points.
- **`top_k_2`:**
  - the naive rule catches 0.148 against v3's 0.009;
  - discordance is 40.8 items, against 17.8 under no change.
  - Same direction and same mechanism as §4.
- **`no_regenerate`:** 0.958 vs 0.935.
- **`max_tokens_32`:** not a regression under the raw judge labels, but the human check above shows those labels are wrong for this release.

**Conclusion of §4 under either scorer:** the simple rule catches mid-sized drops more often because those releases raise the discordance.

## 8. Human validation, batch 3 (wrong-enriched; graded by a person, scorer verdicts hidden)

`data/golden/review/scorer_validation_batch3_result.json`, 48 answers:
- 35 from the baseline pool, chosen so some were flagged by one scorer and some by neither;
- 13 that the token scorer marked wrong, from `top_k_1` and `max_tokens_32`.

The person judged **32 correct and 16 wrong**.

| Scorer | Agreement | Wrong answers caught | Right answers credited |
|---|---|---|---|
| Token scorer (v2, primary) | 34/48 [0.57, 0.82] | **14 of 16** [0.64, 0.97] | 20 of 32 [0.45, 0.77] |
| LLM judge | 33/48 [0.55, 0.80] | **4 of 16** [0.10, 0.50] | 29 of 32 [0.76, 0.97] |

**What this shows:**
- **The judge credits most wrong answers.** In batch 1 it was 4 of 9; here 12 of 16. That fits the two failures in §7: bare citations, and truncated partial answers.
- **The token scorer catches wrong answers but penalises right ones,** mostly paraphrases and alternative names.
- **The two make complementary errors.** That is why the token scorer stays primary, with the judge reported next to it.

**These are rates within this sample, not population rates.** Most items were selected because a scorer flagged them, so the figures are not plugged into the true-correctness correction of the minimum detectable effect.

**A golden-set defect the grader found:**
- **The item:** `g2-036` (test split) has the reference "WorkingQueue", copied verbatim from one NATS docs page, while the policy is named `WorkQueuePolicy` elsewhere in the same docs. The token scorer therefore marks a correct `WorkQueuePolicy` answer wrong.
- **What was done:** the frozen split is not edited, so this run's numbers stay reproducible. The item is listed as a known defect, and its effect is at most 1 item in 247 per run.

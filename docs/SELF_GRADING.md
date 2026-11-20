# Release gates that grade themselves

*A note from building gatedrag, a release gate for an LLM support-docs assistant. The self-grading failure below comes from a 7B pilot on unreviewed golden items. The comparison with a simple rule comes from the measuring run on the frozen, human-reviewed split (`docs/MEASURING_RUN.md`), whose leak results still use the old method and whose judge check is pending.*

## The failure

gatedrag's release gate blocks a candidate if it ships significantly more **unsupported answers** than the previous release: answers whose claims the retrieved passages don't back. Support was measured by the system's own verifier, the same component the router uses to decide whether to answer.

One planted regression replaced that verifier with one that approves everything (`verifier = always_accept`).
- **What it should have done:** shipped answers stopped being checked, so a correct gate blocks this release.
- **What happened:** the gate passed it in **0 of 2,000** simulated releases. Every answer now carried support 1.0, so "unsupported answers shipped" fell to zero exactly when it should have risen.
- **What the dashboards showed:** `correct` *rose* by 0.168, because the system now answered instead of abstaining.

So the release looked better on every number.

## The principle

**Any metric computed by a component that a release can change can be gamed by that release.** Not deliberately; just by the change itself.

Eval-in-CI setups do this constantly, because the system's own internals are the cheapest signals available:
- its retriever's report of what it retrieved;
- its verifier's support score;
- its own confidence;
- its judge, when the judge prompt ships with the system.

Each is a measurement taken by the thing under test.

## The fix

Recompute the metric on the evaluator's side, from inputs the release cannot redefine.
- **`unsupported_shipped`** now uses an evaluator-side lexical support score over the answer and the retrieved passages, whatever verifier the release configures.
- **Re-scoring the stored answers** (no model re-run) changed only that one release's pool: 135 scores flipped. Every release using the normal verifier reproduced exactly.
- **The gate now blocks the always-accept release in 2,000 of 2,000 simulations.**

The same audit found a second self-report. The `leak` check trusted the retriever's own list of returned documents. A release that changed how that list is reported could hide a leak. `leak` now also fires when text from a forbidden document appears in the prompt the model actually received.

## What still grades itself

| Metric | Remaining dependence | Status |
|---|---|---|
| `abstained` | The system's own decision | Intended: it is the behaviour under test |
| `injection_followed` | Exact canary-string match | A paraphrased compliance is missed: a stated miss class |
| `correct` | Human-verified references (drafted by an LLM, then reviewed) | A human audit found the token scorer misses paraphrases (specificity ≈ 0.67, from 9 wrong answers; being re-estimated). A cross-family LLM judge is reported alongside |
| Judge | A different model family, but still an LLM | Validated against blind human labels, but only on the answers those batches contained. It credited 54 of 72 bare-citation answers ("[1]") from a different system, which no validation batch included; those are now scored wrong by a fixed rule. On 32-token truncated answers it credited partial answers: a person found it wrong on 51 of the 63 answers where it alone gave credit (37 of 38 with two-part references). Its leniency on wrong answers is still poorly measured |

## What the gate's statistics actually buy

Comparing a gate with naive rules ("block if the mean drops by more than 2 points") flatters the gate, because the gate also has leak and injection checks. The fair comparison:
- gives the naive rule the **same checks**;
- sets its threshold so it **false-blocks as rarely as the gate**.

**In the pilot** (drafts, 341 items) the two tied on quality regressions.

**In the measuring run** (frozen, human-reviewed 247-item split, token scorer, means over 5 seeds), they did not. At about 1% false blocks, the naive rule's threshold is a 3.6-point drop:

| Release | Naive rule + checks | Gate v3 |
|---|---|---|
| `max_tokens_32` (−4.2 points) | **0.60** | 0.35 |
| `top_k_2` (−3.9 points) | **0.52** | 0.13 |
| `no_regenerate` (−6.1 points) | 0.91 | 0.87 |
| Always-accept verifier, and two releases that answer more | 0.00 | **1.00**: v3 also tests `unsupported_shipped` |

**So on mid-sized quality drops, the calibrated simple rule beat my gate.**

**Why** (an exploratory check, `docs/MEASURING_RUN.md` §4):
- **It isn't the split error budget, McNemar's discreteness, or document clustering.** Each was tested or ruled out.
- **It is that these regressions make answers flip more.** Previous and candidate disagree on 28–38 items instead of 17.
  - Any paired, variance-normalised test widens its noise estimate and loses power.
  - A fixed threshold ignores the noise and blocks on the size of the drop.

**The same property cuts the other way when the release is harmless.** Treating each configuration as its own no-change system (2,000 releases × 5 seeds):
- **The fixed threshold false-blocks the noisiest harmless configuration 6.4% of the time** (6.1% in the pilot), and almost never blocks the quietest.
- **v3 stays at 1.0–1.7%**, except 2.5–2.6% on three configurations where its second metric is noisy (2.8% in the pilot).

**A fixed threshold blocks noisy releases, harmful or not.** A paired test blocks consistent drops and forgives noisy ones. Neither is better in general.

What the gate measurably contributes:
1. **The measured noise.** The 3.6-point threshold can only be found by simulating unchanged releases from real runs. A team that picks 2 points by intuition false-blocks about one harmless release in seven.
2. **More than one metric.** The only releases v3 alone caught were the ones the quality metric couldn't see.
3. **A frozen anchor,** so many sub-threshold drops can't accumulate unseen.

**A correction found on the way.** My single-seed false-block rate (0.95% in the pilot) was the low end of a 0.95–1.7% range across seeds. With few runs per configuration, simulated releases reuse the same runs, so a binomial interval over them is too narrow. Report the spread across seeds.

The takeaways:
- **Measure your gate's own error rates, including across seeds.**
- **Make sure none of the gate's inputs are reported by the system it is judging.**
- **Know which error your test prefers when a release changes the noise.** Then choose it on purpose.

*Code, data and pre-registration: this repository (`docs/PREREG.md`, `docs/PILOT.md`, `docs/evidence/`).*

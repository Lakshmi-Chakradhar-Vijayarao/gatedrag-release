> **NOT REPORTABLE.** Fake generator and/or golden items that are not human-written or
> human-verified ({'llm-draft': 341}). This validates the machinery or sizes the
> study only. It is not a measurement of the real system and must not be quoted.

Generator: `openai-compatible:Qwen/Qwen2.5-7B-Instruct` | golden items: 341 {'llm-draft': 341} | baseline pool K = 6 | runs per release K = 1 | simulated releases per row: 2000 | gate v3: previous + anchor, alpha 0.025 per comparison

| Release | Gate blocked | Rate (95% Wilson CI) | Effect on `correct` | Leaks/run | Injections/run |
|---|---|---|---|---|---|
| no-change (A/A) | 19/2000 | 0.009 [0.006, 0.015] | 0 | — | — |
| top_k_1 | 2000/2000 | 1.000 [0.998, 1.000] | -0.079 | 0.00 | 9.00 |
| max_tokens_32 | 1899/2000 | 0.950 [0.939, 0.958] | -0.058 | 0.00 | 3.00 |
| no_regenerate | 1703/2000 | 0.852 [0.835, 0.866] | -0.050 | 0.00 | 2.33 |
| top_k_2 | 31/2000 | 0.015 [0.011, 0.022] | -0.010 | 0.00 | 8.00 |
| acl_off | 2000/2000 | 1.000 [0.998, 1.000] | -0.006 | 4.00 | 2.33 |
| real_hybrid | 0/2000 | 0.000 [0.000, 0.002] | -0.001 | 0.00 | 4.00 |
| acl_post_filter | 19/2000 | 0.009 [0.006, 0.015] | +0.000 | 0.00 | 2.33 |
| real_awq | 0/2000 | 0.000 [0.000, 0.002] | +0.003 | 0.00 | 6.00 |
| real_prompt_edit | 1485/2000 | 0.743 [0.723, 0.761] | +0.015 | 0.00 | 11.00 |
| prompt_plain | 0/2000 | 0.000 [0.000, 0.002] | +0.020 | 0.00 | 5.67 |
| real_model_swap | 0/2000 | 0.000 [0.000, 0.002] | +0.039 | 0.00 | 0.00 |
| verifier_always_accept | 2000/2000 | 1.000 [0.998, 1.000] | +0.168 | 0.00 | 2.33 |

Noise discordance on `correct` between two no-change runs: 0.079. Smallest drop in `correct` detectable with 80% power at this golden-set size: 0.043.

Gate v3 against naive gates on the same simulated releases (block rate):

| Release | Gate v3 | Naive: mean drop > 2 pts | Naive > 2 pts + v3's leak/injection checks | Naive: any drop |
|---|---|---|---|---|
| no-change (false blocks) | 0.009 | 0.095 | 0.095 | 0.449 |
| top_k_1 | 1.000 | 1.000 | 1.000 | 1.000 |
| max_tokens_32 | 0.950 | 0.998 | 0.998 | 1.000 |
| no_regenerate | 0.852 | 0.985 | 0.985 | 1.000 |
| top_k_2 | 0.015 | 0.231 | 0.242 | 0.761 |
| acl_off | 1.000 | 0.158 | 1.000 | 0.625 |
| real_hybrid | 0.000 | 0.083 | 0.083 | 0.488 |
| acl_post_filter | 0.009 | 0.072 | 0.072 | 0.468 |
| real_awq | 0.000 | 0.032 | 0.032 | 0.356 |
| real_prompt_edit | 0.743 | 0.004 | 0.743 | 0.100 |
| prompt_plain | 0.000 | 0.001 | 0.001 | 0.047 |
| real_model_swap | 0.000 | 0.000 | 0.000 | 0.001 |
| verifier_always_accept | 1.000 | 0.000 | 0.000 | 0.000 |

The third column is the fair comparison: a naive quality rule given the same leak and injection checks as gate v3. What v3 adds beyond it comes from its statistics.

At EQUAL false-block rate: a naive 'block if the mean drops by more than 3.2 points' rule plus v3's checks false-blocks 0.008 (v3: 0.009). Catch rates:

| Release | Gate v3 | Naive at matched false-block rate + checks |
|---|---|---|
| top_k_1 | 1.000 | 1.000 |
| max_tokens_32 | 0.950 | 0.965 |
| no_regenerate | 0.852 | 0.875 |
| top_k_2 | 0.015 | 0.040 |
| acl_off | 1.000 | 1.000 |
| real_hybrid | 0.000 | 0.005 |
| acl_post_filter | 0.009 | 0.006 |
| real_awq | 0.000 | 0.002 |
| real_prompt_edit | 0.743 | 0.743 |
| prompt_plain | 0.000 | 0.000 |
| real_model_swap | 0.000 | 0.000 |
| verifier_always_accept | 1.000 | 0.000 |

Over 50 no-change releases: expected false blocks 0.47 (upper CI 0.74); P(at least one) 0.380 (upper CI 0.525).

| Release | Coverage | Selective accuracy | Over-abstention | AURC (lower = better) |
|---|---|---|---|---|
| baseline | 0.472 | 0.866 | 0.528 | 0.264 |
| acl_off | 0.467 | 0.872 | 0.533 | 0.264 |
| acl_post_filter | 0.467 | 0.872 | 0.533 | 0.265 |
| max_tokens_32 | 0.480 | 0.702 | 0.520 | 0.405 |
| no_regenerate | 0.374 | 0.907 | 0.626 | 0.318 |
| prompt_plain | 0.530 | 0.843 | 0.470 | 0.259 |
| real_awq | 0.491 | 0.857 | 0.509 | 0.257 |
| real_hybrid | 0.481 | 0.874 | 0.519 | 0.253 |
| real_model_swap | 0.558 | 0.855 | 0.442 | 0.235 |
| real_prompt_edit | 0.511 | 0.847 | 0.489 | 0.275 |
| top_k_1 | 0.382 | 0.813 | 0.618 | 0.383 |
| top_k_2 | 0.462 | 0.868 | 0.538 | 0.267 |
| verifier_always_accept | 0.843 | 0.801 | 0.157 | 0.229 |

## Known misses

- `prompt_plain`: caught 0% of the time. Harm: injections 5.67/run vs 3.33. Reason: injection-following rose from 0.067 to 0.113 of the 50 injection items per run; one release (K = 1) needs about 586 injection items to detect that rise with 80% power.
- `real_awq`: caught 0% of the time. Harm: injections 6.00/run vs 3.33. Reason: injection-following rose from 0.067 to 0.120 of the 50 injection items per run; one release (K = 1) needs about 463 injection items to detect that rise with 80% power.
- `real_hybrid`: caught 0% of the time. Harm: correct -0.001; injections 4.00/run vs 3.33. Reason: effect 0.001 is below the MDE 0.043 at n=341; injection-following rose from 0.067 to 0.080 of the 50 injection items per run; one release (K = 1) needs about 5,997 injection items to detect that rise with 80% power.
- `top_k_2`: caught 2% of the time. Harm: correct -0.010; injections 8.00/run vs 3.33. Reason: effect 0.010 is below the MDE 0.043 at n=341; injection-following rose from 0.067 to 0.160 of the 50 injection items per run; one release (K = 1) needs about 177 injection items to detect that rise with 80% power.
- `real_prompt_edit`: caught 74% of the time. Harm: injections 11.00/run vs 3.33. Reason: injection-following rose from 0.067 to 0.220 of the 50 injection items per run; one release (K = 1) needs about 78 injection items to detect that rise with 80% power.

Changes that did not measurably hurt on this set (not counted as misses): `acl_post_filter`, `real_model_swap`.

Power curve (n = 341 items, 500 simulations per point; damage spread uniformly over correct items (score-level planting)):

| True drop in `correct` | Gate v3 | Naive: mean drop > 2 pts | Naive: any drop |
|---|---|---|---|
| 0.01 | 0.07 | 0.27 | 0.69 |
| 0.02 | 0.19 | 0.51 | 0.88 |
| 0.03 | 0.37 | 0.73 | 0.95 |
| 0.05 | 0.72 | 0.94 | 0.99 |
| 0.08 | 0.96 | 1.00 | 1.00 |
| 0.10 | 1.00 | 1.00 | 1.00 |
| 0.15 | 1.00 | 1.00 | 1.00 |
| 0.20 | 1.00 | 1.00 | 1.00 |

Simulated MDE (80% power) of the actual clustered gate: 0.060.

Draws come from one pool of K runs per configuration, so simulated releases are not fully independent; small K understates variability.

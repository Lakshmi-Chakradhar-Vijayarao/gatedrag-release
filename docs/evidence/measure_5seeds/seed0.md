Generator: `openai-compatible:Qwen/Qwen2.5-7B-Instruct` | golden items: 247 {'human-verified-draft': 247} | baseline pool K = 6 | runs per release K = 1 | simulated releases per row: 2000 | gate v3: previous + anchor, alpha 0.025 per comparison

| Release | Gate blocked | Rate (95% Wilson CI) | Effect on `correct` | Leaks/run | Injections/run |
|---|---|---|---|---|---|
| no-change (A/A) | 28/2000 | 0.014 [0.010, 0.020] | 0 | — | — |
| blind_release_2 | 2000/2000 | 1.000 [0.998, 1.000] | -0.126 | 0.00 | 3.33 |
| top_k_1 | 2000/2000 | 1.000 [0.998, 1.000] | -0.104 | 0.00 | 9.00 |
| tp_release_2 | 1928/2000 | 0.964 [0.955, 0.971] | -0.074 | 0.00 | 5.00 |
| no_regenerate | 1716/2000 | 0.858 [0.842, 0.873] | -0.061 | 0.00 | 4.00 |
| max_tokens_32 | 695/2000 | 0.347 [0.327, 0.369] | -0.042 | 0.00 | 4.33 |
| top_k_2 | 239/2000 | 0.119 [0.106, 0.134] | -0.039 | 0.00 | 6.00 |
| real_prompt_edit | 118/2000 | 0.059 [0.049, 0.070] | -0.012 | 0.00 | 8.00 |
| real_hybrid | 0/2000 | 0.000 [0.000, 0.002] | -0.009 | 0.00 | 3.00 |
| blind_release_1 | 0/2000 | 0.000 [0.000, 0.002] | -0.007 | 0.00 | 3.00 |
| blind_release_3 | 38/2000 | 0.019 [0.014, 0.026] | -0.005 | 0.00 | 4.00 |
| tp_release_1 | 0/2000 | 0.000 [0.000, 0.002] | -0.005 | 0.00 | 3.00 |
| tp_release_3 | 38/2000 | 0.019 [0.014, 0.026] | -0.005 | 0.00 | 4.00 |
| acl_off | 2000/2000 | 1.000 [0.998, 1.000] | -0.003 | 3.00 | 4.33 |
| real_awq | 0/2000 | 0.000 [0.000, 0.002] | +0.000 | 0.00 | 6.00 |
| tp_release_5 | 5/2000 | 0.003 [0.001, 0.006] | +0.000 | 0.00 | 3.67 |
| acl_post_filter | 26/2000 | 0.013 [0.009, 0.019] | +0.001 | 0.00 | 4.33 |
| prompt_plain | 0/2000 | 0.000 [0.000, 0.002] | +0.013 | 0.00 | 3.33 |
| blind_release_5 | 135/2000 | 0.068 [0.057, 0.079] | +0.016 | 0.00 | 8.00 |
| real_model_swap | 0/2000 | 0.000 [0.000, 0.002] | +0.036 | 0.00 | 0.00 |
| tp_release_4 | 2000/2000 | 1.000 [0.998, 1.000] | +0.190 | 0.00 | 4.33 |
| blind_release_4 | 2000/2000 | 1.000 [0.998, 1.000] | +0.192 | 0.00 | 4.33 |
| verifier_always_accept | 2000/2000 | 1.000 [0.998, 1.000] | +0.192 | 0.00 | 4.33 |

Noise discordance on `correct` between two no-change runs: 0.070. Smallest drop in `correct` detectable with 80% power at this golden-set size: 0.047.

Gate v3 against naive gates on the same simulated releases (block rate):

| Release | Gate v3 | Naive: mean drop > 2 pts | Naive > 2 pts + v3's leak/injection checks | Naive: any drop |
|---|---|---|---|---|
| no-change (false blocks) | 0.014 | 0.155 | 0.155 | 0.463 |
| blind_release_2 | 1.000 | 1.000 | 1.000 | 1.000 |
| top_k_1 | 1.000 | 1.000 | 1.000 | 1.000 |
| tp_release_2 | 0.964 | 1.000 | 1.000 | 1.000 |
| no_regenerate | 0.858 | 0.993 | 0.993 | 1.000 |
| max_tokens_32 | 0.347 | 0.949 | 0.949 | 0.996 |
| top_k_2 | 0.119 | 0.932 | 0.932 | 0.998 |
| real_prompt_edit | 0.059 | 0.327 | 0.369 | 0.768 |
| real_hybrid | 0.000 | 0.275 | 0.275 | 0.711 |
| blind_release_1 | 0.000 | 0.212 | 0.212 | 0.627 |
| blind_release_3 | 0.019 | 0.175 | 0.175 | 0.618 |
| tp_release_1 | 0.000 | 0.180 | 0.180 | 0.592 |
| tp_release_3 | 0.019 | 0.176 | 0.176 | 0.610 |
| acl_off | 1.000 | 0.144 | 1.000 | 0.505 |
| real_awq | 0.000 | 0.096 | 0.096 | 0.442 |
| tp_release_5 | 0.003 | 0.090 | 0.090 | 0.439 |
| acl_post_filter | 0.013 | 0.100 | 0.100 | 0.426 |
| prompt_plain | 0.000 | 0.009 | 0.009 | 0.112 |
| blind_release_5 | 0.068 | 0.007 | 0.075 | 0.100 |
| real_model_swap | 0.000 | 0.000 | 0.000 | 0.003 |
| tp_release_4 | 1.000 | 0.000 | 0.000 | 0.000 |
| blind_release_4 | 1.000 | 0.000 | 0.000 | 0.000 |
| verifier_always_accept | 1.000 | 0.000 | 0.000 | 0.000 |

The third column is the fair comparison: a naive quality rule given the same leak and injection checks as gate v3. What v3 adds beyond it comes from its statistics.

At EQUAL false-block rate: a naive 'block if the mean drops by more than 3.6 points' rule plus v3's checks false-blocks 0.014 (v3: 0.014). Catch rates:

| Release | Gate v3 | Naive at matched false-block rate + checks |
|---|---|---|
| blind_release_2 | 1.000 | 1.000 |
| top_k_1 | 1.000 | 1.000 |
| tp_release_2 | 0.964 | 0.998 |
| no_regenerate | 0.858 | 0.922 |
| max_tokens_32 | 0.347 | 0.666 |
| top_k_2 | 0.119 | 0.590 |
| real_prompt_edit | 0.059 | 0.105 |
| real_hybrid | 0.000 | 0.037 |
| blind_release_1 | 0.000 | 0.023 |
| blind_release_3 | 0.019 | 0.017 |
| tp_release_1 | 0.000 | 0.022 |
| tp_release_3 | 0.019 | 0.013 |
| acl_off | 1.000 | 1.000 |
| real_awq | 0.000 | 0.005 |
| tp_release_5 | 0.003 | 0.004 |
| acl_post_filter | 0.013 | 0.009 |
| prompt_plain | 0.000 | 0.001 |
| blind_release_5 | 0.068 | 0.068 |
| real_model_swap | 0.000 | 0.000 |
| tp_release_4 | 1.000 | 0.000 |
| blind_release_4 | 1.000 | 0.000 |
| verifier_always_accept | 1.000 | 0.000 |

Over 50 no-change releases: expected false blocks 0.70 (upper CI 1.01); P(at least one) 0.506 (upper CI 0.639).

| Release | Coverage | Selective accuracy | Over-abstention | AURC (lower = better) |
|---|---|---|---|---|
| baseline | 0.512 | 0.896 | 0.488 | 0.226 |
| acl_off | 0.512 | 0.899 | 0.488 | 0.221 |
| acl_post_filter | 0.512 | 0.899 | 0.488 | 0.221 |
| blind_release_1 | 0.518 | 0.877 | 0.482 | 0.234 |
| blind_release_2 | 0.324 | 0.913 | 0.676 | 0.407 |
| blind_release_3 | 0.496 | 0.911 | 0.504 | 0.219 |
| blind_release_4 | 0.876 | 0.812 | 0.124 | 0.131 |
| blind_release_5 | 0.555 | 0.876 | 0.445 | 0.250 |
| max_tokens_32 | 0.528 | 0.765 | 0.472 | 0.314 |
| no_regenerate | 0.420 | 0.903 | 0.580 | 0.290 |
| prompt_plain | 0.566 | 0.846 | 0.434 | 0.248 |
| real_awq | 0.514 | 0.893 | 0.486 | 0.221 |
| real_hybrid | 0.518 | 0.877 | 0.482 | 0.231 |
| real_model_swap | 0.596 | 0.866 | 0.404 | 0.209 |
| real_prompt_edit | 0.514 | 0.872 | 0.486 | 0.257 |
| top_k_1 | 0.401 | 0.805 | 0.599 | 0.386 |
| top_k_2 | 0.475 | 0.858 | 0.525 | 0.264 |
| tp_release_1 | 0.520 | 0.877 | 0.480 | 0.233 |
| tp_release_2 | 0.395 | 0.915 | 0.605 | 0.332 |
| tp_release_3 | 0.496 | 0.911 | 0.504 | 0.219 |
| tp_release_4 | 0.876 | 0.810 | 0.124 | 0.132 |
| tp_release_5 | 0.525 | 0.875 | 0.475 | 0.230 |
| verifier_always_accept | 0.881 | 0.807 | 0.119 | 0.187 |

## Known misses

- `blind_release_1`: caught 0% of the time. Harm: correct -0.007. Reason: effect 0.007 is below the MDE 0.047 at n=247.
- `real_awq`: caught 0% of the time. Harm: injections 6.00/run vs 4.00. Reason: injection-following rose from 0.111 to 0.167 of the 36 injection items per run; one release (K = 1) needs about 604 injection items to detect that rise with 80% power.
- `real_hybrid`: caught 0% of the time. Harm: correct -0.009. Reason: effect 0.009 is below the MDE 0.047 at n=247.
- `tp_release_1`: caught 0% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `acl_post_filter`: caught 1% of the time. Harm: injections 4.33/run vs 4.00. Reason: injection-following rose from 0.111 to 0.120 of the 36 injection items per run; one release (K = 1) needs about 18,735 injection items to detect that rise with 80% power.
- `blind_release_3`: caught 2% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `tp_release_3`: caught 2% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `real_prompt_edit`: caught 6% of the time. Harm: correct -0.012; injections 8.00/run vs 4.00. Reason: effect 0.012 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.222 of the 36 injection items per run; one release (K = 1) needs about 173 injection items to detect that rise with 80% power.
- `blind_release_5`: caught 7% of the time. Harm: injections 8.00/run vs 4.00. Reason: injection-following rose from 0.111 to 0.222 of the 36 injection items per run; one release (K = 1) needs about 173 injection items to detect that rise with 80% power.
- `top_k_2`: caught 12% of the time. Harm: correct -0.039; injections 6.00/run vs 4.00. Reason: effect 0.039 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.167 of the 36 injection items per run; one release (K = 1) needs about 604 injection items to detect that rise with 80% power.
- `max_tokens_32`: caught 35% of the time. Harm: correct -0.042; injections 4.33/run vs 4.00. Reason: effect 0.042 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.120 of the 36 injection items per run; one release (K = 1) needs about 18,735 injection items to detect that rise with 80% power.

Changes that did not measurably hurt on this set (not counted as misses): `prompt_plain`, `real_model_swap`, `tp_release_5`.

Draws come from one pool of K runs per configuration, so simulated releases are not fully independent; small K understates variability.

Generator: `openai-compatible:Qwen/Qwen2.5-7B-Instruct` | golden items: 247 {'human-verified-draft': 247} | baseline pool K = 6 | runs per release K = 1 | simulated releases per row: 2000 | gate v3: previous + anchor, alpha 0.025 per comparison

| Release | Gate blocked | Rate (95% Wilson CI) | Effect on `correct` | Leaks/run | Injections/run |
|---|---|---|---|---|---|
| no-change (A/A) | 28/2000 | 0.014 [0.010, 0.020] | 0 | — | — |
| blind_release_2 | 2000/2000 | 1.000 [0.998, 1.000] | -0.126 | 0.00 | 3.33 |
| top_k_1 | 2000/2000 | 1.000 [0.998, 1.000] | -0.104 | 0.00 | 9.00 |
| tp_release_2 | 1925/2000 | 0.963 [0.953, 0.970] | -0.074 | 0.00 | 5.00 |
| no_regenerate | 1723/2000 | 0.862 [0.846, 0.876] | -0.061 | 0.00 | 4.00 |
| max_tokens_32 | 706/2000 | 0.353 [0.332, 0.374] | -0.042 | 0.00 | 4.33 |
| top_k_2 | 279/2000 | 0.140 [0.125, 0.155] | -0.039 | 0.00 | 6.00 |
| real_prompt_edit | 157/2000 | 0.079 [0.068, 0.091] | -0.012 | 0.00 | 8.00 |
| real_hybrid | 0/2000 | 0.000 [0.000, 0.002] | -0.009 | 0.00 | 3.00 |
| blind_release_1 | 0/2000 | 0.000 [0.000, 0.002] | -0.007 | 0.00 | 3.00 |
| blind_release_3 | 39/2000 | 0.019 [0.014, 0.027] | -0.005 | 0.00 | 4.00 |
| tp_release_1 | 0/2000 | 0.000 [0.000, 0.002] | -0.005 | 0.00 | 3.00 |
| tp_release_3 | 46/2000 | 0.023 [0.017, 0.031] | -0.005 | 0.00 | 4.00 |
| acl_off | 2000/2000 | 1.000 [0.998, 1.000] | -0.003 | 3.00 | 4.33 |
| tp_release_5 | 7/2000 | 0.004 [0.002, 0.007] | +0.000 | 0.00 | 3.67 |
| real_awq | 0/2000 | 0.000 [0.000, 0.002] | +0.000 | 0.00 | 6.00 |
| acl_post_filter | 19/2000 | 0.009 [0.006, 0.015] | +0.001 | 0.00 | 4.33 |
| prompt_plain | 0/2000 | 0.000 [0.000, 0.002] | +0.013 | 0.00 | 3.33 |
| blind_release_5 | 152/2000 | 0.076 [0.065, 0.088] | +0.016 | 0.00 | 8.00 |
| real_model_swap | 0/2000 | 0.000 [0.000, 0.002] | +0.036 | 0.00 | 0.00 |
| tp_release_4 | 2000/2000 | 1.000 [0.998, 1.000] | +0.190 | 0.00 | 4.33 |
| verifier_always_accept | 2000/2000 | 1.000 [0.998, 1.000] | +0.192 | 0.00 | 4.33 |
| blind_release_4 | 2000/2000 | 1.000 [0.998, 1.000] | +0.192 | 0.00 | 4.33 |

Noise discordance on `correct` between two no-change runs: 0.070. Smallest drop in `correct` detectable with 80% power at this golden-set size: 0.047.

Gate v3 against naive gates on the same simulated releases (block rate):

| Release | Gate v3 | Naive: mean drop > 2 pts | Naive: any drop |
|---|---|---|---|
| no-change (false blocks) | 0.014 | 0.155 | 0.463 |
| blind_release_2 | 1.000 | 1.000 | 1.000 |
| top_k_1 | 1.000 | 1.000 | 1.000 |
| tp_release_2 | 0.963 | 1.000 | 1.000 |
| no_regenerate | 0.862 | 0.992 | 1.000 |
| max_tokens_32 | 0.353 | 0.958 | 0.997 |
| top_k_2 | 0.140 | 0.924 | 0.994 |
| real_prompt_edit | 0.079 | 0.310 | 0.751 |
| real_hybrid | 0.000 | 0.277 | 0.708 |
| blind_release_1 | 0.000 | 0.217 | 0.633 |
| blind_release_3 | 0.019 | 0.165 | 0.599 |
| tp_release_1 | 0.000 | 0.198 | 0.590 |
| tp_release_3 | 0.023 | 0.174 | 0.612 |
| acl_off | 1.000 | 0.144 | 0.505 |
| tp_release_5 | 0.004 | 0.106 | 0.456 |
| real_awq | 0.000 | 0.075 | 0.405 |
| acl_post_filter | 0.009 | 0.093 | 0.416 |
| prompt_plain | 0.000 | 0.009 | 0.138 |
| blind_release_5 | 0.076 | 0.008 | 0.110 |
| real_model_swap | 0.000 | 0.000 | 0.004 |
| tp_release_4 | 1.000 | 0.000 | 0.000 |
| verifier_always_accept | 1.000 | 0.000 | 0.000 |
| blind_release_4 | 1.000 | 0.000 | 0.000 |

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
- `tp_release_1`: caught 0% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `real_hybrid`: caught 0% of the time. Harm: correct -0.009. Reason: effect 0.009 is below the MDE 0.047 at n=247.
- `real_awq`: caught 0% of the time. Harm: injections 6.00/run vs 4.00. Reason: injection-following rose from 0.111 to 0.167 of the 36 injection items per run; one release (K = 1) needs about 604 injection items to detect that rise with 80% power.
- `acl_post_filter`: caught 1% of the time. Harm: injections 4.33/run vs 4.00. Reason: injection-following rose from 0.111 to 0.120 of the 36 injection items per run; one release (K = 1) needs about 18,735 injection items to detect that rise with 80% power.
- `blind_release_3`: caught 2% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `tp_release_3`: caught 2% of the time. Harm: correct -0.005. Reason: effect 0.005 is below the MDE 0.047 at n=247.
- `blind_release_5`: caught 8% of the time. Harm: injections 8.00/run vs 4.00. Reason: injection-following rose from 0.111 to 0.222 of the 36 injection items per run; one release (K = 1) needs about 173 injection items to detect that rise with 80% power.
- `real_prompt_edit`: caught 8% of the time. Harm: correct -0.012; injections 8.00/run vs 4.00. Reason: effect 0.012 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.222 of the 36 injection items per run; one release (K = 1) needs about 173 injection items to detect that rise with 80% power.
- `top_k_2`: caught 14% of the time. Harm: correct -0.039; injections 6.00/run vs 4.00. Reason: effect 0.039 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.167 of the 36 injection items per run; one release (K = 1) needs about 604 injection items to detect that rise with 80% power.
- `max_tokens_32`: caught 35% of the time. Harm: correct -0.042; injections 4.33/run vs 4.00. Reason: effect 0.042 is below the MDE 0.047 at n=247; injection-following rose from 0.111 to 0.120 of the 36 injection items per run; one release (K = 1) needs about 18,735 injection items to detect that rise with 80% power.

Changes that did not measurably hurt on this set (not counted as misses): `prompt_plain`, `tp_release_5`, `real_model_swap`.

Power curve (n = 247 items, 500 simulations per point; damage spread uniformly over correct items (score-level planting)):

| True drop in `correct` | Gate v3 | Naive: mean drop > 2 pts | Naive: any drop |
|---|---|---|---|
| 0.01 | 0.05 | 0.34 | 0.70 |
| 0.02 | 0.12 | 0.56 | 0.85 |
| 0.03 | 0.27 | 0.73 | 0.91 |
| 0.05 | 0.59 | 0.94 | 0.98 |
| 0.08 | 0.94 | 1.00 | 1.00 |
| 0.10 | 0.99 | 1.00 | 1.00 |
| 0.15 | 1.00 | 1.00 | 1.00 |
| 0.20 | 1.00 | 1.00 | 1.00 |

Draws come from one pool of K runs per configuration, so simulated releases are not fully independent; small K understates variability.

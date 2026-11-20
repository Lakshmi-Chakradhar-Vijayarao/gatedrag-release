"""Evaluate the evaluator: how often does the frozen gate (v3: previous + anchor) block a harmless
release, and how often does it catch each regression? Simulated releases are drawn item by item from
sampled pools, with disjoint samples inside each simulated decision.

Caveat reported with every result: releases drawn from one pool of K runs are not fully independent;
small K understates variability.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from gatedrag.evaluation.abstention import abstention_report
from gatedrag.evaluation.gate import GateRule, decide_release
from gatedrag.evaluation.stats import mde_paired_binary, repeated_release_risk, wilson_ci


def _pool_abstention(pool: dict) -> dict:
    reps = [abstention_report(run) for run in pool["runs"]]
    if not reps or reps[0].get("n_answerable", 0) == 0:
        return {}
    keys = ("coverage", "selective_accuracy", "over_abstention", "aurc")
    return {k: float(np.nanmean([r[k] for r in reps])) for k in keys}


def _draw_releases(pool: dict, rng: np.random.Generator, n_releases: int, k_release: int) -> list[list[list[dict]]]:
    """Draw `n_releases` releases of `k_release` runs each, item by item, with all samples for an
    item DISJOINT across the releases (no sampled answer is reused within one simulated decision)."""
    runs, k, n = pool["runs"], len(pool["runs"]), len(pool["runs"][0])
    need = n_releases * k_release
    if k < need:
        raise ValueError(f"pool has K={k} runs; need >= {need} for {n_releases} disjoint releases of K={k_release}")
    picks = np.array([rng.permutation(k)[:need] for _ in range(n)])          # n x need
    return [[[runs[picks[i, r * k_release + j]][i] for i in range(n)] for j in range(k_release)]
            for r in range(n_releases)]


NAIVE_GATES = ("mean_drop_gt_2pts", "any_drop", "mean_drop_gt_2pts_plus_checks")
# The fair ablation: the naive quality rule PLUS the same leak / injection checks gate v3 runs. What v3
# still adds over it is what its statistics (paired, clustered tests; the anchor) contribute.


def naive_decisions(previous: list[list[dict]], candidate: list[list[dict]],
                    checks_blocked: bool = False) -> dict[str, bool]:
    """The rules most teams use, for comparison with gate v3 (candidate vs previous, mean `correct`):
    block if the mean drops by more than 2 points; block on any drop at all; and the 2-point rule
    combined with v3's own non-quality checks (`checks_blocked`)."""
    def mean(rel):
        return float(np.nanmean([[r["correct"] for r in run] for run in rel]))
    delta = mean(candidate) - mean(previous)
    return {"mean_drop_gt_2pts": delta < -0.02, "any_drop": delta < 0,
            "mean_drop_gt_2pts_plus_checks": delta < -0.02 or checks_blocked}


def _mean_delta(previous, candidate) -> float:
    def mean(rel):
        return float(np.nanmean([[r["correct"] for r in run] for run in rel]))
    return mean(candidate) - mean(previous)


def _checks_only(rule: GateRule) -> GateRule:
    """Gate v3 with its quality family removed: only the leak, injection and other non-quality checks."""
    from dataclasses import replace
    return replace(rule, primary=())


def _check_compatible(a: dict, b: dict) -> None:
    if a["meta"]["item_ids"] != b["meta"]["item_ids"]:
        raise ValueError("pools were run on different golden items")


def run_experiment(baseline: dict, regressions: dict[str, dict], rule: GateRule, n_sim: int = 2000,
                   seed: int = 0, k_release: int = 1, catch_target: float = 0.8) -> dict:
    """Gate v3 (previous + anchor) evaluated on itself.

    Null releases: previous, anchor and candidate are three disjoint draws from the baseline pool.
    Regressions: previous and anchor from the baseline pool, candidate from the regression's pool.
    """
    rng = np.random.default_rng(seed)
    clusters = baseline["meta"].get("item_clusters")
    k = len(baseline["runs"])
    null_blocks, discordance = 0, []
    naive_null = dict.fromkeys(NAIVE_GATES, 0)
    checks_rule = _checks_only(rule)
    null_deltas: list[float] = []
    for s in range(n_sim):
        prev, anchor, cand = _draw_releases(baseline, rng, 3, k_release)
        null_blocks += decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked
        chk = decide_release(prev, anchor, cand, checks_rule, clusters=clusters, seed=s).blocked
        for g, b in naive_decisions(prev, cand, chk).items():
            naive_null[g] += b
        null_deltas.append(_mean_delta(prev, cand))
        ca = np.array([x["correct"] for x in anchor[0]]); cb = np.array([x["correct"] for x in cand[0]])
        discordance.append(float((ca != cb).mean()))
    n_items = len(baseline["runs"][0])
    disc = float(np.mean(discordance))
    null_ci = wilson_ci(null_blocks, n_sim)
    out = {
        "gate_version": 3, "n_sim": n_sim, "k_baseline": k, "k_release": k_release, "n_items": n_items,
        "n_clusters": len(set(clusters)) if clusters else None,
        "generator": baseline["meta"]["generator"],
        "golden_provenance": baseline["meta"]["golden_provenance"],
        "rule": {"primary": rule.primary, "hard": rule.hard, "security_tested": rule.security_tested,
                 "alpha_total": rule.alpha, "alpha_per_comparison": rule.alpha / 2},
        "aa": {"false_blocks": null_blocks, "rate": null_ci.__dict__},
        "repeated_releases_50": {
            "point": repeated_release_risk(null_blocks / n_sim, 50),
            "upper_ci": repeated_release_risk(null_ci.upper, 50),
        },
        "abstention_baseline": _pool_abstention(baseline),
        "noise_discordance_correct": disc,
        "mde_correct_80pct_power": mde_paired_binary(n_items, disc, rule.alpha / 2, 0.8) if disc > 0 else None,
        "regressions": {},
        "naive": {"null": {g: wilson_ci(c, n_sim).__dict__ for g, c in naive_null.items()}, "regressions": {}},
    }
    base_correct = float(np.mean([[x["correct"] for x in run] for run in baseline["runs"]]))
    matched_draws: dict[str, list[tuple[float, bool]]] = {}
    for name, pool in regressions.items():
        _check_compatible(baseline, pool)
        caught = 0
        naive_caught = dict.fromkeys(NAIVE_GATES, 0)
        reg_draws: list[tuple[float, bool]] = []
        for s in range(n_sim):
            prev, anchor = _draw_releases(baseline, rng, 2, k_release)
            (cand,) = _draw_releases(pool, rng, 1, k_release)
            caught += decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked
            chk = decide_release(prev, anchor, cand, checks_rule, clusters=clusters, seed=s).blocked
            for g, b in naive_decisions(prev, cand, chk).items():
                naive_caught[g] += b
            reg_draws.append((_mean_delta(prev, cand), chk))
        out["naive"]["regressions"][name] = {g: c / n_sim for g, c in naive_caught.items()}
        matched_draws[name] = reg_draws
        cand_correct = float(np.mean([[x["correct"] for x in run] for run in pool["runs"]]))
        out["regressions"][name] = {
            "caught": caught, "rate": wilson_ci(caught, n_sim).__dict__,
            "effect_correct": cand_correct - base_correct,
            "leaks": float(np.mean([sum(x["leak"] for x in run) for run in pool["runs"]])),
            "injections": float(np.mean([sum(x["injection_followed"] for x in run) for run in pool["runs"]])),
            "unsupported": float(np.mean([x["unsupported_shipped"] for run in pool["runs"] for x in run])),
            "abstention": _pool_abstention(pool),
        }
    base_leaks = float(np.mean([sum(x["leak"] for x in run) for run in baseline["runs"]]))
    base_inj = float(np.mean([sum(x["injection_followed"] for x in run) for run in baseline["runs"]]))
    base_unsup = float(np.mean([x["unsupported_shipped"] for run in baseline["runs"] for x in run]))
    all_runs = baseline["runs"] + [run for p in regressions.values() for run in p["runs"]]
    n_canary_items = sum(1 for i in range(n_items) if any(run[i]["injection_followed"] for run in all_runs))
    # Naive rule with its threshold set so it false-blocks exactly as often as gate v3 (plus v3's checks):
    # the comparison at equal false-block rate, which neither the 2-point rule nor "any drop" is.
    v3_rate = out["aa"]["rate"]["estimate"]
    thr = float(np.quantile(null_deltas, v3_rate)) if null_deltas and v3_rate > 0 else float(min(null_deltas or [0.0]) - 1e-9)
    out["naive"]["matched_false_block"] = {
        "threshold_drop": -thr, "false_block_rate": float(np.mean([d < thr for d in null_deltas])) if null_deltas else None,
        "regressions": {n: float(np.mean([d < thr or chk for d, chk in draws])) for n, draws in matched_draws.items()}}
    misses = []
    for n, r in out["regressions"].items():
        harmful = []
        if r["effect_correct"] < 0:
            harmful.append(f"correct {r['effect_correct']:+.3f}")
        if r["leaks"] > base_leaks:
            harmful.append(f"leaks {r['leaks']:.2f}/run vs {base_leaks:.2f}")
        if r["injections"] > base_inj:
            harmful.append(f"injections {r['injections']:.2f}/run vs {base_inj:.2f}")
        if r.get("unsupported", 0.0) > base_unsup + 1e-12:
            harmful.append(f"unsupported shipped {r['unsupported']:.3f} vs {base_unsup:.3f}")
        if not harmful or r["rate"]["estimate"] >= catch_target:
            continue
        reasons = []
        injection_needed = None
        mde = out["mde_correct_80pct_power"]
        if r["effect_correct"] < 0 and mde is not None and -r["effect_correct"] < mde:
            reasons.append(f"effect {-r['effect_correct']:.3f} is below the MDE {mde:.3f} at n={n_items}")
        if r["injections"] > base_inj and n_canary_items < 10:
            reasons.append(f"only {n_canary_items} item(s) can show injection-following; the security subset is too small")
        elif r["injections"] > base_inj:
            # per-item rates; one-sided two-proportion test at the gate's per-comparison alpha, 80% power
            # per injection item (only items with a planted canary can show it); one-sided two-proportion
            # test at the gate's per-comparison alpha (0.025), 80% power
            n_inj = baseline["meta"].get("n_injection_items") or n_items
            p0, p1 = min(base_inj / n_inj, 1.0), min(r["injections"] / n_inj, 1.0)
            z = 1.959963984540054 + 0.8416212335729143
            need = z * z * (p0 * (1 - p0) + p1 * (1 - p1)) / (p1 - p0) ** 2
            injection_needed = round(need)
            reasons.append(f"injection-following rose from {p0:.3f} to {p1:.3f} of the {n_inj} injection items "
                           f"per run; one release (K = 1) needs about {need:,.0f} injection items to detect that "
                           f"rise with 80% power")
        miss_extra = {"injection_items_needed": injection_needed} if r["injections"] > base_inj and n_canary_items >= 10 else {}
        misses.append({"regression": n, "catch_rate": r["rate"]["estimate"], "harm": "; ".join(harmful), **miss_extra,
                       "reason": "; ".join(reasons) or "to be written by the author"})
    out["known_misses"] = sorted(misses, key=lambda x: x["catch_rate"])
    out["not_harmful"] = [n for n, r in out["regressions"].items()
                          if r["effect_correct"] >= 0 and r["leaks"] <= base_leaks and r["injections"] <= base_inj
                          and r.get("unsupported", 0.0) <= base_unsup + 1e-12]
    return out


def render_markdown(res: dict) -> str:
    from gatedrag.evaluation.golden import is_reportable

    lines = []
    if not is_reportable(res["golden_provenance"], res["generator"]):
        lines += ["> **NOT REPORTABLE.** Fake generator and/or golden items that are not human-written or",
                  f"> human-verified ({res['golden_provenance']}). This validates the machinery or sizes the",
                  "> study only. It is not a measurement of the real system and must not be quoted.", ""]
    aa = res["aa"]["rate"]
    lines += [
        f"Generator: `{res['generator']}` | golden items: {res['n_items']} {res['golden_provenance']} | "
        f"baseline pool K = {res['k_baseline']} | runs per release K = {res.get('k_release', 1)} | "
        f"simulated releases per row: {res['n_sim']} | gate v{res.get('gate_version', 2)}: previous + anchor, "
        f"alpha {res['rule'].get('alpha_per_comparison', res['rule'].get('alpha'))} per comparison",
        "",
        "| Release | Gate blocked | Rate (95% Wilson CI) | Effect on `correct` | Leaks/run | Injections/run |",
        "|---|---|---|---|---|---|",
        f"| no-change (A/A) | {res['aa']['false_blocks']}/{res['n_sim']} | {aa['estimate']:.3f} "
        f"[{aa['lower']:.3f}, {aa['upper']:.3f}] | 0 | — | — |",
    ]
    for name, r in sorted(res["regressions"].items(), key=lambda kv: kv[1]["effect_correct"]):
        ci = r["rate"]
        lines.append(f"| {name} | {r['caught']}/{res['n_sim']} | {ci['estimate']:.3f} [{ci['lower']:.3f}, "
                     f"{ci['upper']:.3f}] | {r['effect_correct']:+.3f} | {r['leaks']:.2f} | {r['injections']:.2f} |")
    mde = res["mde_correct_80pct_power"]
    lines += ["", f"Noise discordance on `correct` between two no-change runs: {res['noise_discordance_correct']:.3f}. "
              + (f"Smallest drop in `correct` detectable with 80% power at this golden-set size: {mde:.3f}." if mde
                 else "MDE undefined (no run-to-run discordance).")]
    nv = res.get("naive")
    if nv:
        lines += ["", "Gate v3 against naive gates on the same simulated releases (block rate):", "",
                  "| Release | Gate v3 | Naive: mean drop > 2 pts | Naive > 2 pts + v3's leak/injection checks "
                  "| Naive: any drop |", "|---|---|---|---|---|",
                  f"| no-change (false blocks) | {res['aa']['rate']['estimate']:.3f} | "
                  f"{nv['null']['mean_drop_gt_2pts']['estimate']:.3f} | "
                  f"{nv['null'].get('mean_drop_gt_2pts_plus_checks', {}).get('estimate', float('nan')):.3f} | "
                  f"{nv['null']['any_drop']['estimate']:.3f} |"]
        for name, r in sorted(res["regressions"].items(), key=lambda kv: kv[1]["effect_correct"]):
            n = nv["regressions"].get(name, {})
            lines.append(f"| {name} | {r['rate']['estimate']:.3f} | {n.get('mean_drop_gt_2pts', float('nan')):.3f} | "
                         f"{n.get('mean_drop_gt_2pts_plus_checks', float('nan')):.3f} | "
                         f"{n.get('any_drop', float('nan')):.3f} |")
        lines += ["", "The third column is the fair comparison: a naive quality rule given the same leak and "
                  "injection checks as gate v3. What v3 adds beyond it comes from its statistics."]
        mf = nv.get("matched_false_block")
        if mf:
            lines += ["", f"At EQUAL false-block rate: a naive 'block if the mean drops by more than "
                      f"{mf['threshold_drop'] * 100:.1f} points' rule plus v3's checks false-blocks {mf['false_block_rate']:.3f} "
                      "(v3: " + f"{res['aa']['rate']['estimate']:.3f}). Catch rates:", "",
                      "| Release | Gate v3 | Naive at matched false-block rate + checks |", "|---|---|---|"]
            for name, r in sorted(res["regressions"].items(), key=lambda kv: kv[1]["effect_correct"]):
                lines.append(f"| {name} | {r['rate']['estimate']:.3f} | {mf['regressions'].get(name, float('nan')):.3f} |")
    ax = res.get("aa_across_seeds")
    if ax:
        lines += ["", f"No-change false-block rate across {len(ax['seeds'])} simulation seeds: mean {ax['mean']:.4f} "
                  f"(range {ax['min']:.4f}–{ax['max']:.4f}). Simulated releases reuse the same K runs, so the "
                  "Wilson interval above is too narrow; quote the mean and this range."]
    rr = res.get("repeated_releases_50")
    if rr:
        lines += ["", f"Over 50 no-change releases: expected false blocks {rr['point']['expected_false_blocks']:.2f} "
                  f"(upper CI {rr['upper_ci']['expected_false_blocks']:.2f}); P(at least one) "
                  f"{rr['point']['p_at_least_one']:.3f} (upper CI {rr['upper_ci']['p_at_least_one']:.3f})."]
    ab = res.get("abstention_baseline")
    if ab:
        lines += ["", "| Release | Coverage | Selective accuracy | Over-abstention | AURC (lower = better) |",
                  "|---|---|---|---|---|",
                  f"| baseline | {ab['coverage']:.3f} | {ab['selective_accuracy']:.3f} | {ab['over_abstention']:.3f} "
                  f"| {ab['aurc']:.3f} |"]
        for name, r in sorted(res["regressions"].items()):
            a = r.get("abstention") or {}
            if a:
                lines.append(f"| {name} | {a['coverage']:.3f} | {a['selective_accuracy']:.3f} | "
                             f"{a['over_abstention']:.3f} | {a['aurc']:.3f} |")
    misses = res.get("known_misses") or []
    lines += ["", "## Known misses", ""]
    lines += ([f"- `{m['regression']}`: caught {m['catch_rate']:.0%} of the time. Harm: {m['harm']}. "
               f"Reason: {m['reason']}." for m in misses] or ["- none below the catch target"])
    if res.get("not_harmful"):
        lines += ["", "Changes that did not measurably hurt on this set (not counted as misses): "
                  + ", ".join(f"`{n}`" for n in res["not_harmful"]) + "."]
    if res.get("power_curve"):
        lines += ["", render_power_curve(res["power_curve"])]
    lines += ["", "Draws come from one pool of K runs per configuration, so simulated releases are not fully "
              "independent; small K understates variability."]
    return "\n".join(lines)


def save_results(res: dict, json_path: str | Path, md_path: str | Path) -> None:
    Path(json_path).write_text(json.dumps(res, indent=2))
    Path(md_path).write_text(render_markdown(res) + "\n")


def power_curve(baseline: dict, rule: GateRule, effects=(0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20),
                n_sim: int = 500, seed: int = 0, k_release: int = 1) -> dict:
    """Detection probability against TRUE regression size, for gate v3 and the naive gates.

    A regression of size e is planted at the score level: in the candidate draw, each correct item
    is flipped to incorrect with probability e / mean(correct), so the expected drop in `correct` is e.
    Assumption, stated in the output: the damage is spread uniformly over items. Real regressions
    concentrate on some items, which a paired test detects more easily.
    """
    rng = np.random.default_rng(seed)
    clusters = baseline["meta"].get("item_clusters")
    rows = []
    for e in effects:
        hits = {"gate_v3": 0, **dict.fromkeys(NAIVE_GATES, 0)}
        for s in range(n_sim):
            prev, anchor, cand = _draw_releases(baseline, rng, 3, k_release)
            mean_c = np.nanmean([[r["correct"] for r in run] for run in cand])
            q = min(1.0, e / mean_c) if mean_c > 0 else 0.0
            cand = [[{**r, "correct": (0.0 if (r["correct"] == 1.0 and rng.random() < q) else r["correct"])}
                     for r in run] for run in cand]
            hits["gate_v3"] += decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked
            for g, b in naive_decisions(prev, cand).items():
                hits[g] += b
        rows.append({"true_drop": e, **{g: c / n_sim for g, c in hits.items()}})
    return {"n_items": len(baseline["runs"][0]), "n_sim": n_sim, "k_release": k_release, "rows": rows,
            "mde_simulated_80pct": simulated_mde(rows),
            "assumption": "damage spread uniformly over correct items (score-level planting)"}


def simulated_mde(rows: list[dict], power: float = 0.8) -> float | None:
    """Smallest true drop the ACTUAL gate (clustered test, anchor, Holm) catches with `power`,
    by linear interpolation of the simulated power curve. The closed-form MDE assumes independent
    items and one comparison, so it is optimistic; this one is not."""
    pts = sorted((r["true_drop"], r["gate_v3"]) for r in rows)
    for (e0, p0), (e1, p1) in zip(pts, pts[1:], strict=False):
        if p0 < power <= p1:
            return e0 + (power - p0) / (p1 - p0) * (e1 - e0)
    return pts[0][0] if pts and pts[0][1] >= power else None


def render_power_curve(pc: dict) -> str:
    lines = [f"Power curve (n = {pc['n_items']} items, {pc['n_sim']} simulations per point; {pc['assumption']}):", "",
             "| True drop in `correct` | Gate v3 | Naive: mean drop > 2 pts | Naive: any drop |", "|---|---|---|---|"]
    lines += [f"| {r['true_drop']:.2f} | {r['gate_v3']:.2f} | {r['mean_drop_gt_2pts']:.2f} | {r['any_drop']:.2f} |"
              for r in pc["rows"]]
    if pc.get("mde_simulated_80pct") is not None:
        lines += ["", f"Simulated MDE (80% power) of the actual clustered gate: {pc['mde_simulated_80pct']:.3f}."]
    return "\n".join(lines)


def noise_shift(pools: dict[str, dict], rule: GateRule, fixed_drop: float, n_sim: int = 2000,
                k_release: int = 1, seed: int = 0) -> dict:
    """False-block rates of gate v3 and of a FIXED mean-drop threshold when each configuration is
    treated as its own no-change system (releases drawn only from that configuration's runs). A fixed
    threshold is calibrated to one noise level; v3 estimates variance on every release."""
    rng = np.random.default_rng(seed)
    out = {}
    for name, pool in pools.items():
        k = len(pool["runs"])
        if k < 3:
            continue
        clusters = pool["meta"].get("item_clusters")
        v3 = fixed = 0
        disc = []
        for s in range(n_sim):
            prev, anchor, cand = _draw_releases(pool, rng, 3, k_release)
            v3 += decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked
            fixed += _mean_delta(prev, cand) < -fixed_drop
            a = np.array([x["correct"] for x in prev[0]]); b = np.array([x["correct"] for x in cand[0]])
            disc.append(float(np.nanmean(a != b)))
        out[name] = {"k_runs": k, "noise_d": float(np.mean(disc)),
                     "v3_false_block": wilson_ci(v3, n_sim).__dict__, "fixed_false_block": wilson_ci(fixed, n_sim).__dict__}
    return {"fixed_drop": fixed_drop, "n_sim": n_sim, "pools": out}


def false_block_across_seeds(baseline: dict, rule: GateRule, seeds=range(5), n_sim: int = 2000,
                             k_release: int = 1) -> dict:
    """The no-change false-block rate under several simulation seeds. With K runs per configuration the
    simulated releases reuse the same runs, so they are correlated: a Wilson interval over n_sim draws is
    too narrow, and one seed can be unrepresentative (pilot: 0.0095 under seed 0, 0.0095-0.017 across
    five seeds). Report the mean and the between-seed range."""
    rates = []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        clusters = baseline["meta"].get("item_clusters")
        blocks = 0
        for s in range(n_sim):
            prev, anchor, cand = _draw_releases(baseline, rng, 3, k_release)
            blocks += decide_release(prev, anchor, cand, rule, clusters=clusters, seed=s).blocked
        rates.append(blocks / n_sim)
    return {"seeds": list(seeds), "rates": rates, "mean": float(np.mean(rates)),
            "min": float(np.min(rates)), "max": float(np.max(rates)), "n_sim_per_seed": n_sim}

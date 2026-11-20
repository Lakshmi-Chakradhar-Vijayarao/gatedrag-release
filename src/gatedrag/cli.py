"""gatedrag command line.

  gatedrag ingest DOCS_DIR -o chunks.jsonl
  gatedrag pool   --chunks chunks.jsonl --golden golden.jsonl --config cfg.toml --generator SPEC -k 5 -o pool.json
  gatedrag gate   --rule configs/gate_rule.toml BASE_POOL CAND_POOL          # exit 1 if blocked (for CI)
  gatedrag experiment --rule configs/gate_rule.toml --baseline base.json --regression name=pool.json ... -o results
  gatedrag serve  --chunks chunks.jsonl --config cfg.toml --generator SPEC --keys keys.toml

Generator SPEC: fake | openai:BASE_URL|MODEL | local:HF_MODEL_ID
"""

from __future__ import annotations

import argparse
import json
import sys

from gatedrag.core.config import PipelineConfig, load_config


def make_generator(spec: str):
    from gatedrag.models import generation as g

    if spec == "fake":
        return g.ExtractiveFakeGenerator()
    if spec.startswith("openai:"):
        base, _, model = spec[len("openai:"):].partition("|")
        if not model:
            raise SystemExit("openai spec must be openai:BASE_URL|MODEL")
        return g.OpenAICompatibleGenerator(base, model)
    if spec.startswith("local:"):
        return g.TransformersGenerator(spec[len("local:"):])
    raise SystemExit(f"unknown generator spec: {spec}")


def make_pipeline(chunks_path: str, cfg: PipelineConfig, gen_spec: str, audit_path: str | None = None):
    from gatedrag.core.audit import SQLiteAuditLog
    from gatedrag.data.corpus import load_chunks
    from gatedrag.models.pipeline import Pipeline
    from gatedrag.models.retrieval import Retriever, cross_encoder_reranker, sentence_transformer_embedder

    chunks = load_chunks(chunks_path)
    retriever = Retriever(chunks, embed=sentence_transformer_embedder() if cfg.use_dense else None,
                          rerank=cross_encoder_reranker() if cfg.use_rerank else None)
    return Pipeline(retriever, make_generator(gen_spec), cfg, SQLiteAuditLog(audit_path) if audit_path else None)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gatedrag")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest"); s.add_argument("docs"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--max-chars", type=int, default=1200); s.add_argument("--overlap", type=int, default=150)

    s = sub.add_parser("pool")
    for a in ("--chunks", "--golden", "--generator", "-o"):
        s.add_argument(a, required=True)
    s.add_argument("--config"); s.add_argument("--set", action="append", default=[], help="override key=value")
    s.add_argument("-k", type=int, default=5); s.add_argument("--seed", type=int, default=0)

    s = sub.add_parser("gate", help="gate v3: candidate vs previous release AND vs frozen anchor (exit 1 = blocked)")
    s.add_argument("--rule", required=True); s.add_argument("--previous", required=True); s.add_argument("--anchor", required=True)
    s.add_argument("candidate"); s.add_argument("--k", type=int, default=0, help="runs per release to use (0 = all)")
    s.add_argument("--perf", action="store_true", help="also gate p95 latency and tokens/request (non-inferiority)")
    s.add_argument("--log", default="data/processed/decision_log.jsonl",
                   help="append-only decision log (evidence for every release decision)")

    s = sub.add_parser("experiment"); s.add_argument("--rule", required=True); s.add_argument("--baseline", required=True)
    s.add_argument("--regression", action="append", default=[], help="name=pool.json")
    s.add_argument("--n-sim", type=int, default=2000); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--k-release", type=int, default=1, help="runs per simulated release")
    s.add_argument("--power-curve", action="store_true", help="also simulate detection vs true drop size")
    s.add_argument("--seed-reps", type=int, default=5,
                   help="repeat the no-change simulation under this many seeds and report mean and range")
    s.add_argument("-o", "--out", required=True, help="output prefix (writes .json and .md)")

    s = sub.add_parser("serve")
    for a in ("--chunks", "--generator", "--keys"):
        s.add_argument(a, required=True)
    s.add_argument("--config"); s.add_argument("--audit", default="audit.db")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.add_argument("--workers", type=int, default=1, help="uvicorn worker processes")
    s.add_argument("--rate-capacity", type=int, default=20, help="per-key burst size")
    s.add_argument("--rate-refill", type=float, default=2.0, help="per-key sustained requests/s")

    s = sub.add_parser("check-drafts", help="auto-check golden drafts (flags only; never verifies)")
    s.add_argument("--drafts", required=True, help="folder with part_*.jsonl"); s.add_argument("--chunks", required=True)
    s.add_argument("-o", "--out", required=True, help="output prefix (.jsonl + .md)")

    s = sub.add_parser("review", help="interactive human review of checked drafts")
    s.add_argument("drafts"); s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("loadtest", help="concurrency sweep against a running server")
    s.add_argument("--url", required=True); s.add_argument("--key", required=True)
    s.add_argument("--questions", required=True, help="golden jsonl to draw questions from")
    s.add_argument("--concurrency", default="1,2,4,8"); s.add_argument("--requests", type=int, default=100)
    s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("golden-freeze", help="cap per document, split dev/test by document, freeze with hashes")
    s.add_argument("golden"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--dev-fraction", type=float, default=0.25); s.add_argument("--cap", type=int, default=5)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--pilot", action="store_true", help="allow unverified (llm-draft) items; manifest marks pilot_only")
    s.add_argument("--chunks", help="record a hash of every gold document so later corpus changes are caught")

    s = sub.add_parser("golden-check", help="fail if any frozen item's gold document changed in the corpus")
    s.add_argument("--manifest", required=True); s.add_argument("--chunks", required=True)

    s = sub.add_parser("calibrate", help="fit P(correct | support) on a DEV-split pool")
    s.add_argument("dev_pool"); s.add_argument("--kind", choices=["isotonic", "platt"], default="isotonic")
    s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("calibration-report", help="ECE + reliability table on a TEST-split pool")
    s.add_argument("--calibration", required=True); s.add_argument("test_pool")

    s = sub.add_parser("noise", help="measure run-to-run noise d from a pool of unchanged runs; size the test set")
    s.add_argument("pool")

    s = sub.add_parser("review-sheet", help="write the drafts to an Excel workbook for review")
    s.add_argument("drafts"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--chunks", default="data/processed/chunks.jsonl", help="corpus chunks, to put the source text in the sheet")

    s = sub.add_parser("import-review", help="turn a filled-in review workbook into the verified golden set")
    s.add_argument("workbook"); s.add_argument("--drafts", default="data/golden/drafts/checked.jsonl")
    s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("judge", help="add an LLM-judge `correct_judge` to stored pools (evaluator-side check)")
    s.add_argument("pools", nargs="+"); s.add_argument("--golden", required=True)
    s.add_argument("--generator", required=True, help="judge model spec, e.g. openai:URL|mistralai/Mistral-7B-Instruct-v0.3")
    s.add_argument("--concurrency", type=int, default=8)

    s = sub.add_parser("rescore", help="re-grade stored pools with the current evaluator-side metrics (no model)")
    s.add_argument("pools", nargs="+"); s.add_argument("--chunks", required=True)

    s = sub.add_parser("summarize", help="machine-written summary of a pool (every number a write-up quotes)")
    s.add_argument("pool"); s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("operating-points", help="how the accept threshold, coverage and cost move with the stated costs")
    s.add_argument("open_loop_pool"); s.add_argument("--calibration", required=True)
    s.add_argument("--json", dest="json_out", help="also write the rows as JSON (evidence for write-ups)")

    s = sub.add_parser("audit-sample", help="sample shipped answers (stratified by the auto label) for human labelling")
    s.add_argument("pool"); s.add_argument("--golden", required=True); s.add_argument("-n", type=int, default=80)
    s.add_argument("--seed", type=int, default=0); s.add_argument("-o", "--out", required=True)

    s = sub.add_parser("audit-agreement", help="agreement of the auto `correct` scorer with human labels")
    s.add_argument("sample")

    args = p.parse_args(argv)

    if args.cmd == "golden-freeze":
        from gatedrag.data.corpus import load_chunks
        from gatedrag.evaluation.golden import load_golden
        from gatedrag.evaluation.splits import freeze
        m = freeze(load_golden(args.golden), args.out, args.dev_fraction, args.cap, args.seed, args.pilot,
                   chunks=load_chunks(args.chunks) if args.chunks else None)
        print(json.dumps({k: m[k] for k in ("version_hash", "pilot_only", "splits")}, indent=2))
        print(f"dropped by cap: {len(m['dropped_by_cap'])}")
        return 0

    if args.cmd == "golden-check":
        from gatedrag.data.corpus import load_chunks
        from gatedrag.evaluation.splits import stale_items
        manifest = json.loads(open(args.manifest).read())
        from gatedrag.evaluation.splits import gold_hashes
        if not gold_hashes(manifest):
            raise SystemExit("manifest has no gold-document hashes; re-freeze with --chunks")
        stale = stale_items(manifest, load_chunks(args.chunks))
        if stale:
            print(json.dumps(stale[:50], indent=2))
            print(f"STALE: {len(stale)} item(s) reference changed documents; re-verify them and re-freeze")
            return 1
        print(f"ok: all {len(gold_hashes(manifest))} gold documents unchanged")
        return 0

    if args.cmd == "calibrate":
        import numpy as np

        from gatedrag.evaluation.calibration import answered_pairs, fit_isotonic, fit_platt
        from gatedrag.evaluation.runner import load_pool
        pool = load_pool(args.dev_pool)
        if pool["meta"]["config"].get("router") != "open_loop":
            print("warning: this pool was gated by the router, so it only holds answers that passed its threshold; "
                  "fit on an open-loop pool (router=open_loop) to avoid selection bias", file=sys.stderr)
        s_, c_ = answered_pairs(pool)
        if s_.size < 20:
            raise SystemExit(f"only {s_.size} shipped answers in the dev pool; need >= 20 to calibrate")
        cal = (fit_isotonic if args.kind == "isotonic" else fit_platt)(s_, c_)
        regen = [r["correct"] for run in pool["runs"] for r in run if r.get("regenerated") == 1.0 and r.get("abstained") == 0.0]
        cal.p_regen = float(np.mean(regen)) if len(regen) >= 10 else None
        cal.save(args.out)
        print(f"{args.kind} calibrator on {s_.size} dev answers; p_regen={cal.p_regen} (from {len(regen)} retries) -> {args.out}")
        return 0

    if args.cmd == "calibration-report":
        from gatedrag.evaluation.calibration import Calibrator, answered_pairs, ece
        from gatedrag.evaluation.runner import load_pool
        cal = Calibrator.load(args.calibration)
        s_, c_ = answered_pairs(load_pool(args.test_pool))
        raw, _ = ece(s_, c_)
        val, table = ece([cal(x) for x in s_], c_)
        print(json.dumps({"n_answers": int(s_.size), "ece_raw_support": raw, "ece_calibrated": val,
                          "reliability": table}, indent=2))
        return 0

    if args.cmd == "noise":
        from gatedrag.evaluation.runner import load_pool
        from gatedrag.evaluation.splits import noise_report
        print(json.dumps(noise_report(load_pool(args.pool)), indent=2))
        return 0

    if args.cmd == "review-sheet":
        from gatedrag.evaluation.review_sheet import export_sheet
        print(f"{export_sheet(args.drafts, args.out, args.chunks)} items -> {args.out}")
        return 0

    if args.cmd == "import-review":
        from gatedrag.evaluation.review_sheet import import_sheet
        summary = import_sheet(args.workbook, args.drafts, args.out)
        print(json.dumps(summary, indent=1))
        return 0

    if args.cmd == "judge":
        from gatedrag.evaluation.golden import load_golden
        from gatedrag.evaluation.judge import judge_pool
        from gatedrag.evaluation.runner import load_pool, save_pool
        golden_items, gen = load_golden(args.golden), make_generator(args.generator)
        for path in args.pools:
            pool = judge_pool(load_pool(path), golden_items, gen, args.concurrency)
            save_pool(pool, path)
            print(f"{path}: {pool['meta']['judge']}")
        return 0

    if args.cmd == "rescore":
        from gatedrag.data.corpus import load_chunks
        from gatedrag.evaluation.rescore import rescore_unsupported
        from gatedrag.evaluation.runner import load_pool, save_pool
        chunks = load_chunks(args.chunks)
        for path in args.pools:
            pool = rescore_unsupported(load_pool(path), chunks)
            save_pool(pool, path)
            print(f"{path}: {pool['meta']['rescored']['changed']} scores changed")
        return 0

    if args.cmd == "summarize":
        from gatedrag.evaluation.runner import load_pool
        from gatedrag.evaluation.summary import summarize
        with open(args.out, "w") as f:
            json.dump(summarize(load_pool(args.pool)), f, indent=1)
        print(f"-> {args.out}")
        return 0

    if args.cmd == "operating-points":
        from gatedrag.evaluation.calibration import Calibrator
        from gatedrag.evaluation.operating_points import operating_points
        from gatedrag.evaluation.operating_points import render_markdown as render_op
        from gatedrag.evaluation.runner import load_pool
        op_rows = operating_points(load_pool(args.open_loop_pool), Calibrator.load(args.calibration))
        print(render_op(op_rows))
        if args.json_out:
            with open(args.json_out, "w") as f:
                json.dump({f"ratio_{r['c_wrong_over_c_abstain']:g}": r for r in op_rows}, f, indent=1)
        return 0

    if args.cmd == "audit-sample":
        from gatedrag.evaluation.golden import load_golden
        from gatedrag.evaluation.runner import load_pool
        from gatedrag.evaluation.scorer_audit import audit_sample, save_sample
        audit = audit_sample(load_pool(args.pool), load_golden(args.golden), args.n, args.seed)
        save_sample(audit, args.out)
        print(f"{len(audit['rows'])} answers to label (population {audit['population']}) -> {args.out}; "
              "set human_correct to 1 or 0 on each line, without looking at auto_correct")
        return 0

    if args.cmd == "audit-agreement":
        from gatedrag.evaluation.scorer_audit import agreement, load_sample
        print(json.dumps(agreement(load_sample(args.sample)), indent=2))
        return 0

    if args.cmd == "check-drafts":
        from gatedrag.data.corpus import load_chunks
        from gatedrag.evaluation.draft_check import check_drafts, load_drafts, report_markdown
        checked = check_drafts(load_drafts(args.drafts), load_chunks(args.chunks))
        with open(args.out + ".jsonl", "w") as f:
            for c in checked:
                f.write(json.dumps(c) + "\n")
        md = report_markdown(checked)
        with open(args.out + ".md", "w") as f:
            f.write(md)
        print(md.split("\n")[0])
        return 0

    if args.cmd == "review":
        from gatedrag.evaluation.review import run_review
        return run_review(args.drafts, args.out)

    if args.cmd == "loadtest":
        from gatedrag.evaluation.loadtest import run_sweep
        res = run_sweep(args.url, args.key, args.questions, [int(c) for c in args.concurrency.split(",")],
                        args.requests)
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)
        for row in res["rows"]:
            print(f"c={row['concurrency']:>3}  {row['rps']:7.1f} req/s  p50 {row['p50_ms']:8.1f} ms  "
                  f"p95 {row['p95_ms']:8.1f} ms  status {row['status_counts']}")
        return 0

    if args.cmd == "ingest":
        from gatedrag.data.corpus import load_corpus, save_chunks
        chunks = load_corpus(args.docs, args.max_chars, args.overlap)
        save_chunks(chunks, args.out)
        print(f"{len(chunks)} chunks from {len({c.doc_id for c in chunks})} documents -> {args.out}")
        return 0

    if args.cmd == "pool":
        from gatedrag.evaluation.golden import load_golden
        from gatedrag.evaluation.runner import run_pool, save_pool
        cfg = load_config(args.config)
        overrides = {}
        for kv in args.set:
            k, _, v = kv.partition("=")
            cur = getattr(cfg, k)
            overrides[k] = (v.lower() == "true") if isinstance(cur, bool) else type(cur)(v)
        cfg = cfg.with_(**overrides)
        pool = run_pool(make_pipeline(args.chunks, cfg, args.generator), load_golden(args.golden), args.k, args.seed)
        save_pool(pool, args.o)
        print(f"pool: {args.k} runs x {pool['meta']['n_items']} items, config {cfg.fingerprint()} -> {args.o}")
        return 0

    if args.cmd == "gate":
        from gatedrag.evaluation.gate import decide_release, load_rule
        from gatedrag.evaluation.runner import load_pool
        pools = [load_pool(x) for x in (args.previous, args.anchor, args.candidate)]
        if len({tuple(p["meta"]["item_ids"]) for p in pools}) != 1:
            raise SystemExit("previous, anchor and candidate must be run on the same golden items")
        runs = [p["runs"][: args.k] if args.k else p["runs"] for p in pools]

        def _perf(p):
            if (p["meta"].get("concurrency") or 1) != 1:
                raise SystemExit("--perf needs pools run with concurrency 1: concurrent per-answer times include "
                                 "queueing and are not latencies (measure with `gatedrag loadtest` instead)")
            return {"latency_ms": p["meta"]["latency_ms"], "tokens": p["meta"]["tokens"]}
        perf = {"anchor": _perf(pools[1]), "candidate": _perf(pools[2])} if args.perf else None
        prev_runs, anchor_runs, cand_runs = runs
        d = decide_release(prev_runs, anchor_runs, cand_runs, load_rule(args.rule),
                           clusters=pools[0]["meta"].get("item_clusters"), perf=perf)
        import hashlib
        import os
        import time

        def _sha(path):
            return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "blocked": d.blocked, "reasons": d.reasons,
                  "rule": {"path": args.rule, "sha": _sha(args.rule)},
                  "previous": {"path": args.previous, "sha": _sha(args.previous), "config": pools[0]["meta"]["config_fingerprint"]},
                  "anchor": {"path": args.anchor, "sha": _sha(args.anchor), "config": pools[1]["meta"]["config_fingerprint"]},
                  "candidate": {"path": args.candidate, "sha": _sha(args.candidate), "config": pools[2]["meta"]["config_fingerprint"]},
                  "table": d.table}
        if args.log:
            os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
            with open(args.log, "a") as f:
                f.write(json.dumps(record) + "\n")
        print(json.dumps({"blocked": d.blocked, "reasons": d.reasons, "table": d.table}, indent=2))
        return 1 if d.blocked else 0

    if args.cmd == "experiment":
        from gatedrag.evaluation.experiment import render_markdown, run_experiment, save_results
        from gatedrag.evaluation.gate import load_rule
        from gatedrag.evaluation.runner import load_pool
        regs = {}
        for spec in args.regression:
            name, _, path = spec.partition("=")
            regs[name] = load_pool(path)
        res = run_experiment(load_pool(args.baseline), regs, load_rule(args.rule), args.n_sim, args.seed,
                             k_release=args.k_release)
        if args.power_curve:
            from gatedrag.evaluation.experiment import power_curve
            res["power_curve"] = power_curve(load_pool(args.baseline), load_rule(args.rule), seed=args.seed,
                                             k_release=args.k_release)
        if args.seed_reps > 1:
            from gatedrag.evaluation.experiment import false_block_across_seeds
            res["aa_across_seeds"] = false_block_across_seeds(load_pool(args.baseline), load_rule(args.rule),
                                                              seeds=range(args.seed_reps), n_sim=args.n_sim,
                                                              k_release=args.k_release)
        save_results(res, args.out + ".json", args.out + ".md")
        print(render_markdown(res))
        return 0

    if args.cmd == "serve":
        import os

        import uvicorn
        os.environ.update({
            "GATEDRAG_CHUNKS": os.path.abspath(args.chunks), "GATEDRAG_GENERATOR": args.generator,
            "GATEDRAG_KEYS": os.path.abspath(args.keys),
            "GATEDRAG_CONFIG": os.path.abspath(args.config) if args.config else "",
            "GATEDRAG_AUDIT": os.path.abspath(args.audit) if args.audit else "",
            "GATEDRAG_RATE_CAPACITY": str(args.rate_capacity), "GATEDRAG_RATE_REFILL": str(args.rate_refill),
        })
        uvicorn.run("gatedrag.api.server:app_factory", factory=True, host=args.host, port=args.port,
                    workers=args.workers, log_level="warning")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

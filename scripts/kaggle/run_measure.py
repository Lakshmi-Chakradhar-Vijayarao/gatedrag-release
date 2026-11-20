"""Kaggle GPU measuring run (pilot while the golden items are unreviewed LLM drafts: NOT reportable).

Runs in a Kaggle kernel with "GPU T4 x2" and internet on. The gatedrag bundle (code, configs, chunks,
golden items) is attached as a private dataset built by scripts/kaggle/bundle.sh.

Serving: vLLM (OpenAI-compatible server, tensor-parallel over both T4s, fp16), the same path as the
deployment compose file. Items are sent concurrently so vLLM batches them. If vLLM cannot start,
the script falls back to in-process Transformers (sequential, much slower) and says so in RUNINFO.

Order, most informative first. Each pool is saved as soon as it finishes; a time budget stops new
pools before Kaggle's 12-hour limit, so a timeout costs the tail of the list, never the baseline:
  phase A  Qwen2.5-7B fp16: baseline (K_BASE runs), open-loop pool (K = 2), planted regressions (K_REG), real prompt edit,
           real hybrid retrieval
  phase B  AWQ build of the same model: real_awq
  phase C  previous model version: real_model_swap
  then     noise report, 80-answer scorer-audit sample, gate-v3 experiment over finished pools
Outputs land in /kaggle/working/out (fetch with `kaggle kernels output`).
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

MODEL = os.environ.get("GATEDRAG_MODEL", "Qwen/Qwen2.5-7B-Instruct")
MODEL_AWQ = "Qwen/Qwen2.5-7B-Instruct-AWQ"
MODEL_PREV = "Qwen/Qwen2-7B-Instruct"
VLLM_SPEC = os.environ.get("GATEDRAG_VLLM", "vllm==0.6.6.post1")   # V0 engine: runs on T4 (sm75)
VLLM_PINS = ["transformers==4.47.1"]       # vLLM 0.6.6 sets no upper bound; transformers 5 breaks it
DRY = os.environ.get("GATEDRAG_DRYRUN") == "1"   # local check of this script: fake generator, no GPU
K_BASE, K_REG = (3, 3) if DRY else (6, 3)
CONCURRENCY = 4 if DRY else 16
INPUT = os.environ.get("GATEDRAG_INPUT", "/kaggle/input")
WORKDIR = Path(os.environ.get("GATEDRAG_WORKDIR", "/kaggle/working"))
BUDGET_S = 10.5 * 3600          # Kaggle stops a session at 12 h; leave room for the analysis
PORT = 8011
# planted regressions, clearest signal first, so a budget cut drops the least informative rows
PRIORITY = ["acl_off", "prompt_plain", "verifier_always_accept", "top_k_1", "max_tokens_32",
            "acl_post_filter", "top_k_2", "no_regenerate"]
T0 = time.time()

bundle = Path(glob.glob(f"{INPUT}/**/pyproject.toml", recursive=True)[0]).parent
work = WORKDIR / "gatedrag"
shutil.copytree(bundle, work, dirs_exist_ok=True)
out = WORKDIR / "out"
out.mkdir(parents=True, exist_ok=True)
os.chdir(work)
log_path = out / "run.log"


def log(msg: str) -> None:
    line = f"[{(time.time() - T0) / 60:6.1f} min] {msg}"
    print(line, flush=True)
    with open(log_path, "a") as f:
        f.write(line + "\n")


def pip(*args: str) -> bool:
    return subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args]).returncode == 0


VLLM_PY = sys.executable
if not DRY:
    pip("opentelemetry-api", "opentelemetry-sdk")
    # vLLM goes in its own venv: it pins torch/transformers versions that would otherwise replace the
    # kernel's (which sentence-transformers and the in-process fallback use). It runs as a server process.
    # Kaggle's Python (3.13) cannot build a stdlib venv (ensurepip fails), and vLLM 0.6.6 supports
    # Python <= 3.12. `uv` fetches a standalone Python 3.12 and builds the venv with it.
    venv_dir = Path("/tmp/venv_vllm")           # not in /kaggle/working: that is size-limited run output
    VLLM_OK = (pip("uv") and
               subprocess.run([sys.executable, "-m", "uv", "venv", "-q", "--python", "3.12", str(venv_dir)]).returncode == 0 and
               subprocess.run([sys.executable, "-m", "uv", "pip", "install", "-q", "--python", str(venv_dir / "bin/python"),
                               VLLM_SPEC, *VLLM_PINS]).returncode == 0)
    VLLM_PY = str(venv_dir / "bin/python")
    log(f"vLLM venv ({VLLM_SPEC}): {'ok' if VLLM_OK else 'FAILED, will fall back to transformers'}")
else:
    VLLM_OK = False
sys.path.insert(0, str(work / "src"))
os.environ["PYTHONPATH"] = str(work / "src")

import torch  # noqa: E402

from gatedrag.cli import main as cli  # noqa: E402
from gatedrag.cli import make_generator  # noqa: E402
from gatedrag.core.config import load_config  # noqa: E402
from gatedrag.data.corpus import load_chunks  # noqa: E402
from gatedrag.evaluation.golden import load_golden  # noqa: E402
from gatedrag.evaluation.runner import run_pool, save_pool  # noqa: E402
from gatedrag.models.pipeline import Pipeline  # noqa: E402
from gatedrag.models.retrieval import Retriever  # noqa: E402

gpus = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
log(f"GPUs: {gpus}")
if not DRY and sum(torch.cuda.get_device_properties(i).total_memory for i in range(len(gpus))) < 24e9:
    raise SystemExit("a 7B fp16 model needs > 24 GB of GPU memory: choose 'GPU T4 x2' in the notebook settings")

chunks = load_chunks("data/processed/chunks.jsonl")
# measuring run: the frozen, human-verified TEST split; the pilot used the unreviewed drafts
FROZEN = Path("data/golden/frozen")
golden_path = str(FROZEN / "test.jsonl") if (FROZEN / "test.jsonl").exists() else "data/golden/drafts/checked.jsonl"
golden = load_golden(golden_path)
dev_items = load_golden(FROZEN / "dev.jsonl") if (FROZEN / "dev.jsonl").exists() else []
manifest = json.loads((FROZEN / "MANIFEST.json").read_text()) if (FROZEN / "MANIFEST.json").exists() else {}
base_cfg = load_config("configs/release.toml")
regs = tomllib.loads(Path("configs/regressions.toml").read_text())["regressions"]
# releases written and sealed by a third party (docs/BLIND_REGRESSIONS.md); run if present
blind_path = next(iter(Path(INPUT).glob("**/blind_regressions.toml")), Path("configs/blind_regressions.toml"))
if DRY:                                   # never read the sealed file on a laptop, not even its names
    blind_path = Path("/nonexistent")
if blind_path.exists():
    for name, delta in tomllib.loads(blind_path.read_text()).get("blind", {}).items():
        regs[f"blind_{name}"] = delta
# releases written by a third party but received unsealed: reported separately, never as blind
tp_path = Path("configs/third_party_regressions.toml")
if tp_path.exists():
    for name, delta in tomllib.loads(tp_path.read_text()).get("third_party", {}).items():
        regs[f"tp_{name}"] = delta
order = [r for r in PRIORITY if r in regs] + [r for r in regs if r not in PRIORITY]
bm25 = Retriever(chunks)
import hashlib  # noqa: E402

from gatedrag.evaluation.golden import provenance_summary  # noqa: E402

info: dict = {"golden": golden_path, "n_items": len(golden), "golden_provenance": provenance_summary(golden),
              "golden_version": manifest.get("version_hash"), "pilot_only": manifest.get("pilot_only", True),
              "blind_file_sha256": hashlib.sha256(blind_path.read_bytes()).hexdigest() if blind_path.exists() else None,
              "gpus": gpus, "torch": torch.__version__, "k_baseline": K_BASE, "k_regression": K_REG,
              "concurrency": CONCURRENCY, "servers": [], "pools": {}}
_commit = bundle / "CODE_COMMIT.txt"            # written by bundle.sh: hash, then count of uncommitted files
if _commit.exists():
    _c = _commit.read_text().split()
    info["code_commit"] = _c[0]
    info["code_uncommitted_files"] = int(_c[1]) if len(_c) > 1 else None


def start_server(model: str, *extra: str):
    """Start vLLM; return (process, generator) or (None, None) if it does not come up."""
    cmd = [VLLM_PY, "-m", "vllm.entrypoints.openai.api_server", "--model", model, "--port", str(PORT),
           "--tensor-parallel-size", str(max(1, len(gpus))), "--dtype", "half", "--max-model-len", "4096",
           "--gpu-memory-utilization", "0.90", "--seed", "0", *extra]
    srv_log = open(out / f"vllm_{model.split('/')[-1]}.log", "w")
    # own process group: vLLM forks tensor-parallel workers that hold GPU memory; stop_server kills the group
    proc = subprocess.Popen(cmd, stdout=srv_log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(180):                       # up to 30 min: download + load + warm-up
        if proc.poll() is not None:
            log(f"vLLM for {model} exited with code {proc.returncode}; see {srv_log.name}")
            return None, None
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5)
            log(f"vLLM serving {model}")
            info["servers"].append({"model": model, "args": list(extra)})
            return proc, make_generator(f"openai:http://127.0.0.1:{PORT}|{model}")
        except Exception:
            time.sleep(10)
    proc.terminate()
    log(f"vLLM for {model} did not come up in 30 min")
    return None, None


def gpu_used_mib() -> list[int]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True)
    return [int(x) for x in out.stdout.split()] if out.returncode == 0 else []


def stop_server(proc) -> None:
    """Kill vLLM and its tensor-parallel workers (the whole process group), then wait until the GPUs
    are actually free: terminating only the parent left the workers holding ~14 GB, and every later
    server died with CUDA out of memory."""
    if proc is None:
        return
    import signal
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(60)
            break
        except subprocess.TimeoutExpired:
            continue
    for _ in range(60):                        # up to 5 min for the driver to release memory
        used = gpu_used_mib()
        if not used or max(used) < 1500:
            return
        time.sleep(5)
    log(f"warning: GPU memory still in use after stopping vLLM: {gpu_used_mib()} MiB")


_hybrid: list = []                        # built once, on first use (downloads the embedding model)


def retriever_for(cfg):
    """BM25 for BM25 configs; the hybrid retriever for any config with use_dense, including releases
    written by third parties."""
    if not cfg.use_dense:
        return bm25
    if not _hybrid:
        if DRY:
            raise RuntimeError("dry run: no embedding model is loaded on the laptop")
        from gatedrag.models.retrieval import sentence_transformer_embedder
        _hybrid.append(Retriever(chunks, embed=sentence_transformer_embedder()))
    return _hybrid[0]


def run(name: str, cfg, k: int, generator, retriever=None, conc: int = CONCURRENCY) -> bool:
    path = out / f"pool_{name}.json"
    if path.exists():
        return True
    if time.time() - T0 > BUDGET_S:
        log(f"skip {name}: time budget spent")
        return False
    t = time.time()
    try:
        save_pool(run_pool(Pipeline(retriever or retriever_for(cfg), generator, cfg), golden, k=k, concurrency=conc), path)
    except Exception as e:                     # one failed configuration must not lose the others
        log(f"{name} FAILED: {type(e).__name__}: {e}")
        return False
    mins = (time.time() - t) / 60
    info["pools"][name] = {"k": k, "minutes": round(mins, 1), "generator": generator.name}
    log(f"{name}: K={k} done in {mins:.1f} min ({mins / k:.1f} min per run)")
    return True


# ---- phase A: the release model ---------------------------------------------------------------
proc, gen = (None, make_generator("fake")) if DRY else start_server(MODEL)
conc = CONCURRENCY
if gen is None:                                # fallback: in-process, sequential
    info["fallback"] = "transformers in-process (vLLM unavailable): sequential, slower"
    gen, conc = make_generator(f"local:{MODEL}"), 1
    log(info["fallback"])

run("baseline", base_cfg, K_BASE, gen, conc=conc)
# open loop: every generated answer shipped and scored -> unbiased calibration data + cost sweep
run("open_loop", base_cfg.with_(router="open_loop"), 2, gen, conc=conc)
if dev_items:   # calibration: fit on an open-loop DEV pool, report ECE on the open-loop TEST pool
    dev_path = out / "pool_open_loop_dev.json"
    if not dev_path.exists():
        save_pool(run_pool(Pipeline(bm25, gen, base_cfg.with_(router="open_loop")), dev_items, k=2,
                           concurrency=conc), dev_path)
        log("open_loop_dev: K=2 done")
done_pools = [(v["minutes"], v["k"]) for v in info["pools"].values()]
per_run = sum(m for m, _ in done_pools) / max(1, sum(k for _, k in done_pools))
n_left = K_REG * (len(order) + 4)
log(f"ETA for the remaining {n_left} runs at this speed: about {per_run * n_left / 60:.1f} h")
done = [n for n in order if run(n, base_cfg.with_(**regs[n]), K_REG, gen, conc=conc)]
if run("real_prompt_edit", base_cfg.with_(prompt_variant="grounded_v2"), K_REG, gen, conc=conc):
    done.append("real_prompt_edit")
if run("real_hybrid", base_cfg.with_(use_dense=True), K_REG, gen, conc=conc):
    done.append("real_hybrid")
stop_server(proc)

# ---- phases B and C: real model changes (vLLM only; too slow in-process) -------------------------
if not DRY and VLLM_OK and "fallback" not in info:
    for name, model, extra in (("real_awq", MODEL_AWQ, ("--quantization", "awq")),
                               ("real_model_swap", MODEL_PREV, ())):
        if time.time() - T0 > BUDGET_S:
            log(f"skip {name}: time budget spent")
            continue
        proc, gen = start_server(model, *extra)
        if gen is not None and run(name, base_cfg, K_REG, gen):
            done.append(name)
        stop_server(proc)

# ---- analysis ----------------------------------------------------------------------------------
info.update({"model": "fake (dry run)" if DRY else MODEL, "changes_done": done,
             "elapsed_h": round((time.time() - T0) / 3600, 2)})
if VLLM_OK:
    info["vllm"] = VLLM_SPEC
(out / "RUNINFO.json").write_text(json.dumps(info, indent=2))

base = str(out / "pool_baseline.json")
if not Path(base).exists():                    # analysis needs the baseline; report what exists and stop cleanly
    log("no baseline pool: skipping noise, audit sample and gate experiment")
    print(json.dumps(info, indent=2))
    raise SystemExit(0)
with open(out / "noise.json", "w") as f:
    subprocess.run([sys.executable, "-m", "gatedrag", "noise", base], check=True, stdout=f)
cli(["audit-sample", base, "--golden", golden_path, "-n", "80", "-o", str(out / "scorer_audit.jsonl")])
if (out / "pool_open_loop_dev.json").exists():
    cli(["calibrate", str(out / "pool_open_loop_dev.json"), "--kind", "isotonic", "-o", str(out / "calibrator_dev.json")])
    with open(out / "calibration_test.json", "w") as f:
        subprocess.run([sys.executable, "-m", "gatedrag", "calibration-report", "--calibration",
                        str(out / "calibrator_dev.json"), str(out / "pool_open_loop.json")], check=False, stdout=f)
if manifest:
    with open(out / "golden_check.txt", "w") as f:
        subprocess.run([sys.executable, "-m", "gatedrag", "golden-check", "--manifest", str(FROZEN / "MANIFEST.json"),
                        "--chunks", "data/processed/chunks.jsonl"], check=False, stdout=f)
if done:
    cli(["experiment", "--rule", "configs/gate_rule.toml", "--baseline", base,
         *[a for n in done for a in ("--regression", f"{n}={out / f'pool_{n}.json'}")],
         "--n-sim", "200" if DRY else "2000", "--power-curve", "-o", str(out / "gate_experiment")])
log("finished")
print(json.dumps(info, indent=2))

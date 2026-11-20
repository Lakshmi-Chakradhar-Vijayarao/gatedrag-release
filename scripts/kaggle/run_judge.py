"""Kaggle: grade stored pools with an LLM judge (Mistral-7B-Instruct-v0.3, a different model family
from the Qwen system under test). Evaluator-side only: no system output is regenerated.

Bundle (private dataset): src/, pyproject.toml, golden/{dev,test}.jsonl, pools/*.json.
Output: /kaggle/working/out/<pool>.json with `correct_judge` on every row, plus run.log.
"""

from __future__ import annotations

import glob
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

JUDGE = os.environ.get("GATEDRAG_JUDGE", "mistralai/Mistral-7B-Instruct-v0.3")
VLLM = ["vllm==0.6.6.post1", "transformers==4.47.1"]
PORT = 8013
OUT = Path("/kaggle/working/out")
OUT.mkdir(parents=True, exist_ok=True)
T0 = time.time()
bundle = Path(glob.glob("/kaggle/input/**/pyproject.toml", recursive=True)[0]).parent


def log(msg: str) -> None:
    line = f"[{(time.time() - T0) / 60:6.1f} min] {msg}"
    print(line, flush=True)
    with open(OUT / "run.log", "a") as f:
        f.write(line + "\n")


subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv", "opentelemetry-api", "opentelemetry-sdk", "httpx"],
               check=True)
venv = Path("/tmp/venv_vllm")
subprocess.run([sys.executable, "-m", "uv", "venv", "-q", "--python", "3.12", str(venv)], check=True)
subprocess.run([sys.executable, "-m", "uv", "pip", "install", "-q", "--python", str(venv / "bin/python"), *VLLM], check=True)
log("vLLM venv ok")
sys.path.insert(0, str(bundle / "src"))

from gatedrag.cli import make_generator  # noqa: E402
from gatedrag.evaluation.golden import load_golden  # noqa: E402
from gatedrag.evaluation.judge import judge_pool  # noqa: E402
from gatedrag.evaluation.runner import load_pool, save_pool  # noqa: E402

golden = load_golden(bundle / "golden/dev.jsonl") + load_golden(bundle / "golden/test.jsonl")
n_gpu = int(subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.count("GPU "))
cmd = [str(venv / "bin/python"), "-m", "vllm.entrypoints.openai.api_server", "--model", JUDGE, "--port", str(PORT),
       "--dtype", "half", "--max-model-len", "4096", "--tensor-parallel-size", str(max(1, n_gpu)), "--seed", "0"]
srv = subprocess.Popen(cmd, stdout=open(OUT / "vllm.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
for _ in range(180):
    if srv.poll() is not None:
        raise SystemExit("vLLM exited; see vllm.log")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5)
        break
    except Exception:
        time.sleep(10)
log(f"serving judge {JUDGE} on {n_gpu} GPU(s)")
gen = make_generator(f"openai:http://127.0.0.1:{PORT}|{JUDGE}")
summary = {}
for path in sorted((bundle / "pools").glob("*.json")):
    pool = judge_pool(load_pool(path), golden, gen, concurrency=16)
    save_pool(pool, OUT / path.name)
    summary[path.name] = pool["meta"]["judge"]
    log(f"{path.name}: {pool['meta']['judge']}")
os.killpg(os.getpgid(srv.pid), signal.SIGTERM)
(OUT / "JUDGE_INFO.json").write_text(json.dumps({"judge": JUDGE, "vllm": VLLM, "pools": summary}, indent=1))
log("finished")

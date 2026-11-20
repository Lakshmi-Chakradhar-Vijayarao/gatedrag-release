import json, sys
from pathlib import Path
from gatedrag.evaluation.experiment import noise_shift
from gatedrag.evaluation.gate import load_rule
from gatedrag.evaluation.runner import load_pool
D = Path("data/interim/runs/kaggle_qwen7b_measure/out"); seed = int(sys.argv[1])
pools = {p.stem[5:]: load_pool(p) for p in sorted(D.glob("pool_*.json")) if p.stem[5:] not in ("open_loop", "open_loop_dev")}
res = noise_shift(pools, load_rule("configs/gate_rule.toml"), fixed_drop=float(sys.argv[2]), n_sim=2000, seed=seed)
Path(sys.argv[3]).write_text(json.dumps(res))

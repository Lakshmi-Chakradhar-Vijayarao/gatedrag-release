#!/usr/bin/env bash
# Build the private Kaggle dataset + kernel folders for the GPU measuring run, and push them if asked.
#   KAGGLE_USER=<your username> ./scripts/kaggle/bundle.sh          # build only (dist/kaggle/)
#   KAGGLE_USER=<your username> ./scripts/kaggle/bundle.sh --push   # build, upload dataset, start kernel
# Needs a logged-in kaggle CLI on your PRIMARY account (`kaggle auth login`) for --push.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${KAGGLE_USER:?set KAGGLE_USER to your Kaggle username}"
D=dist/kaggle/dataset; K=dist/kaggle/kernel
rm -rf dist/kaggle && mkdir -p "$D/data/processed" "$D/data/golden/drafts" "$K"
cp -R src configs pyproject.toml README.md LICENSE "$D/"
# record the exact code: commit hash, and whether the working tree had uncommitted changes
{ git rev-parse HEAD; git status --porcelain -- src configs scripts | wc -l | tr -d " "; } > "$D/CODE_COMMIT.txt"
find "$D/src" -name __pycache__ -prune -exec rm -rf {} +
cp data/processed/chunks.jsonl "$D/data/processed/"
cp data/golden/drafts/checked.jsonl "$D/data/golden/drafts/"
if [ -d data/golden/frozen ]; then mkdir -p "$D/data/golden/frozen" && cp data/golden/frozen/*.jsonl data/golden/frozen/MANIFEST.json "$D/data/golden/frozen/"; fi
# the sealed blind set travels unread; it is matched against its recorded hash after the gate decides
if [ -f data/sealed/blind_regressions.toml ]; then mkdir -p "$D/sealed" && cp data/sealed/blind_regressions.toml "$D/sealed/"; fi
rm -f "$D/configs/keys.toml"            # never ship real API keys
cat > "$D/dataset-metadata.json" <<JSON
{"title": "gatedrag-bundle", "id": "$KAGGLE_USER/gatedrag-bundle", "licenses": [{"name": "Apache 2.0"}]}
JSON
cp scripts/kaggle/run_measure.py "$K/"
cat > "$K/kernel-metadata.json" <<JSON
{"id": "$KAGGLE_USER/gatedrag-measure", "title": "gatedrag-measure", "code_file": "run_measure.py",
 "language": "python", "kernel_type": "script", "is_private": true, "enable_gpu": true,
 "enable_internet": true, "dataset_sources": ["$KAGGLE_USER/gatedrag-bundle"]}
JSON
(cd "$D" && find . -type f ! -name dataset-metadata.json | sort | xargs shasum -a 256) > dist/kaggle/BUNDLE_SHA256.txt
echo "built dist/kaggle ($(du -sh "$D" | cut -f1) dataset)"
if [[ "${1:-}" == "--push" ]]; then
  if kaggle datasets status "$KAGGLE_USER/gatedrag-bundle" >/dev/null 2>&1; then
    kaggle datasets version -p "$D" -m "bundle $(date +%F)" --dir-mode zip
  else
    kaggle datasets create -p "$D" --dir-mode zip      # private by default
  fi
  echo "waiting for the dataset to finish processing..."; sleep 60
  kaggle kernels push -p "$K" --accelerator NvidiaTeslaT4
  echo "started. status: kaggle kernels status $KAGGLE_USER/gatedrag-measure"
  echo "fetch:   kaggle kernels output $KAGGLE_USER/gatedrag-measure -p data/interim/runs/kaggle_qwen7b"
fi

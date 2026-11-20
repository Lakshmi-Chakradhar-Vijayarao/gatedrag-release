#!/usr/bin/env bash
# Fetch the evaluation corpus: NATS documentation (https://github.com/nats-io/nats.docs),
# Apache License 2.0, (c) The NATS Authors. Pinned so every run sees identical documents.
set -euo pipefail
COMMIT=f115becf6563e3bbe16bb94cbf87bfceb84199c1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/data/raw/nats.docs"
OUT="$ROOT/data/interim/corpus"
if [ ! -d "$SRC/.git" ]; then
  git init -q "$SRC" && git -C "$SRC" remote add origin https://github.com/nats-io/nats.docs.git
fi
git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"
git -C "$SRC" checkout -q "$COMMIT"
rm -rf "$OUT/nats" && mkdir -p "$OUT/nats"
# English product documentation only (no translations, legacy pages, release notes or assets)
for d in nats-concepts running-a-nats-service using-nats reference; do
  cp -R "$SRC/$d" "$OUT/nats/"
done
cp "$SRC/overview.md" "$SRC/LICENSE" "$OUT/nats/"
# Test documents (fictional, written for this project): access-controlled pages and one planted injection
cp -R "$ROOT/data/test_docs/." "$OUT/"
echo "corpus at $OUT (nats.docs @ ${COMMIT:0:7})"

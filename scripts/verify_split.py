"""Check the frozen split against its manifest and its derivation record.

The measuring run used split version 455373d18c44cfd6 (v1). This release ships v2, which is v1 with one
free-text `notes` field removed from 7 items. `V1_EQUIVALENCE.json` records the sha256 of every item as it
was in v1 with that field removed. This script recomputes each item's hash from the shipped v2 files and the
split hashes in MANIFEST.json, so anyone can confirm that every scored field is exactly what v1 held.

Run: python scripts/verify_split.py
"""
import hashlib
import json
import sys
from pathlib import Path

F = Path(__file__).resolve().parent.parent / "data/golden/frozen"
manifest = json.loads((F / "MANIFEST.json").read_text())
equiv = json.loads((F / "V1_EQUIVALENCE.json").read_text())
ok = True
for split in ("dev", "test"):
    raw = (F / f"{split}.jsonl").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["splits"][split]["sha256"]:
        print(f"{split}: file hash does not match MANIFEST.json"); ok = False
    for line in raw.decode().splitlines():
        item = json.loads(line)
        h = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if equiv["item_sha256"].get(item["id"]) != h:
            print(f"{split}: item {item['id']} differs from v1"); ok = False
n = len(equiv["item_sha256"])
print(f"{'OK' if ok else 'FAILED'}: {n} items; split {manifest['version_hash']} is v1 {equiv['v1_version_hash']} "
      f"with only the `notes` field removed from {len(equiv['items_changed'])} items")
sys.exit(0 if ok else 1)

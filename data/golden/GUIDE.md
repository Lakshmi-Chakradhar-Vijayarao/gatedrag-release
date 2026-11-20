# Writing the golden set (human work; do it before any tuning)

**Target size:** about 300–400 items. The final number is set by power (`docs/PREREG.md` §5) after a pilot on the real model.

One JSON object per line, in `data/golden/golden.jsonl`. Every field is checked by `gatedrag.evaluation.golden.load_golden`.

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique and stable, e.g. `limits-007` |
| `question` | yes | Phrased as a real user would ask it, not copied from the doc |
| `answerable` | yes | `true` if the corpus contains the answer |
| `gold_docs` | if answerable | Doc ids (path without extension) that contain the answer |
| `reference` | if answerable | The **key facts only**, e.g. `256 KB`. Scoring checks these facts appear in the answer |
| `slice` | no | `general`, `multi-hop`, `unanswerable` or `security` |
| `groups` | no | Access groups of the asking user (default `["public"]`) |
| `forbidden_docs` | security items | Docs this user must never retrieve |
| `canary` | injection items | A string that appears only if an instruction planted in a document was followed |
| `cluster` | no | Correlation group; defaults to the first gold doc |
| `provenance` | yes | `human` (you wrote it), `human-verified-draft` (you checked and fixed a drafted item), or `synthetic-fixture` (tests only; **never reported**) |

## Mix to aim for (adjust to the corpus)

- About 60% answerable, single document.
- About 15% multi-hop (the answer needs two passages).
- About 15% unanswerable: plausible questions the docs do not answer. These measure over-confidence.
- About 10% security:
  - access-control questions asked by users without the right group;
  - injection items, built by planting one instruction plus a unique canary in a test document.

## Rules

1. Write or verify every item **before** looking at any system output. Never edit an item because the system got it wrong.
2. A separate human-labelled subset (about 100 answers, each labelled supported or unsupported) validates the verifier. Record agreement (Cohen's kappa) and the threshold, fixed in advance.
3. Keep a held-out 20% split that is never used while choosing configurations.

## Sizing and splitting (gate v3; see docs/PREREG.md)

**Test split size** comes from *measured* noise.
1. Run `gatedrag pool` with K ≥ 5 unchanged runs.
2. Run `gatedrag noise pool.json`. It reports d and the n each detectable drop requires, at α = 0.025 per comparison and 80% power.
3. **Example:** d = 0.15 needs about 470 test items for a 5-point drop.

**Development split:** about 150 items, for calibration and configuration choices only. It is never used to report results.

**Injection subset:** about 50 items with canaries, to detect an injection-following rate rising from about 5% to 25% (paired test). With 1–2 items the gate cannot see injection regressions at all (pilot known-miss).

**Document cap:** at most 5 items per source document.

**Freeze:** `gatedrag golden-freeze golden.jsonl -o data/golden/frozen`.
- It splits by whole documents, stratified by slice, and writes `MANIFEST.json` with SHA-256 hashes.
- It refuses unverified items; `--pilot` is only for sizing runs, and the manifest marks those runs `pilot_only`.

## Drafts in this repository

`data/golden/drafts/part_*.jsonl` hold 341 LLM-drafted items (provenance `llm-draft`). `checked.jsonl` is the same set after automatic checks, with flags and with notes from `reviewer_notes.json`. Review it with `gatedrag review data/golden/drafts/checked.jsonl -o data/golden/golden.jsonl`. Rejected or unreviewed drafts are never used for a reported result.

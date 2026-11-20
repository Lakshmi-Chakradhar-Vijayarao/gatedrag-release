PY ?= .venv/bin/python
export PYTHONPATH := src
GENERATOR ?= fake

.PHONY: install test lint corpus ingest check-drafts serve loadtest docker-build aws-plan reproduce reproduce-smoke kaggle-bundle kaggle-push kaggle-dryrun

install:        ## create the venv and install with dev + dense extras
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev,dense]"

test:           ## unit + end-to-end tests (offline, no model downloads)
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests
	$(PY) -m mypy src --ignore-missing-imports

corpus:         ## fetch the pinned NATS docs + test documents into data/interim/corpus
	./scripts/fetch_corpus.sh

ingest: corpus  ## chunk the corpus into data/processed/chunks.jsonl
	$(PY) -m gatedrag ingest data/interim/corpus -o data/processed/chunks.jsonl

check-drafts:   ## automatic checks on golden-set drafts (flags only, never verifies)
	$(PY) -m gatedrag check-drafts --drafts data/golden/drafts --chunks data/processed/chunks.jsonl -o data/golden/drafts/checked

serve:          ## local API; GENERATOR=openai:URL|MODEL for a real model
	$(PY) -m gatedrag serve --chunks data/processed/chunks.jsonl --config configs/release.toml \
	  --keys configs/keys.example.toml --generator "$(GENERATOR)" --audit data/processed/audit.db

loadtest:       ## concurrency sweep against a running server
	$(PY) -m gatedrag loadtest --url http://127.0.0.1:8000 --key k-load --questions data/golden/drafts/checked.jsonl \
	  --concurrency 1,4,16 --requests 320 -o data/processed/perf/loadtest.json

docker-build:
	docker build -f docker/Dockerfile.serve -t gatedrag .

aws-plan:       ## dry run: quota, AMI and cost cap for the GPU measuring run (launches nothing)
	./scripts/aws_launch_ec2.sh

reproduce:      ## full measurement: GENERATOR="openai:URL|MODEL" make reproduce (writes docs/RESULTS.md)
	./scripts/reproduce.sh

reproduce-smoke: ## the same pipeline on the synthetic fixture with the fake generator (fast; NOT reportable)
	PYTHONPATH=src $(PY) -m gatedrag ingest tests/fixtures/corpus -o data/interim/fixture_chunks.jsonl
	GENERATOR=fake CHUNKS=data/interim/fixture_chunks.jsonl GOLDEN=tests/fixtures/golden_synthetic.jsonl \
	  K=4 N_SIM=200 OUT=data/interim/runs/reproduce_smoke RESULTS=data/interim/runs/reproduce_smoke/RESULTS.md ./scripts/reproduce.sh

kaggle-bundle:  ## build the private Kaggle dataset + kernel (KAGGLE_USER=name)
	./scripts/kaggle/bundle.sh

kaggle-push:    ## build, upload and start the GPU measuring run on Kaggle T4 x2 (needs `kaggle auth login`)
	./scripts/kaggle/bundle.sh --push

kaggle-dryrun:  ## run the Kaggle script locally with the fake generator (checks the script, no GPU)
	KAGGLE_USER=dryrun ./scripts/kaggle/bundle.sh
	rm -rf data/interim/kaggle_dry && mkdir -p data/interim/kaggle_dry/input
	cp -R dist/kaggle/dataset data/interim/kaggle_dry/input/gatedrag-bundle
	GATEDRAG_DRYRUN=1 GATEDRAG_INPUT=data/interim/kaggle_dry/input GATEDRAG_WORKDIR=$(CURDIR)/data/interim/kaggle_dry/work \
	  $(PY) scripts/kaggle/run_measure.py

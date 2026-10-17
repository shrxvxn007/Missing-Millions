PYTHON ?= python3
VENV_PYTHON := .venv/bin/python

.PHONY: setup prepare-demo acquire-real prepare-real dev build serve test test-e2e

setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements.txt
	npm --prefix apps/web ci

# Explicit fixture generation. Never called automatically after a source error.
prepare-demo:
	$(VENV_PYTHON) -m pipeline.build_demo --mode synthetic

acquire-real:
	$(VENV_PYTHON) -m pipeline.ingest.acquire_sources --sources all --size-m 10000 --out data/raw/turkana-real

prepare-real:
	$(VENV_PYTHON) -m pipeline.build_demo --mode real --source data/raw/turkana-real

dev:
	$(VENV_PYTHON) scripts/dev.py

build:
	npm --prefix apps/web run build

serve:
	$(VENV_PYTHON) -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000

test:
	$(VENV_PYTHON) -m pytest tests -q

test-e2e:
	npm --prefix apps/web run test:e2e

# Convenience launcher — run these from the project folder, e.g. `make ui`.
# No need to activate the venv; each target uses .venv/bin directly.

PY := .venv/bin/python
ST := .venv/bin/streamlit
UV := .venv/bin/uvicorn

.PHONY: ui dev cli api seed extract test eval help

help:
	@echo "make ui       # launch the Streamlit web app (http://localhost:8501)"
	@echo "make cli       # interactive command-line agent"
	@echo "make api       # run the FastAPI backend (http://localhost:8000)"
	@echo "make seed      # (re)create schema + ingest docs + seed rules"
	@echo "make extract   # ingest + LLM-extract structured rules from docs (needs key)"
	@echo "make test      # run unit + retrieval tests"
	@echo "make eval      # deterministic evals (calculation + retrieval)"

ui dev:
	$(ST) run app/streamlit_app.py

cli:
	$(PY) cli.py

api:
	$(UV) backend.main:app --port 8000 --reload

seed:
	$(PY) seed.py

extract:
	$(PY) seed.py --extract

test:
	$(PY) tests/test_calculator.py && $(PY) tests/test_retrieval.py

eval:
	$(PY) evaluation/calculation_eval.py && $(PY) evaluation/rag_eval.py

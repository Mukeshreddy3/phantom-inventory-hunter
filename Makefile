.PHONY: setup data test demo clean

PY := .venv/bin/python

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

data:
	$(PY) -m phantom_hunter.generator

test:
	$(PY) -m pytest tests/ -q

demo: data
	$(PY) -m phantom_hunter.reconcile --summary

clean:
	rm -rf data .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

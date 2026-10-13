.PHONY: setup data test demo agent loop dashboard clean

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

agent: data
	$(PY) -m phantom_hunter.agent --samples 10

loop: data
	$(PY) -m phantom_hunter.runner --days 3

dashboard:
	$(PY) -m phantom_hunter.dashboard --port 8000

clean:
	rm -rf data .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

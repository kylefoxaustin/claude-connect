.PHONY: install run dev test clean

PORT ?= 8765
HOST ?= 127.0.0.1

install:
	pip install -e ".[dev]"

run:
	uvicorn conductor.main:app --host $(HOST) --port $(PORT)

dev:
	uvicorn conductor.main:app --host $(HOST) --port $(PORT) --reload

test:
	pytest -q

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

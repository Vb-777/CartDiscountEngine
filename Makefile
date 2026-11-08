.PHONY: install test lint typecheck cov run all

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .

typecheck:
	mypy

cov:
	pytest -q --cov=app --cov-report=term-missing

run:
	uvicorn app.main:app --reload --port 8000

all: lint typecheck cov

.PHONY: api check test eval-smoke

api:
	uv run --no-sync uvicorn blue_wren.api.main:app --reload

check:
	uv run --no-sync ruff check .
	uv run --no-sync mypy

test:
	uv run --no-sync coverage run -m pytest
	uv run --no-sync coverage report

eval-smoke:
	uv run --no-sync pytest -q tests/test_event_replay.py

.PHONY: check test eval-smoke

check:
	uv run ruff check .
	uv run mypy

test:
	uv run coverage run -m pytest
	uv run coverage report

eval-smoke:
	uv run pytest -q tests/test_event_replay.py

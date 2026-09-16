.PHONY: api check test eval-smoke

BLUE_WREN_DB ?= blue-wren.db

api:
	BLUE_WREN_DB=$(BLUE_WREN_DB) uv run --no-sync uvicorn blue_wren.api.main:app --reload

check:
	uv run --no-sync ruff check .
	uv run --no-sync mypy

test:
	uv run --no-sync coverage run -m pytest
	uv run --no-sync coverage report

eval-smoke:
	uv run --no-sync python -m blue_wren.cli.eval_smoke \
		tests/fixtures/acme_q2_2026.json \
		tests/fixtures/acme_q2_2026.expected.json \
		tests/fixtures/acme_q2_2026.sources.json

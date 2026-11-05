import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from blue_wren.application.analysis import propose_observations
from blue_wren.application.analysis_codec import decode_run, encode_run
from blue_wren.application.analysis_store import (
    AnalysisRunConflict,
    AnalysisRunNotFound,
    AnalysisRunRepository,
)
from blue_wren.domain.analysis import AnalysisRun, AnalysisScope, RunBudget, SourceSpan
from blue_wren.domain.findings import BaselineObservation
from blue_wren.domain.provider import ProviderResponse, ProviderUsage
from blue_wren.infrastructure.memory_analysis_store import InMemoryAnalysisRunRepository
from blue_wren.infrastructure.sqlite_analysis_store import SqliteAnalysisRunRepository
from blue_wren.infrastructure.stub_analysis_provider import StubAnalysisProvider

START = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SECRET = "ZEBRA-CONFIDENTIAL-TEXT"
BUDGET = RunBudget(4000, 800, 2, 0, Decimal("60"))
SCOPE = AnalysisScope(
    event_id="acme-q2-2026",
    company_id="ACME-AU",
    cutoff_at=START - timedelta(hours=9),
    metrics=("revenue",),
    units=("AUD_millions",),
    spans=(
        SourceSpan(
            "acme-q2-results",
            "acme-q2-results:v1",
            1,
            1,
            "page=1;span=1",
            f"Revenue 125.0 {SECRET}",
        ),
    ),
    baselines=(
        BaselineObservation("revenue", Decimal("120.0"), "AUD_millions", "2026-Q2", "reported"),
    ),
)


class Clock:
    def __init__(self) -> None:
        self.current = START

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


class Sleeper:
    def sleep(self, seconds: Decimal) -> None:
        return None


def _run(key: str = "job-1", budget: RunBudget = BUDGET) -> AnalysisRun:
    response = ProviderResponse(
        text=json.dumps(
            {
                "observations": [
                    {
                        "metric": "revenue",
                        "value_text": "125.0",
                        "unit": "AUD_millions",
                        "period": "2026-Q2",
                        "basis": "reported",
                        "document_version_id": "acme-q2-results:v1",
                        "locator": "page=1;span=1",
                    }
                ]
            }
        ),
        usage=ProviderUsage(100, 40),
        stop_reason="end_turn",
        model_id="model-x",
        request_id="req-1",
    )
    return propose_observations(
        SCOPE,
        provider=StubAnalysisProvider([response]),
        model_id="model-x",
        budget=budget,
        idempotency_key=key,
        clock=Clock(),
        sleeper=Sleeper(),
        nonce="n1",
    )


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> AnalysisRunRepository:
    if request.param == "memory":
        return InMemoryAnalysisRunRepository()
    return SqliteAnalysisRunRepository(tmp_path / "runs.db")


def test_codec_round_trips_a_run_without_span_or_prompt_text() -> None:
    run = _run()

    payload = encode_run(run)
    text = json.dumps(payload)

    assert decode_run(json.loads(text)) == run
    assert SECRET not in text
    assert "Revenue 125.0" not in text
    assert "source-span" not in text


def test_codec_rejects_unknown_schema_version() -> None:
    payload = encode_run(_run())
    payload["schema_version"] = 99

    with pytest.raises(ValueError, match="schema_version"):
        decode_run(payload)


def test_create_then_get_by_id_and_key(repository: AnalysisRunRepository) -> None:
    run = _run()

    assert repository.create(run) == run
    assert repository.get(run.run_id) == run
    assert repository.get_by_idempotency_key("job-1") == run


def test_replaying_the_same_request_returns_the_stored_run(
    repository: AnalysisRunRepository,
) -> None:
    first = repository.create(_run())
    again = _run()

    assert repository.create(again) == first
    assert len(repository.list_for_event("acme-q2-2026")) == 1


def test_reusing_a_key_for_a_different_request_conflicts(
    repository: AnalysisRunRepository,
) -> None:
    repository.create(_run())

    with pytest.raises(AnalysisRunConflict, match="job-1"):
        repository.create(_run(budget=replace(BUDGET, max_output_tokens=1)))


def test_list_for_event_orders_by_start_time(repository: AnalysisRunRepository) -> None:
    second = _run("job-2")
    first = replace(_run("job-1"), started_at=START - timedelta(hours=1))
    repository.create(second)
    repository.create(first)

    assert [run.run_id for run in repository.list_for_event("acme-q2-2026")] == [
        first.run_id,
        second.run_id,
    ]
    assert repository.list_for_event("other") == ()


def test_unknown_run_raises_not_found(repository: AnalysisRunRepository) -> None:
    with pytest.raises(AnalysisRunNotFound):
        repository.get("missing")
    with pytest.raises(AnalysisRunNotFound):
        repository.get_by_idempotency_key("missing")


def test_sqlite_runs_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "runs.db"
    run = _run()
    first = SqliteAnalysisRunRepository(path)
    first.create(run)
    first.close()

    assert SqliteAnalysisRunRepository(path).get(run.run_id) == run

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from blue_wren.application.analysis import (
    propose_observations,
    request_digest_for,
    run_id_for,
)
from blue_wren.application.analysis_provider import (
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
)
from blue_wren.domain.analysis import (
    AnalysisScope,
    ProposalRejectionCode,
    RunBudget,
    RunFailureCode,
    RunStatus,
    SourceSpan,
)
from blue_wren.domain.findings import BaselineObservation
from blue_wren.domain.provider import ProviderResponse, ProviderUsage
from blue_wren.infrastructure.stub_analysis_provider import StubAnalysisProvider

START = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
BUDGET = RunBudget(
    max_prompt_chars=4000,
    max_output_tokens=800,
    max_provider_calls=3,
    max_tool_calls=0,
    max_seconds=Decimal("60"),
)
SCOPE = AnalysisScope(
    event_id="acme-q2-2026",
    company_id="ACME-AU",
    cutoff_at=START - timedelta(hours=9),
    metrics=("ebitda", "revenue"),
    units=("AUD_millions",),
    spans=(
        SourceSpan(
            "acme-q2-results", "acme-q2-results:v1", 1, 1, "page=1;span=1", "Revenue 125.0."
        ),
        SourceSpan("acme-q2-results", "acme-q2-results:v1", 1, 2, "page=1;span=2", "EBITDA 30.0."),
    ),
    baselines=(
        BaselineObservation("revenue", Decimal("120.0"), "AUD_millions", "2026-Q2", "reported"),
        BaselineObservation("ebitda", Decimal("32.0"), "AUD_millions", "2026-Q2", "reported"),
    ),
)


class FakeClock:
    def __init__(self, step: Decimal = Decimal("1")) -> None:
        self.current = START
        self.step = step

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=float(self.step))
        return value


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[Decimal] = []

    def sleep(self, seconds: Decimal) -> None:
        self.calls.append(seconds)


class Cancelled:
    def cancelled(self) -> bool:
        return True


def _observation(metric: str, value: str, locator: str) -> dict[str, str]:
    return {
        "metric": metric,
        "value_text": value,
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
        "document_version_id": "acme-q2-results:v1",
        "locator": locator,
    }


def _response(*observations: dict[str, str], stop_reason: str = "end_turn") -> ProviderResponse:
    return ProviderResponse(
        text=json.dumps({"observations": list(observations)}),
        usage=ProviderUsage(input_tokens=100, output_tokens=40),
        stop_reason=stop_reason,
        model_id="model-x",
        request_id="req-1",
    )


FULL = _response(
    _observation("revenue", "125.0", "page=1;span=1"),
    _observation("ebitda", "30.0", "page=1;span=2"),
)


def _run(script: list[ProviderResponse | Exception], **overrides: object):  # type: ignore[no-untyped-def]
    stub = StubAnalysisProvider(script)  # type: ignore[arg-type]
    sleeper = FakeSleeper()
    arguments: dict[str, object] = {
        "provider": stub,
        "model_id": "model-x",
        "budget": BUDGET,
        "idempotency_key": "job-1",
        "clock": FakeClock(),
        "sleeper": sleeper,
        "nonce": "n1",
    }
    arguments.update(overrides)
    return propose_observations(SCOPE, **arguments), stub, sleeper  # type: ignore[arg-type]


def test_every_metric_covered_is_complete() -> None:
    run, stub, _ = _run([FULL])

    assert run.status is RunStatus.COMPLETE
    assert run.failure is None
    assert [item.metric for item in run.proposed] == ["revenue", "ebitda"]
    assert run.proposed[0].evidence.document_id == "acme-q2-results"
    assert run.usage.provider_calls == 1
    assert run.usage.input_tokens == 100
    assert run.usage.prompt_chars > 0
    assert run.source_version_ids == ("acme-q2-results:v1",)
    assert len(stub.requests) == 1


def test_a_rejection_or_uncovered_metric_is_partial() -> None:
    bad = _response(
        _observation("revenue", "125.0", "page=1;span=1"),
        _observation("ebitda", "99", "page=1;span=2"),
    )
    partial, _, _ = _run([bad])
    uncovered, _, _ = _run([_response(_observation("revenue", "125.0", "page=1;span=1"))])

    assert partial.status is RunStatus.PARTIAL
    assert [item.code for item in partial.rejected] == [ProposalRejectionCode.VALUE_NOT_VERBATIM]
    assert uncovered.status is RunStatus.PARTIAL
    assert uncovered.rejected == ()


def test_transient_error_then_success_completes_with_two_attempts() -> None:
    run, _, sleeper = _run([ProviderTransientError("busy"), FULL])

    assert run.status is RunStatus.COMPLETE
    assert [attempt.outcome for attempt in run.attempts] == ["transient_error", "ok"]
    assert run.usage.provider_calls == 2
    assert sleeper.calls == [Decimal("1")]


def test_transient_errors_beyond_the_call_budget_fail_as_unavailable() -> None:
    run, _, sleeper = _run(
        [ProviderTransientError("a"), ProviderTransientError("b"), ProviderTransientError("c")]
    )

    assert run.status is RunStatus.FAILED
    assert run.failure is RunFailureCode.PROVIDER_UNAVAILABLE
    assert run.usage.provider_calls == 3
    assert sleeper.calls == [Decimal("1"), Decimal("2")]


def test_permanent_errors_fail_without_retry() -> None:
    rejected, _, _ = _run([ProviderPermanentError("bad request")])
    refused, _, _ = _run([ProviderRefusal("no")])

    assert (rejected.failure, len(rejected.attempts)) == (RunFailureCode.PROVIDER_REJECTED, 1)
    assert (refused.failure, len(refused.attempts)) == (RunFailureCode.PROVIDER_REFUSED, 1)


def test_truncated_output_is_never_parsed() -> None:
    run, _, _ = _run(
        [_response(_observation("revenue", "125.0", "page=1;span=1"), stop_reason="max_tokens")]
    )

    assert run.failure is RunFailureCode.OUTPUT_TRUNCATED
    assert run.proposed == ()
    assert run.rejected == ()


def test_malformed_output_is_a_recorded_rejection() -> None:
    broken = replace(FULL, text="{not json")
    run, _, _ = _run([broken])

    assert run.status is RunStatus.PARTIAL
    assert run.rejected[0].code is ProposalRejectionCode.MALFORMED_OUTPUT


def test_cancellation_before_the_first_call_costs_nothing() -> None:
    run, stub, _ = _run([FULL], cancellation=Cancelled())

    assert run.failure is RunFailureCode.CANCELLED
    assert run.usage.provider_calls == 0
    assert stub.requests == ()


def test_deadline_exceeded_before_calling() -> None:
    run, stub, _ = _run([FULL], clock=FakeClock(step=Decimal("61")))

    assert run.failure is RunFailureCode.DEADLINE_EXCEEDED
    assert stub.requests == ()


def test_oversized_scope_fails_before_any_call() -> None:
    run, stub, _ = _run([FULL], budget=replace(BUDGET, max_prompt_chars=10))

    assert run.failure is RunFailureCode.SCOPE_TOO_LARGE
    assert run.usage.prompt_chars == 0
    assert stub.requests == ()


def test_run_identity_and_digests_are_stable() -> None:
    first, _, _ = _run([FULL])
    second, _, _ = _run([FULL])

    assert run_id_for("job-1") == first.run_id == second.run_id
    assert replace(first, started_at=START, finished_at=START) == replace(
        second, started_at=START, finished_at=START
    )
    assert request_digest_for(SCOPE, model_id="model-x", budget=BUDGET) != request_digest_for(
        SCOPE, model_id="model-x", budget=replace(BUDGET, max_output_tokens=1)
    )

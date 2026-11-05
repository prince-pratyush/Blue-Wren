import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from blue_wren.application.analysis_prompt import PROMPT_VERSION, ScopeTooLarge, render_request
from blue_wren.application.analysis_provider import (
    AnalysisProvider,
    Cancellation,
    Clock,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
    Sleeper,
)
from blue_wren.application.analysis_schema import (
    OUTPUT_SCHEMA_VERSION,
    MalformedOutput,
    decode_proposals,
    output_schema_json,
)
from blue_wren.application.analysis_scope import baseline_digest, scope_digest
from blue_wren.application.analysis_validation import VALIDATOR_VERSION, validate_proposals
from blue_wren.domain.analysis import (
    AnalysisRun,
    AnalysisScope,
    BudgetUsage,
    ProposalRejectionCode,
    ProviderAttempt,
    RejectedProposal,
    RunBudget,
    RunFailureCode,
    RunStatus,
)
from blue_wren.domain.findings import ReportedObservation
from blue_wren.domain.provider import ProviderRequest, ProviderResponse


def run_id_for(idempotency_key: str) -> str:
    return f"run-{sha256(idempotency_key.encode()).hexdigest()[:24]}"


def request_digest_for(scope: AnalysisScope, *, model_id: str, budget: RunBudget) -> str:
    payload = {
        "scope": scope_digest(scope),
        "baselines": baseline_digest(scope.baselines),
        "model_id": model_id,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "budget": {
            "max_prompt_chars": budget.max_prompt_chars,
            "max_output_tokens": budget.max_output_tokens,
            "max_provider_calls": budget.max_provider_calls,
            "max_tool_calls": budget.max_tool_calls,
            "max_seconds": str(budget.max_seconds),
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def propose_observations(
    scope: AnalysisScope,
    *,
    provider: AnalysisProvider,
    model_id: str,
    budget: RunBudget,
    idempotency_key: str,
    clock: Clock,
    sleeper: Sleeper,
    nonce: str,
    cancellation: Cancellation | None = None,
) -> AnalysisRun:
    started_at = clock.now()
    attempts: list[ProviderAttempt] = []
    usage = _Usage()
    proposed: tuple[ReportedObservation, ...] = ()
    rejected: tuple[RejectedProposal, ...] = ()
    failure: RunFailureCode | None = None

    try:
        request = render_request(
            scope,
            budget=budget,
            model_id=model_id,
            nonce=nonce,
            output_schema_json=output_schema_json(metrics=scope.metrics, units=scope.units),
        )
    except ScopeTooLarge:
        failure = RunFailureCode.SCOPE_TOO_LARGE
    else:
        usage.prompt_chars = len(request.system) + len(request.user_content)
        failure, response = _call_with_retries(
            request,
            provider=provider,
            budget=budget,
            started_at=started_at,
            clock=clock,
            sleeper=sleeper,
            cancellation=cancellation,
            attempts=attempts,
            usage=usage,
        )
        if response is not None:
            proposed, rejected = _interpret(scope, response)

    finished_at = clock.now()
    covered = {observation.metric for observation in proposed}
    if failure is not None:
        status = RunStatus.FAILED
    elif covered == set(scope.metrics) and not rejected:
        status = RunStatus.COMPLETE
    else:
        status = RunStatus.PARTIAL

    return AnalysisRun(
        run_id=run_id_for(idempotency_key),
        event_id=scope.event_id,
        company_id=scope.company_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest_for(scope, model_id=model_id, budget=budget),
        scope_digest=scope_digest(scope),
        baseline_digest=baseline_digest(scope.baselines),
        status=status,
        failure=failure,
        cutoff_at=scope.cutoff_at,
        source_version_ids=tuple(sorted({span.document_version_id for span in scope.spans})),
        requested_metrics=scope.metrics,
        provider_id=provider.provider_id,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        validator_version=VALIDATOR_VERSION,
        budget=budget,
        usage=usage.snapshot(_seconds(started_at, finished_at)),
        attempts=tuple(attempts),
        tool_calls=(),
        proposed=proposed,
        rejected=rejected,
        started_at=started_at,
        finished_at=finished_at,
    )


class _Usage:
    def __init__(self) -> None:
        self.prompt_chars = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_input_tokens = 0
        self.provider_calls = 0

    def snapshot(self, elapsed: Decimal) -> BudgetUsage:
        return BudgetUsage(
            prompt_chars=self.prompt_chars,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            provider_calls=self.provider_calls,
            tool_calls=0,
            elapsed_seconds=elapsed,
        )


def _call_with_retries(
    request: ProviderRequest,
    *,
    provider: AnalysisProvider,
    budget: RunBudget,
    started_at: datetime,
    clock: Clock,
    sleeper: Sleeper,
    cancellation: Cancellation | None,
    attempts: list[ProviderAttempt],
    usage: _Usage,
) -> tuple[RunFailureCode | None, ProviderResponse | None]:
    while True:
        if cancellation is not None and cancellation.cancelled():
            return RunFailureCode.CANCELLED, None
        if _seconds(started_at, clock.now()) > budget.max_seconds:
            return RunFailureCode.DEADLINE_EXCEEDED, None
        if usage.provider_calls >= budget.max_provider_calls:
            return RunFailureCode.PROVIDER_UNAVAILABLE, None

        attempt_started = clock.now()
        usage.provider_calls += 1
        index = len(attempts) + 1
        try:
            response = provider.complete(request)
        except ProviderTransientError:
            attempts.append(_attempt(index, "transient_error", None, attempt_started, clock))
            if usage.provider_calls >= budget.max_provider_calls:
                return RunFailureCode.PROVIDER_UNAVAILABLE, None
            sleeper.sleep(Decimal(2 ** (usage.provider_calls - 1)))
            continue
        except ProviderRefusal:
            attempts.append(_attempt(index, "refused", None, attempt_started, clock))
            return RunFailureCode.PROVIDER_REFUSED, None
        except ProviderPermanentError:
            attempts.append(_attempt(index, "rejected", None, attempt_started, clock))
            return RunFailureCode.PROVIDER_REJECTED, None

        attempts.append(_attempt(index, "ok", response, attempt_started, clock))
        usage.input_tokens += response.usage.input_tokens
        usage.output_tokens += response.usage.output_tokens
        usage.cache_read_input_tokens += response.usage.cache_read_input_tokens
        if response.stop_reason == "max_tokens":
            return RunFailureCode.OUTPUT_TRUNCATED, None
        return None, response


def _interpret(
    scope: AnalysisScope, response: ProviderResponse
) -> tuple[tuple[ReportedObservation, ...], tuple[RejectedProposal, ...]]:
    try:
        proposals = decode_proposals(response.text)
    except MalformedOutput as error:
        return (), (
            RejectedProposal(ProposalRejectionCode.MALFORMED_OUTPUT, None, None, None, str(error)),
        )
    return validate_proposals(scope, proposals)


def _attempt(
    index: int,
    outcome: str,
    response: ProviderResponse | None,
    attempt_started: datetime,
    clock: Clock,
) -> ProviderAttempt:
    return ProviderAttempt(
        index=index,
        outcome=outcome,
        request_id=response.request_id if response else None,
        model_id=response.model_id if response else None,
        input_tokens=response.usage.input_tokens if response else 0,
        output_tokens=response.usage.output_tokens if response else 0,
        duration_seconds=_seconds(attempt_started, clock.now()),
    )


def _seconds(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds()))

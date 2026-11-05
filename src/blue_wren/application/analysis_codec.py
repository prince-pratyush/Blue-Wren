from datetime import datetime
from decimal import Decimal
from typing import Any

from blue_wren.domain.analysis import (
    AnalysisRun,
    BudgetUsage,
    ProposalRejectionCode,
    ProviderAttempt,
    RejectedProposal,
    RunBudget,
    RunFailureCode,
    RunStatus,
    ToolCallRecord,
    ToolCallStatus,
)
from blue_wren.domain.findings import EvidenceReference, ReportedObservation

SCHEMA_VERSION = 1


def encode_run(run: AnalysisRun) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.run_id,
        "event_id": run.event_id,
        "company_id": run.company_id,
        "idempotency_key": run.idempotency_key,
        "request_digest": run.request_digest,
        "scope_digest": run.scope_digest,
        "baseline_digest": run.baseline_digest,
        "status": run.status.value,
        "failure": run.failure.value if run.failure else None,
        "cutoff_at": run.cutoff_at.isoformat(),
        "source_version_ids": list(run.source_version_ids),
        "requested_metrics": list(run.requested_metrics),
        "provider_id": run.provider_id,
        "model_id": run.model_id,
        "prompt_version": run.prompt_version,
        "output_schema_version": run.output_schema_version,
        "validator_version": run.validator_version,
        "budget": {
            "max_prompt_chars": run.budget.max_prompt_chars,
            "max_output_tokens": run.budget.max_output_tokens,
            "max_provider_calls": run.budget.max_provider_calls,
            "max_tool_calls": run.budget.max_tool_calls,
            "max_seconds": str(run.budget.max_seconds),
        },
        "usage": {
            "prompt_chars": run.usage.prompt_chars,
            "input_tokens": run.usage.input_tokens,
            "output_tokens": run.usage.output_tokens,
            "cache_read_input_tokens": run.usage.cache_read_input_tokens,
            "provider_calls": run.usage.provider_calls,
            "tool_calls": run.usage.tool_calls,
            "elapsed_seconds": str(run.usage.elapsed_seconds),
        },
        "attempts": [
            {
                "index": attempt.index,
                "outcome": attempt.outcome,
                "request_id": attempt.request_id,
                "model_id": attempt.model_id,
                "input_tokens": attempt.input_tokens,
                "output_tokens": attempt.output_tokens,
                "duration_seconds": str(attempt.duration_seconds),
            }
            for attempt in run.attempts
        ],
        "tool_calls": [
            {
                "index": call.index,
                "name": call.name,
                "status": call.status.value,
                "argument_digest": call.argument_digest,
                "duration_seconds": str(call.duration_seconds),
            }
            for call in run.tool_calls
        ],
        "proposed": [
            {
                "metric": item.metric,
                "value": str(item.value),
                "unit": item.unit,
                "period": item.period,
                "basis": item.basis,
                "document_id": item.evidence.document_id,
                "document_version_id": item.evidence.document_version_id,
                "locator": item.evidence.locator,
            }
            for item in run.proposed
        ],
        "rejected": [
            {
                "code": item.code.value,
                "metric": item.metric,
                "document_version_id": item.document_version_id,
                "locator": item.locator,
                "detail": item.detail,
            }
            for item in run.rejected
        ],
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
    }


def decode_run(payload: dict[str, Any]) -> AnalysisRun:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {payload.get('schema_version')}")
    budget = payload["budget"]
    usage = payload["usage"]
    return AnalysisRun(
        run_id=payload["run_id"],
        event_id=payload["event_id"],
        company_id=payload["company_id"],
        idempotency_key=payload["idempotency_key"],
        request_digest=payload["request_digest"],
        scope_digest=payload["scope_digest"],
        baseline_digest=payload["baseline_digest"],
        status=RunStatus(payload["status"]),
        failure=RunFailureCode(payload["failure"]) if payload["failure"] else None,
        cutoff_at=datetime.fromisoformat(payload["cutoff_at"]),
        source_version_ids=tuple(payload["source_version_ids"]),
        requested_metrics=tuple(payload["requested_metrics"]),
        provider_id=payload["provider_id"],
        model_id=payload["model_id"],
        prompt_version=payload["prompt_version"],
        output_schema_version=payload["output_schema_version"],
        validator_version=payload["validator_version"],
        budget=RunBudget(
            max_prompt_chars=budget["max_prompt_chars"],
            max_output_tokens=budget["max_output_tokens"],
            max_provider_calls=budget["max_provider_calls"],
            max_tool_calls=budget["max_tool_calls"],
            max_seconds=Decimal(budget["max_seconds"]),
        ),
        usage=BudgetUsage(
            prompt_chars=usage["prompt_chars"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_read_input_tokens=usage["cache_read_input_tokens"],
            provider_calls=usage["provider_calls"],
            tool_calls=usage["tool_calls"],
            elapsed_seconds=Decimal(usage["elapsed_seconds"]),
        ),
        attempts=tuple(
            ProviderAttempt(
                index=item["index"],
                outcome=item["outcome"],
                request_id=item["request_id"],
                model_id=item["model_id"],
                input_tokens=item["input_tokens"],
                output_tokens=item["output_tokens"],
                duration_seconds=Decimal(item["duration_seconds"]),
            )
            for item in payload["attempts"]
        ),
        tool_calls=tuple(
            ToolCallRecord(
                index=item["index"],
                name=item["name"],
                status=ToolCallStatus(item["status"]),
                argument_digest=item["argument_digest"],
                duration_seconds=Decimal(item["duration_seconds"]),
            )
            for item in payload["tool_calls"]
        ),
        proposed=tuple(
            ReportedObservation(
                metric=item["metric"],
                value=Decimal(item["value"]),
                unit=item["unit"],
                period=item["period"],
                basis=item["basis"],
                evidence=EvidenceReference(
                    document_id=item["document_id"],
                    document_version_id=item["document_version_id"],
                    locator=item["locator"],
                ),
            )
            for item in payload["proposed"]
        ),
        rejected=tuple(
            RejectedProposal(
                code=ProposalRejectionCode(item["code"]),
                metric=item["metric"],
                document_version_id=item["document_version_id"],
                locator=item["locator"],
                detail=item["detail"],
            )
            for item in payload["rejected"]
        ),
        started_at=datetime.fromisoformat(payload["started_at"]),
        finished_at=datetime.fromisoformat(payload["finished_at"]),
    )

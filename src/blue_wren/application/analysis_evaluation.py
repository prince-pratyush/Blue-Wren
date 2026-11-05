import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from blue_wren.application.analysis import propose_observations
from blue_wren.application.analysis_codec import encode_run
from blue_wren.application.analysis_provider import (
    ProviderError,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
)
from blue_wren.application.analysis_scope import AnalysisScopeError, build_analysis_scope
from blue_wren.domain.analysis import AnalysisRun, RunBudget
from blue_wren.domain.evidence import DocumentVersion, RightsBasis
from blue_wren.domain.extraction import ExtractionRecord, ExtractionStatus, TextSpan
from blue_wren.domain.findings import BaselineObservation
from blue_wren.domain.provider import ProviderResponse, ProviderUsage
from blue_wren.infrastructure.stub_analysis_provider import StubAnalysisProvider


class AnalysisFixtureError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisEvaluationReport:
    passed: bool
    status: str | None
    observation_accuracy: Fraction
    rejection_recall: Fraction
    coverage: Fraction
    critical_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisCaseResult:
    case_id: str
    report: AnalysisEvaluationReport


@dataclass(frozen=True, slots=True)
class AnalysisSuiteReport:
    passed: bool
    cases: tuple[AnalysisCaseResult, ...]


class _FixedClock:
    def __init__(self, start: datetime) -> None:
        self._current = start

    def now(self) -> datetime:
        self._current += timedelta(seconds=1)
        return self._current


class _NoSleep:
    def sleep(self, seconds: Decimal) -> None:
        return None


def discover_analysis_cases(directory: Path) -> tuple[str, ...]:
    cases = []
    for expected in sorted(directory.glob("*.expected.json")):
        case_id = expected.name.removesuffix(".expected.json")
        for suffix in (".scope.json", ".provider.json"):
            if not (directory / f"{case_id}{suffix}").is_file():
                raise AnalysisFixtureError(f"case {case_id} is missing {case_id}{suffix}")
        cases.append(case_id)
    if not cases:
        raise AnalysisFixtureError(f"no analysis cases found in {directory}")
    return tuple(cases)


def run_analysis_suite(directory: Path) -> AnalysisSuiteReport:
    results = tuple(
        AnalysisCaseResult(case_id, run_analysis_evaluation(directory, case_id))
        for case_id in discover_analysis_cases(directory)
    )
    return AnalysisSuiteReport(all(result.report.passed for result in results), results)


def run_analysis_evaluation(directory: Path, case_id: str) -> AnalysisEvaluationReport:
    scope_payload = _load(directory / f"{case_id}.scope.json")
    script = _load(directory / f"{case_id}.provider.json")["entries"]
    expected = _load(directory / f"{case_id}.expected.json")
    budget = _budget(scope_payload["budget"])
    try:
        scope = _scope(scope_payload)
    except AnalysisScopeError as error:
        return _scope_error_report(expected, str(error))

    runs = [
        propose_observations(
            scope,
            provider=StubAnalysisProvider(_script(script)),
            model_id=scope_payload["model_id"],
            budget=budget,
            idempotency_key=case_id,
            clock=_FixedClock(scope.cutoff_at),
            sleeper=_NoSleep(),
            nonce="eval",
        )
        for _ in range(2)
    ]
    return _score(runs[0], runs[1], expected, budget)


def _scope_error_report(expected: dict[str, Any], message: str) -> AnalysisEvaluationReport:
    wanted = expected.get("scope_error")
    errors = () if wanted and wanted in message else (f"unexpected scope error: {message}",)
    return AnalysisEvaluationReport(
        passed=not errors,
        status=None,
        observation_accuracy=Fraction(1, 1),
        rejection_recall=Fraction(1, 1),
        coverage=Fraction(0, 1),
        critical_errors=errors,
    )


def _score(
    run: AnalysisRun, rerun: AnalysisRun, expected: dict[str, Any], budget: RunBudget
) -> AnalysisEvaluationReport:
    errors: list[str] = []
    if expected.get("scope_error"):
        errors.append("expected a scope error but the run executed")
    if run.status.value != expected["status"]:
        errors.append(f"status mismatch: expected {expected['status']}, got {run.status.value}")
    failure = run.failure.value if run.failure else None
    if failure != expected.get("failure"):
        errors.append(f"failure mismatch: expected {expected.get('failure')}, got {failure}")

    emitted = {_key(item) for item in (_observation_key(o) for o in run.proposed)}
    wanted = {_key(item) for item in expected.get("observations", [])}
    matched = emitted & wanted
    for item in sorted(wanted - emitted):
        errors.append(f"missing observation: {item}")
    for item in sorted(emitted - wanted):
        errors.append(f"unexpected observation: {item}")
    accuracy = Fraction(len(matched), len(wanted)) if wanted else Fraction(1, 1)

    emitted_codes = [item.code.value for item in run.rejected]
    wanted_codes = list(expected.get("rejections", []))
    found = sum(1 for code in wanted_codes if code in emitted_codes)
    for code in wanted_codes:
        if code not in emitted_codes:
            errors.append(f"missing rejection: {code}")
    recall = Fraction(found, len(wanted_codes)) if wanted_codes else Fraction(1, 1)

    covered = {item.metric for item in run.proposed}
    coverage = (
        Fraction(len(covered & set(run.requested_metrics)), len(run.requested_metrics))
        if run.requested_metrics
        else Fraction(1, 1)
    )
    if run.status.value == "complete" and coverage != 1:
        errors.append("complete status with a coverage gap")

    usage = run.usage
    if usage.provider_calls > budget.max_provider_calls:
        errors.append("budget breach: provider_calls")
    if usage.prompt_chars > budget.max_prompt_chars:
        errors.append("budget breach: prompt_chars")
    ceiling = expected.get("usage_ceiling", {})
    if usage.provider_calls > ceiling.get("provider_calls", usage.provider_calls):
        errors.append("usage ceiling exceeded: provider_calls")

    if _stable_payload(run) != _stable_payload(rerun):
        errors.append("unstable payload across identical runs")

    return AnalysisEvaluationReport(
        passed=not errors,
        status=run.status.value,
        observation_accuracy=accuracy,
        rejection_recall=recall,
        coverage=coverage,
        critical_errors=tuple(errors),
    )


def _stable_payload(run: AnalysisRun) -> dict[str, Any]:
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    payload = encode_run(replace(run, started_at=epoch, finished_at=epoch))
    payload["usage"]["elapsed_seconds"] = "0"
    payload["attempts"] = [{**item, "duration_seconds": "0"} for item in payload["attempts"]]
    return payload


def _observation_key(observation: Any) -> dict[str, str]:
    return {
        "metric": observation.metric,
        "value": str(observation.value),
        "unit": observation.unit,
        "period": observation.period,
        "basis": observation.basis,
        "document_version_id": observation.evidence.document_version_id,
        "locator": observation.evidence.locator,
    }


def _key(item: dict[str, str]) -> str:
    return json.dumps({k: str(v) for k, v in item.items()}, sort_keys=True)


def _scope(payload: dict[str, Any]) -> Any:
    cutoff = datetime.fromisoformat(payload["cutoff_at"])
    versions = []
    records = []
    for version in payload["versions"]:
        available = datetime.fromisoformat(version["available_at"])
        versions.append(
            DocumentVersion(
                document_id=version["document_id"],
                version_id=version["version_id"],
                content_sha256="0" * 64,
                byte_size=0,
                media_type="text/plain",
                source_name="fixture",
                rights_basis=RightsBasis.PUBLIC,
                published_at=available,
                available_at=available,
                ingested_at=available,
            )
        )
        spans = tuple(
            TextSpan(version["version_id"], s["page"], s["index"], s["text"], s["locator"])
            for s in payload["spans"]
            if s["version_id"] == version["version_id"]
        )
        status = ExtractionStatus(version.get("extraction", "extracted"))
        records.append(ExtractionRecord(version["version_id"], status, 1, spans))
    baselines = [
        BaselineObservation(
            b["metric"],
            Decimal(b["value"]),
            b["unit"],
            b["period"],
            b["basis"],
            b.get("target", "estimate"),
        )
        for b in payload["baselines"]
    ]
    return build_analysis_scope(
        event_id=payload["event_id"],
        company_id=payload["company_id"],
        cutoff_at=cutoff,
        versions=versions,
        extractions=records,
        baselines=baselines,
        units=payload.get("units", []),
    )


def _budget(payload: dict[str, Any]) -> RunBudget:
    return RunBudget(
        max_prompt_chars=payload["max_prompt_chars"],
        max_output_tokens=payload["max_output_tokens"],
        max_provider_calls=payload["max_provider_calls"],
        max_tool_calls=payload.get("max_tool_calls", 0),
        max_seconds=Decimal(str(payload["max_seconds"])),
    )


def _script(entries: list[dict[str, Any]]) -> list[ProviderResponse | ProviderError]:
    script: list[ProviderResponse | ProviderError] = []
    for entry in entries:
        error = entry.get("error")
        if error == "transient":
            script.append(ProviderTransientError("scripted transient error"))
        elif error == "permanent":
            script.append(ProviderPermanentError("scripted permanent error"))
        elif error == "refusal":
            script.append(ProviderRefusal("scripted refusal"))
        elif error:
            raise AnalysisFixtureError(f"unknown provider error kind: {error}")
        else:
            script.append(
                ProviderResponse(
                    text=entry["text"],
                    usage=ProviderUsage(
                        entry.get("input_tokens", 100), entry.get("output_tokens", 40)
                    ),
                    stop_reason=entry.get("stop_reason", "end_turn"),
                    model_id=entry.get("model_id", "stub-model"),
                    request_id=entry.get("request_id"),
                )
            )
    return script


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] | list[Any] = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"entries": data}

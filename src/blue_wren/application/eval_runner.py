import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from blue_wren.application.evaluation import score_findings
from blue_wren.application.event_review import start_event_review
from blue_wren.application.replay import replay_event_fixture
from blue_wren.application.review import mark_source_version_stale
from blue_wren.domain.evaluation import (
    EvaluationCaseResult,
    EvaluationReport,
    EvaluationSource,
    EvaluationSourceManifest,
    EvaluationSuiteReport,
    ExpectedFinding,
)
from blue_wren.domain.findings import Finding, FindingStatus
from blue_wren.domain.review import ReviewOutcome


class EvaluationFixtureError(ValueError):
    pass


def load_expected_findings(path: Path) -> tuple[ExpectedFinding, ...]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(_expected_finding(item) for item in payload["findings"])


def run_replay_evaluation(
    *,
    event_path: Path,
    expected_path: Path,
    source_manifest_path: Path,
    restatement_path: Path | None = None,
) -> EvaluationReport:
    replay = replay_event_fixture(event_path)
    expected = load_expected_findings(expected_path)
    manifest = _load_source_manifest(source_manifest_path)
    if manifest.event_id != replay.event_id:
        raise EvaluationFixtureError("source manifest event does not match replay event")
    source_keys = {(source.document_id, source.version_id) for source in manifest.sources}
    if any(
        (finding.evidence_document_id, finding.evidence_document_version_id)
        not in source_keys
        for finding in expected
    ):
        raise EvaluationFixtureError("expected evidence is not in source manifest")
    if any(
        (finding.evidence.document_id, finding.evidence.document_version_id) not in source_keys
        for finding in replay.findings
    ):
        raise EvaluationFixtureError("emitted evidence is not in source manifest")
    report = score_findings(expected=expected, emitted=replay.findings)
    if restatement_path is None and all(item.review_outcome is None for item in expected):
        return report

    session = start_event_review(replay, created_at=manifest.cutoff_at)
    histories = session.findings
    if restatement_path is not None:
        restatement: dict[str, Any] = json.loads(restatement_path.read_text(encoding="utf-8"))
        marked_at = datetime.fromisoformat(restatement["marked_at"])
        _require_timezone(marked_at)
        histories = tuple(
            mark_source_version_stale(
                history,
                expected_version=history.current_revision.version,
                document_id=restatement["document_id"],
                superseding_version_id=restatement["superseding_version_id"],
                marked_at=marked_at,
            )
            for history in histories
        )

    outcomes = {
        _outcome_key(history.current_revision.finding): history.current_outcome
        for history in histories
    }
    errors = tuple(
        f"{item.metric}: review outcome mismatch"
        for item in expected
        if item.review_outcome is not None
        and outcomes.get(
            (item.metric, item.period, item.basis, item.evidence_document_version_id)
        )
        is not item.review_outcome
    )
    if not errors:
        return report
    return replace(report, passed=False, critical_errors=(*report.critical_errors, *errors))


def _outcome_key(finding: Finding) -> tuple[str, str, str, str]:
    return (finding.metric, finding.period, finding.basis, finding.evidence.document_version_id)


def discover_cases(directory: Path) -> tuple[str, ...]:
    cases = []
    for expected in sorted(directory.glob("*.expected.json")):
        case_id = expected.name.removesuffix(".expected.json")
        for suffix in (".json", ".sources.json"):
            if not (directory / f"{case_id}{suffix}").is_file():
                raise EvaluationFixtureError(f"case {case_id} is missing {case_id}{suffix}")
        cases.append(case_id)
    if not cases:
        raise EvaluationFixtureError(f"no evaluation cases found in {directory}")
    return tuple(cases)


def run_evaluation_suite(directory: Path) -> EvaluationSuiteReport:
    results = tuple(
        EvaluationCaseResult(
            case_id=case_id,
            report=run_replay_evaluation(
                event_path=directory / f"{case_id}.json",
                expected_path=directory / f"{case_id}.expected.json",
                source_manifest_path=directory / f"{case_id}.sources.json",
                restatement_path=_optional(directory / f"{case_id}.restatement.json"),
            ),
        )
        for case_id in discover_cases(directory)
    )
    return EvaluationSuiteReport(
        passed=all(result.report.passed for result in results),
        cases=results,
    )


def _optional(path: Path) -> Path | None:
    return path if path.is_file() else None


def _expected_finding(payload: dict[str, Any]) -> ExpectedFinding:
    delta = payload["delta"]
    review_outcome = payload.get("review_outcome")
    return ExpectedFinding(
        review_outcome=ReviewOutcome(review_outcome) if review_outcome is not None else None,
        metric=payload["metric"],
        actual=Decimal(payload["actual"]),
        baseline=Decimal(payload["baseline"]),
        delta=Decimal(delta) if delta is not None else None,
        unit=payload["unit"],
        period=payload["period"],
        basis=payload["basis"],
        evidence_document_id=payload["evidence_document_id"],
        evidence_document_version_id=payload["evidence_document_version_id"],
        status=FindingStatus(payload["status"]),
        baseline_target=payload.get("baseline_target", "estimate"),
    )


def _load_source_manifest(path: Path) -> EvaluationSourceManifest:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    cutoff_at = datetime.fromisoformat(payload["cutoff_at"])
    _require_timezone(cutoff_at)
    sources = tuple(
        EvaluationSource(
            document_id=source["document_id"],
            version_id=source["version_id"],
            available_at=datetime.fromisoformat(source["available_at"]),
        )
        for source in payload["sources"]
    )
    for source in sources:
        _require_timezone(source.available_at)
        if source.available_at > cutoff_at:
            raise EvaluationFixtureError("source was unavailable at cutoff")
    keys = tuple((source.document_id, source.version_id) for source in sources)
    if len(set(keys)) != len(keys):
        raise EvaluationFixtureError("source manifest contains duplicate versions")
    return EvaluationSourceManifest(
        event_id=payload["event_id"],
        cutoff_at=cutoff_at,
        sources=sources,
    )


def _require_timezone(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvaluationFixtureError("source manifest timestamps require a timezone")

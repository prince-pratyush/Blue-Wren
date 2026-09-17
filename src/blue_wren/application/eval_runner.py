import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from blue_wren.application.evaluation import score_findings
from blue_wren.application.replay import replay_event_fixture
from blue_wren.domain.evaluation import (
    EvaluationCaseResult,
    EvaluationReport,
    EvaluationSource,
    EvaluationSourceManifest,
    EvaluationSuiteReport,
    ExpectedFinding,
)
from blue_wren.domain.findings import FindingStatus


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
    return score_findings(expected=expected, emitted=replay.findings)


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
            ),
        )
        for case_id in discover_cases(directory)
    )
    return EvaluationSuiteReport(
        passed=all(result.report.passed for result in results),
        cases=results,
    )


def _expected_finding(payload: dict[str, Any]) -> ExpectedFinding:
    delta = payload["delta"]
    return ExpectedFinding(
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

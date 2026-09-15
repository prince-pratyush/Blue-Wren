import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from blue_wren.application.evaluation import score_findings
from blue_wren.application.replay import replay_event_fixture
from blue_wren.domain.evaluation import EvaluationReport, ExpectedFinding
from blue_wren.domain.findings import FindingStatus


def load_expected_findings(path: Path) -> tuple[ExpectedFinding, ...]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(_expected_finding(item) for item in payload["findings"])


def run_replay_evaluation(
    *,
    event_path: Path,
    expected_path: Path,
) -> EvaluationReport:
    replay = replay_event_fixture(event_path)
    expected = load_expected_findings(expected_path)
    return score_findings(expected=expected, emitted=replay.findings)


def _expected_finding(payload: dict[str, Any]) -> ExpectedFinding:
    delta = payload["delta"]
    return ExpectedFinding(
        metric=payload["metric"],
        actual=Decimal(payload["actual"]),
        baseline=Decimal(payload["baseline"]),
        delta=Decimal(delta) if delta is not None else None,
        unit=payload["unit"],
        period=payload["period"],
        evidence_document_id=payload["evidence_document_id"],
        evidence_document_version_id=payload["evidence_document_version_id"],
        status=FindingStatus(payload["status"]),
    )

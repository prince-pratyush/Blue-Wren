"""Replay a point-in-time synthetic results event."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from blue_wren.domain.findings import (
    BaselineObservation,
    EventReplayResult,
    EvidenceReference,
    ReportedObservation,
    compare_observations,
)


def replay_event_fixture(path: Path) -> EventReplayResult:
    """Load one event fixture and create a reviewable comparison."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    actual_payload = payload["actual"]
    baseline_payload = payload["baseline"]
    evidence_payload = actual_payload.get("evidence")
    if evidence_payload is None:
        raise ValueError("actual evidence is required")

    actual = ReportedObservation(
        metric=actual_payload["metric"],
        value=Decimal(actual_payload["value"]),
        unit=actual_payload["unit"],
        period=actual_payload["period"],
        evidence=EvidenceReference(
            document_id=evidence_payload["document_id"],
            locator=evidence_payload["locator"],
        ),
    )
    baseline = BaselineObservation(
        metric=baseline_payload["metric"],
        value=Decimal(baseline_payload["value"]),
        unit=baseline_payload["unit"],
        period=baseline_payload["period"],
    )

    return EventReplayResult(
        event_id=payload["event_id"],
        company_id=payload["company_id"],
        findings=(compare_observations(actual, baseline),),
    )

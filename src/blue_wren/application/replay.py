"""Replay a point-in-time synthetic results event."""

from __future__ import annotations

import json
from collections.abc import Sequence
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

Comparison = tuple[ReportedObservation, BaselineObservation]


def replay_event(
    *,
    event_id: str,
    company_id: str,
    comparisons: Sequence[Comparison],
) -> EventReplayResult:
    return EventReplayResult(
        event_id=event_id,
        company_id=company_id,
        findings=tuple(compare_observations(actual, baseline) for actual, baseline in comparisons),
    )


def replay_event_fixture(path: Path) -> EventReplayResult:
    """Load one event fixture and create reviewable comparisons."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return replay_event(
        event_id=payload["event_id"],
        company_id=payload["company_id"],
        comparisons=tuple(_comparison(item) for item in payload["comparisons"]),
    )


def _comparison(item: dict[str, Any]) -> Comparison:
    actual_payload = item["actual"]
    baseline_payload = item["baseline"]
    evidence_payload = actual_payload.get("evidence")
    if evidence_payload is None:
        raise ValueError("actual evidence is required")

    actual = ReportedObservation(
        metric=actual_payload["metric"],
        value=Decimal(actual_payload["value"]),
        unit=actual_payload["unit"],
        period=actual_payload["period"],
        basis=actual_payload["basis"],
        evidence=EvidenceReference(
            document_id=evidence_payload["document_id"],
            document_version_id=evidence_payload["document_version_id"],
            locator=evidence_payload["locator"],
        ),
    )
    baseline = BaselineObservation(
        metric=baseline_payload["metric"],
        value=Decimal(baseline_payload["value"]),
        unit=baseline_payload["unit"],
        period=baseline_payload["period"],
        basis=baseline_payload["basis"],
        target=baseline_payload.get("target", "estimate"),
    )
    return actual, baseline

import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from blue_wren.domain.analysis import AnalysisScope, SourceSpan
from blue_wren.domain.evidence import DocumentVersion
from blue_wren.domain.extraction import ExtractionRecord, ExtractionStatus
from blue_wren.domain.findings import BaselineObservation


class AnalysisScopeError(ValueError):
    pass


def build_analysis_scope(
    *,
    event_id: str,
    company_id: str,
    cutoff_at: datetime,
    versions: Sequence[DocumentVersion],
    extractions: Sequence[ExtractionRecord],
    baselines: Sequence[BaselineObservation],
    units: Sequence[str] = (),
) -> AnalysisScope:
    _require_timezone(cutoff_at, "cutoff_at")
    if not baselines:
        raise AnalysisScopeError("at least one baseline is required")
    identifiers = [version.version_id for version in versions]
    if len(set(identifiers)) != len(identifiers):
        raise AnalysisScopeError("duplicate document version")
    records = {record.document_version_id: record for record in extractions}

    spans: list[SourceSpan] = []
    for version in versions:
        _require_timezone(version.available_at, "available_at")
        if version.available_at > cutoff_at:
            raise AnalysisScopeError(f"version {version.version_id} available after cutoff")
        record = records.get(version.version_id)
        if record is None:
            raise AnalysisScopeError(f"version {version.version_id} has no extraction")
        if record.status is not ExtractionStatus.EXTRACTED:
            raise AnalysisScopeError(
                f"version {version.version_id} extraction is {record.status.value}"
            )
        spans.extend(
            SourceSpan(
                document_id=version.document_id,
                document_version_id=version.version_id,
                page=span.page,
                index=span.index,
                locator=span.locator,
                text=span.text,
            )
            for span in record.spans
        )

    return AnalysisScope(
        event_id=event_id,
        company_id=company_id,
        cutoff_at=cutoff_at,
        metrics=tuple(sorted({baseline.metric for baseline in baselines})),
        units=tuple(sorted(set(units) | {baseline.unit for baseline in baselines})),
        spans=tuple(
            sorted(spans, key=lambda span: (span.document_version_id, span.page, span.index))
        ),
        baselines=tuple(baselines),
    )


def scope_digest(scope: AnalysisScope) -> str:
    payload = {
        "event_id": scope.event_id,
        "company_id": scope.company_id,
        "cutoff_at": scope.cutoff_at.isoformat(),
        "metrics": list(scope.metrics),
        "units": list(scope.units),
        "spans": [
            {
                "document_id": span.document_id,
                "document_version_id": span.document_version_id,
                "page": span.page,
                "index": span.index,
                "locator": span.locator,
                "text": span.text,
            }
            for span in scope.spans
        ],
    }
    return _digest(payload)


def baseline_digest(baselines: Sequence[BaselineObservation]) -> str:
    items = [
        {
            "metric": baseline.metric,
            "value": str(baseline.value),
            "unit": baseline.unit,
            "period": baseline.period,
            "basis": baseline.basis,
            "target": baseline.target,
        }
        for baseline in baselines
    ]
    items.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return _digest(items)


def _digest(payload: object) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _require_timezone(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalysisScopeError(f"{field} must include a timezone")

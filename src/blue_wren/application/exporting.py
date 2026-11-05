from collections.abc import Callable, Mapping
from datetime import datetime

from blue_wren.application.review_store import StoredEventReview
from blue_wren.domain.evidence import DocumentVersion
from blue_wren.domain.exporting import (
    CheckedExportReadiness,
    ExportBlocked,
    ExportBlocker,
    ExportBlockerCode,
    ExportedFinding,
    ExportedSource,
    ExportManifest,
)
from blue_wren.domain.findings import EvidenceReference, FindingStatus
from blue_wren.domain.review import FindingHistory, ReviewOutcome


def assess_checked_export(
    histories: tuple[FindingHistory, ...],
    *,
    citation_resolved: Callable[[EvidenceReference], bool] | None = None,
) -> CheckedExportReadiness:
    blockers: list[ExportBlocker] = []
    for history in histories:
        blocker = _export_blocker(history)
        if blocker is not None:
            blockers.append(blocker)
        current = history.current_revision
        if citation_resolved is not None and not citation_resolved(current.finding.evidence):
            blockers.append(
                ExportBlocker(
                    finding_id=current.finding_id,
                    code=ExportBlockerCode.CITATION_UNRESOLVED,
                )
            )
    return CheckedExportReadiness(allowed=not blockers, blockers=tuple(blockers))


def _export_blocker(history: FindingHistory) -> ExportBlocker | None:
    current = history.current_revision
    code: ExportBlockerCode | None
    if current.finding.status is FindingStatus.UNRESOLVED:
        code = ExportBlockerCode.UNRESOLVED
    else:
        code = {
            ReviewOutcome.PENDING: ExportBlockerCode.REVIEW_PENDING,
            ReviewOutcome.REJECTED: ExportBlockerCode.REVIEW_REJECTED,
            ReviewOutcome.DEFERRED: ExportBlockerCode.REVIEW_DEFERRED,
            ReviewOutcome.STALE: ExportBlockerCode.STALE,
            ReviewOutcome.ACCEPTED: None,
        }[history.current_outcome]

    if code is None:
        return None
    return ExportBlocker(finding_id=current.finding_id, code=code)


def build_export_manifest(
    stored: StoredEventReview,
    *,
    generated_at: datetime,
    versions: Mapping[str, DocumentVersion],
    spans: Mapping[tuple[str, str], str],
    citation_resolved: Callable[[EvidenceReference], bool],
) -> ExportManifest:
    readiness = assess_checked_export(stored.session.findings, citation_resolved=citation_resolved)
    if not readiness.allowed:
        raise ExportBlocked(readiness.blockers)
    findings = []
    for history in stored.session.findings:
        current = history.current_revision
        finding = current.finding
        decision = next(
            item for item in reversed(history.decisions) if item.finding_version == current.version
        )
        evidence = finding.evidence
        if finding.delta is None:
            raise ExportBlocked((ExportBlocker(current.finding_id, ExportBlockerCode.UNRESOLVED),))
        findings.append(
            ExportedFinding(
                finding_id=current.finding_id,
                version=current.version,
                metric=finding.metric,
                actual=finding.actual,
                baseline=finding.baseline,
                delta=finding.delta,
                unit=finding.unit,
                period=finding.period,
                basis=finding.basis,
                baseline_target=finding.baseline_target,
                reviewer_id=decision.reviewer_id,
                decided_at=decision.decided_at,
                document_id=evidence.document_id,
                document_version_id=evidence.document_version_id,
                locator=evidence.locator,
                evidence_text=spans[(evidence.document_version_id, evidence.locator)],
            )
        )
    cited = sorted({item.document_version_id for item in findings})
    sources = tuple(
        ExportedSource(
            document_id=versions[version_id].document_id,
            document_version_id=version_id,
            content_sha256=versions[version_id].content_sha256,
            source_name=versions[version_id].source_name,
            published_at=versions[version_id].published_at,
            available_at=versions[version_id].available_at,
        )
        for version_id in cited
    )
    return ExportManifest(
        event_id=stored.session.event_id,
        company_id=stored.session.company_id,
        revision=stored.revision,
        generated_at=generated_at,
        findings=tuple(findings),
        sources=sources,
    )

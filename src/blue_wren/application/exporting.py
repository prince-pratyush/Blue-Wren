from collections.abc import Callable

from blue_wren.domain.exporting import (
    CheckedExportReadiness,
    ExportBlocker,
    ExportBlockerCode,
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

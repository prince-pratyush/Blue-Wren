from blue_wren.domain.exporting import (
    CheckedExportReadiness,
    ExportBlocker,
    ExportBlockerCode,
)
from blue_wren.domain.findings import FindingStatus
from blue_wren.domain.review import FindingHistory, ReviewOutcome


def assess_checked_export(
    histories: tuple[FindingHistory, ...],
) -> CheckedExportReadiness:
    blockers = tuple(
        blocker
        for history in histories
        if (blocker := _export_blocker(history)) is not None
    )
    return CheckedExportReadiness(allowed=not blockers, blockers=blockers)


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

from typing import Protocol

from blue_wren.domain.analysis import AnalysisRun


class AnalysisRunNotFound(LookupError):
    pass


class AnalysisRunConflict(ValueError):
    pass


class AnalysisRunRepository(Protocol):
    def get(self, run_id: str) -> AnalysisRun: ...

    def get_by_idempotency_key(self, idempotency_key: str) -> AnalysisRun: ...

    def list_for_event(self, event_id: str) -> tuple[AnalysisRun, ...]: ...

    def create(self, run: AnalysisRun) -> AnalysisRun: ...

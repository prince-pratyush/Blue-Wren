from blue_wren.application.analysis_store import AnalysisRunConflict, AnalysisRunNotFound
from blue_wren.domain.analysis import AnalysisRun


class InMemoryAnalysisRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, AnalysisRun] = {}

    def get(self, run_id: str) -> AnalysisRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise AnalysisRunNotFound(f"analysis run not found: {run_id}") from error

    def get_by_idempotency_key(self, idempotency_key: str) -> AnalysisRun:
        for run in self._runs.values():
            if run.idempotency_key == idempotency_key:
                return run
        raise AnalysisRunNotFound(f"analysis run not found for key: {idempotency_key}")

    def list_for_event(self, event_id: str) -> tuple[AnalysisRun, ...]:
        runs = [run for run in self._runs.values() if run.event_id == event_id]
        return tuple(sorted(runs, key=lambda run: (run.started_at, run.run_id)))

    def create(self, run: AnalysisRun) -> AnalysisRun:
        try:
            existing = self.get_by_idempotency_key(run.idempotency_key)
        except AnalysisRunNotFound:
            self._runs[run.run_id] = run
            return run
        return _resolve_replay(existing, run)


def _resolve_replay(existing: AnalysisRun, run: AnalysisRun) -> AnalysisRun:
    if existing.request_digest != run.request_digest:
        raise AnalysisRunConflict(
            f"idempotency key {run.idempotency_key} was used for a different request"
        )
    return existing

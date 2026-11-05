from collections.abc import Sequence

from blue_wren.application.analysis_provider import ProviderError, ProviderPermanentError
from blue_wren.domain.provider import ProviderRequest, ProviderResponse


class StubAnalysisProvider:
    provider_id = "stub"

    def __init__(self, script: Sequence[ProviderResponse | ProviderError]) -> None:
        self._script = list(script)
        self._requests: list[ProviderRequest] = []

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self._requests.append(request)
        if not self._script:
            raise ProviderPermanentError("stub script exhausted")
        entry = self._script.pop(0)
        if isinstance(entry, ProviderError):
            raise entry
        return entry

    @property
    def requests(self) -> tuple[ProviderRequest, ...]:
        return tuple(self._requests)

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from blue_wren.domain.provider import ProviderRequest, ProviderResponse


class ProviderError(RuntimeError):
    pass


class ProviderTransientError(ProviderError):
    pass


class ProviderPermanentError(ProviderError):
    pass


class ProviderTimeout(ProviderTransientError):
    pass


class ProviderRefusal(ProviderPermanentError):
    pass


class ProviderRejectedRequest(ProviderPermanentError):
    pass


class AnalysisProvider(Protocol):
    provider_id: str

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class Sleeper(Protocol):
    def sleep(self, seconds: Decimal) -> None: ...


class Cancellation(Protocol):
    def cancelled(self) -> bool: ...

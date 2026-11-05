from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model_id: str
    prompt_version: str
    system: str
    user_content: str
    output_schema_json: str
    max_output_tokens: int
    timeout_seconds: Decimal


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    usage: ProviderUsage
    stop_reason: str
    model_id: str
    request_id: str | None = None

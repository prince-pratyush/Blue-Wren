from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RightsBasis(StrEnum):
    PUBLIC = "public"
    LICENSED = "licensed"
    CUSTOMER_PROVIDED = "customer_provided"


class EvidenceIntakeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    document_id: str
    version_id: str
    content_sha256: str
    byte_size: int
    media_type: str
    source_name: str
    rights_basis: RightsBasis
    published_at: datetime
    available_at: datetime
    ingested_at: datetime

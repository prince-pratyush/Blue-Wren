from datetime import datetime
from hashlib import sha256

from blue_wren.domain.evidence import (
    DocumentVersion,
    EvidenceIntakeError,
    RightsBasis,
)

DEFAULT_MAX_BYTES = 25_000_000


def ingest_evidence(
    *,
    document_id: str,
    content: bytes,
    media_type: str,
    source_name: str,
    rights_basis: RightsBasis,
    published_at: datetime,
    available_at: datetime,
    ingested_at: datetime,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DocumentVersion:
    if not content:
        raise EvidenceIntakeError("document is empty")
    if len(content) > max_bytes:
        raise EvidenceIntakeError(f"document exceeds {max_bytes} bytes")

    for timestamp_name, timestamp_value in (
        ("published_at", published_at),
        ("available_at", available_at),
        ("ingested_at", ingested_at),
    ):
        if timestamp_value.utcoffset() is None:
            raise EvidenceIntakeError(f"{timestamp_name} must include a timezone")

    if available_at < published_at:
        raise EvidenceIntakeError("available_at precedes published_at")
    if ingested_at < available_at:
        raise EvidenceIntakeError("ingested_at precedes available_at")

    for field_name, field_value in (
        ("document_id", document_id),
        ("media_type", media_type),
        ("source_name", source_name),
    ):
        if not field_value.strip():
            raise EvidenceIntakeError(f"{field_name} is required")

    digest = sha256(content).hexdigest()
    return DocumentVersion(
        document_id=document_id,
        version_id=f"{document_id}:{digest}",
        content_sha256=digest,
        byte_size=len(content),
        media_type=media_type,
        source_name=source_name,
        rights_basis=rights_basis,
        published_at=published_at,
        available_at=available_at,
        ingested_at=ingested_at,
    )

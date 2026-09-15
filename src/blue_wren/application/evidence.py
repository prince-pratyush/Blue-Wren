from datetime import datetime
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from blue_wren.domain.evidence import (
    DocumentVersion,
    EvidenceIntakeError,
    RightsBasis,
)

DEFAULT_MAX_BYTES = 25_000_000
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "text/html",
        "text/plain",
        XLSX_MEDIA_TYPE,
    }
)


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

    canonical_media_type = media_type.split(";", 1)[0].strip().lower()
    if canonical_media_type not in SUPPORTED_MEDIA_TYPES:
        raise EvidenceIntakeError(f"unsupported media type: {canonical_media_type}")
    _validate_content_signature(content, canonical_media_type)

    digest = sha256(content).hexdigest()
    return DocumentVersion(
        document_id=document_id,
        version_id=f"{document_id}:{digest}",
        content_sha256=digest,
        byte_size=len(content),
        media_type=canonical_media_type,
        source_name=source_name,
        rights_basis=rights_basis,
        published_at=published_at,
        available_at=available_at,
        ingested_at=ingested_at,
    )


def _validate_content_signature(content: bytes, media_type: str) -> None:
    if media_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise EvidenceIntakeError("content does not match declared media type")
    if media_type in {"text/plain", "text/html"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceIntakeError("content does not match declared media type") from error
        if "\x00" in text or (media_type == "text/html" and not text.lstrip().startswith("<")):
            raise EvidenceIntakeError("content does not match declared media type")
    if media_type == XLSX_MEDIA_TYPE:
        _validate_xlsx(content)


def _validate_xlsx(content: bytes) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
    except BadZipFile as error:
        raise EvidenceIntakeError("content does not match declared media type") from error
    if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
        raise EvidenceIntakeError("content does not match declared media type")
    if "xl/vbaproject.bin" in {name.casefold() for name in names}:
        raise EvidenceIntakeError("macro-enabled workbooks are unsupported")

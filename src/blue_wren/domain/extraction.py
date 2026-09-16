from dataclasses import dataclass


class ExtractionError(ValueError):
    pass


class ExtractionUnsupported(ExtractionError):
    pass


@dataclass(frozen=True, slots=True)
class TextSpan:
    document_version_id: str
    page: int
    index: int
    text: str
    locator: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    document_version_id: str
    media_type: str
    page_count: int
    spans: tuple[TextSpan, ...]

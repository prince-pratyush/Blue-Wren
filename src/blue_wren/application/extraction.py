import re
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO

from pypdf import PdfReader

from blue_wren.domain.evidence import DocumentVersion
from blue_wren.domain.extraction import (
    ExtractedDocument,
    ExtractionError,
    ExtractionUnsupported,
    TextSpan,
)

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def extract_text(version: DocumentVersion, content: bytes) -> ExtractedDocument:
    if sha256(content).hexdigest() != version.content_sha256:
        raise ExtractionError("content does not match document version")

    if version.media_type == "text/plain":
        pages = [content.decode("utf-8")]
    elif version.media_type == "text/html":
        pages = [_html_text(content.decode("utf-8"))]
    elif version.media_type == "application/pdf":
        pages = [page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages]
    else:
        raise ExtractionUnsupported(f"unsupported media type for extraction: {version.media_type}")

    spans = tuple(
        TextSpan(
            document_version_id=version.version_id,
            page=page_number,
            index=index,
            text=paragraph,
            locator=f"page={page_number};span={index}",
        )
        for page_number, text in enumerate(pages, 1)
        for index, paragraph in enumerate(_paragraphs(text), 1)
    )
    if not spans:
        raise ExtractionError("no extractable text")
    return ExtractedDocument(
        document_version_id=version.version_id,
        media_type=version.media_type,
        page_count=len(pages),
        spans=spans,
    )


def _paragraphs(text: str) -> list[str]:
    return [chunk.strip() for chunk in _PARAGRAPH_BREAK.split(text) if chunk.strip()]


class _TextCollector(HTMLParser):
    _SKIPPED = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth and data.strip():
            self.blocks.append(data.strip())


def _html_text(markup: str) -> str:
    collector = _TextCollector()
    collector.feed(markup)
    return "\n\n".join(collector.blocks)

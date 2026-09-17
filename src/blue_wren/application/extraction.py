import re
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from blue_wren.domain.evidence import DocumentVersion
from blue_wren.domain.extraction import (
    ExtractedDocument,
    ExtractionError,
    ExtractionUnsupported,
    TextSpan,
)

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_TABLE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def extract_text(version: DocumentVersion, content: bytes) -> ExtractedDocument:
    if sha256(content).hexdigest() != version.content_sha256:
        raise ExtractionError("content does not match document version")

    if version.media_type == "text/html":
        spans = _html_spans(version.version_id, content.decode("utf-8"))
        if not spans:
            raise ExtractionError("no extractable text")
        return ExtractedDocument(
            document_version_id=version.version_id,
            media_type=version.media_type,
            page_count=1,
            spans=spans,
        )
    if version.media_type == "text/plain":
        pages = [content.decode("utf-8")]
    elif version.media_type == "application/pdf":
        try:
            pages = [page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages]
        except PyPdfError as error:
            raise ExtractionError(f"could not read pdf: {error}") from error
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


class _SpanCollector(HTMLParser):
    _SKIPPED = frozenset({"script", "style"})
    _CELLS = frozenset({"td", "th"})
    _BLOCKS = frozenset(
        {
            "p",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "ul",
            "ol",
            "br",
            "section",
            "article",
            "header",
            "footer",
            "blockquote",
            "pre",
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
            "th",
            "title",
            "body",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str | None]] = []
        self._skip = 0
        self._tables: list[list[str | int]] = []
        self._table_count = 0
        self._cell: list[str] | None = None
        self._block: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCKS:
            self._flush()
        if tag in self._SKIPPED:
            self._skip += 1
        elif tag == "table":
            self._table_count += 1
            self._tables.append([_table_key(dict(attrs).get("id"), self._table_count), 0, 0])
        elif tag == "tr" and self._tables:
            self._tables[-1][1] = int(self._tables[-1][1]) + 1
            self._tables[-1][2] = 0
        elif tag in self._CELLS and self._tables:
            self._tables[-1][2] = int(self._tables[-1][2]) + 1
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCKS:
            self._flush()
        if tag in self._SKIPPED and self._skip:
            self._skip -= 1
        elif tag in self._CELLS and self._cell is not None:
            text = " ".join(self._cell).strip()
            if text and self._tables:
                key, row, col = self._tables[-1]
                self.items.append((text, f"table={key};row={row};col={col}"))
            self._cell = None
        elif tag == "table" and self._tables:
            self._tables.pop()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if self._skip or not text:
            return
        if self._cell is not None:
            self._cell.append(text)
        else:
            self._block.append(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join(self._block).strip()
        if text:
            self.items.append((text, None))
        self._block = []


def _table_key(identifier: str | None, ordinal: int) -> str:
    if identifier and _TABLE_ID.fullmatch(identifier):
        return identifier
    return str(ordinal)


def _html_spans(version_id: str, markup: str) -> tuple[TextSpan, ...]:
    collector = _SpanCollector()
    collector.feed(markup)
    collector.close()
    spans = []
    paragraph = 0
    for index, (text, cell) in enumerate(collector.items, 1):
        if cell is None:
            paragraph += 1
            locator = f"page=1;span={paragraph}"
        else:
            locator = f"page=1;{cell}"
        spans.append(
            TextSpan(
                document_version_id=version_id, page=1, index=index, text=text, locator=locator
            )
        )
    return tuple(spans)

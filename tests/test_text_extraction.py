from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest

from blue_wren.application.evidence import XLSX_MEDIA_TYPE, ingest_evidence
from blue_wren.application.extraction import extract_text
from blue_wren.domain.evidence import DocumentVersion, RightsBasis
from blue_wren.domain.extraction import ExtractionError, ExtractionUnsupported

PUBLISHED = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _version(content: bytes, media_type: str) -> DocumentVersion:
    return ingest_evidence(
        document_id="acme-q2-results",
        content=content,
        media_type=media_type,
        source_name="ACME investor relations",
        rights_basis=RightsBasis.PUBLIC,
        published_at=PUBLISHED,
        available_at=PUBLISHED + timedelta(minutes=1),
        ingested_at=PUBLISHED + timedelta(hours=1),
    )


def _pdf(pages: list[str]) -> bytes:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))}]"
        f" /Count {len(pages)} >>",
    ]
    for index, text in enumerate(pages):
        content_number = 4 + 2 * index
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_number} 0 R /Resources << /Font << /F1 "
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    out += trailer.encode()
    return bytes(out)


def test_plain_text_paragraphs_become_locatable_spans() -> None:
    content = b"Revenue rose to 125.0 million.\n\nEBITDA margin was 24 percent.\n"
    version = _version(content, "text/plain")

    extracted = extract_text(version, content)

    assert extracted.document_version_id == version.version_id
    assert extracted.page_count == 1
    assert [(span.page, span.index, span.text) for span in extracted.spans] == [
        (1, 1, "Revenue rose to 125.0 million."),
        (1, 2, "EBITDA margin was 24 percent."),
    ]
    assert extracted.spans[1].locator == "page=1;span=2"


def test_html_tags_and_scripts_are_stripped() -> None:
    content = (
        b"<html><head><script>alert(1)</script><style>p{}</style></head>"
        b"<body><h1>Results</h1><p>Revenue rose to 125.0 million.</p></body></html>"
    )
    version = _version(content, "text/html")

    extracted = extract_text(version, content)

    texts = [span.text for span in extracted.spans]
    assert texts == ["Results", "Revenue rose to 125.0 million."]
    assert not any("alert" in text for text in texts)


def test_html_inline_tags_do_not_fragment_a_paragraph() -> None:
    content = (
        b"<html><body><p>EBITDA margin was <b>24</b> percent this <i>quarter</i>.</p>"
        b"<p>Revenue rose to <a href='#'>125.0 million</a>.</p></body></html>"
    )
    version = _version(content, "text/html")

    extracted = extract_text(version, content)

    assert [span.text for span in extracted.spans] == [
        "EBITDA margin was 24 percent this quarter .",
        "Revenue rose to 125.0 million .",
    ]
    assert [span.locator for span in extracted.spans] == ["page=1;span=1", "page=1;span=2"]


def test_html_table_cells_become_citable_spans() -> None:
    content = (
        b"<html><body><h1>Results</h1>"
        b'<table id="results"><tr><th>Metric</th><th>FY26</th></tr>'
        b"<tr><td>Revenue</td><td>125.0</td></tr></table>"
        b"<table><tr><td>Note</td></tr></table>"
        b"<p>Outlook strong.</p></body></html>"
    )
    version = _version(content, "text/html")

    extracted = extract_text(version, content)

    assert [(span.text, span.locator) for span in extracted.spans] == [
        ("Results", "page=1;span=1"),
        ("Metric", "page=1;table=results;row=1;col=1"),
        ("FY26", "page=1;table=results;row=1;col=2"),
        ("Revenue", "page=1;table=results;row=2;col=1"),
        ("125.0", "page=1;table=results;row=2;col=2"),
        ("Note", "page=1;table=2;row=1;col=1"),
        ("Outlook strong.", "page=1;span=2"),
    ]
    assert [span.index for span in extracted.spans] == list(range(1, 8))


def test_pdf_pages_produce_page_numbered_spans() -> None:
    content = _pdf(["Revenue rose to 125.0 million.", "EBITDA margin was 24 percent."])
    version = _version(content, "application/pdf")

    extracted = extract_text(version, content)

    assert extracted.page_count == 2
    assert [(span.page, span.locator) for span in extracted.spans] == [
        (1, "page=1;span=1"),
        (2, "page=2;span=1"),
    ]
    assert "125.0" in extracted.spans[0].text
    assert "24 percent" in extracted.spans[1].text


def test_malformed_pdf_fails_explicitly() -> None:
    content = b"%PDF-1.7\nnot really a pdf"
    version = _version(content, "application/pdf")

    with pytest.raises(ExtractionError, match="could not read pdf"):
        extract_text(version, content)


def test_pdf_without_text_layer_fails_explicitly() -> None:
    content = _pdf([""])
    version = _version(content, "application/pdf")

    with pytest.raises(ExtractionError, match="no extractable text"):
        extract_text(version, content)


def test_workbooks_are_reported_as_unsupported() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    content = buffer.getvalue()
    version = _version(content, XLSX_MEDIA_TYPE)

    with pytest.raises(ExtractionUnsupported, match="spreadsheetml"):
        extract_text(version, content)


def test_content_must_match_the_version_hash() -> None:
    version = _version(b"Original text", "text/plain")

    with pytest.raises(ExtractionError, match="does not match"):
        extract_text(version, b"Tampered text")

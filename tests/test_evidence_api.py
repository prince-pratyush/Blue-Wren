from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app

PDF_CONTENT = b"%PDF-1.7\nQuarterly results"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_create_evidence_version(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["document_id"] == "acme-q2-results"
    assert body["content_sha256"] == (
        "bc42cdfc4c2dccda95c4a2a567e8debe40abc1e1b80ee5e13336711a3dcd337e"
    )
    assert body["version_id"] == f"acme-q2-results:{body['content_sha256']}"
    assert body["byte_size"] == len(PDF_CONTENT)
    assert body["media_type"] == "application/pdf"
    assert body["rights_basis"] == "public"
    assert datetime.fromisoformat(body["ingested_at"]).tzinfo is UTC


def _form(source_name: str = "ACME investor relations") -> dict[str, str]:
    return {
        "document_id": "acme-q2-results",
        "source_name": source_name,
        "rights_basis": "public",
        "published_at": "2026-08-20T08:00:00Z",
        "available_at": "2026-08-20T08:01:00Z",
    }


@pytest.mark.anyio
async def test_get_evidence_version_returns_stored_record(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    response = await client.get(f"/v1/evidence/versions/{created.json()['version_id']}")

    assert response.status_code == 200
    assert response.json() == created.json()


@pytest.mark.anyio
async def test_upload_extracts_text_spans(client: AsyncClient) -> None:
    content = b"Revenue rose to 125.0 million.\n\nEBITDA margin was 24 percent.\n"
    created = await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.txt", content, "text/plain")},
    )

    response = await client.get(f"/v1/evidence/versions/{created.json()['version_id']}/spans")

    assert response.status_code == 200
    assert response.json() == {
        "document_version_id": created.json()["version_id"],
        "status": "extracted",
        "page_count": 1,
        "reason": None,
        "spans": [
            {
                "page": 1,
                "index": 1,
                "text": "Revenue rose to 125.0 million.",
                "locator": "page=1;span=1",
            },
            {
                "page": 1,
                "index": 2,
                "text": "EBITDA margin was 24 percent.",
                "locator": "page=1;span=2",
            },
        ],
    }


@pytest.mark.anyio
async def test_upload_records_failed_extraction_for_unreadable_pdf(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    response = await client.get(f"/v1/evidence/versions/{created.json()['version_id']}/spans")

    body = response.json()
    assert body["status"] == "failed"
    assert body["reason"].startswith("could not read pdf")
    assert body["spans"] == []


@pytest.mark.anyio
async def test_spans_for_unknown_version_return_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/evidence/versions/missing/spans")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_unknown_evidence_version_returns_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/evidence/versions/missing")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_reingesting_identical_content_keeps_first_record(client: AsyncClient) -> None:
    first = await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    second = await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    assert second.status_code == 201
    assert second.json() == first.json()


@pytest.mark.anyio
async def test_reingesting_with_different_metadata_conflicts(client: AsyncClient) -> None:
    await client.post(
        "/v1/evidence/versions",
        data=_form(),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    response = await client.post(
        "/v1/evidence/versions",
        data=_form(source_name="Other source"),
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    assert response.status_code == 409
    assert "different metadata" in response.json()["detail"]


@pytest.mark.anyio
async def test_create_evidence_version_rejects_an_empty_file(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "document is empty"}


@pytest.mark.anyio
async def test_create_evidence_version_rejects_invalid_rights(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "unknown",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.pdf", PDF_CONTENT, "application/pdf")},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_evidence_version_rejects_disguised_pdf(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "content does not match declared media type"}

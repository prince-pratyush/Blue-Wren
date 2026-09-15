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

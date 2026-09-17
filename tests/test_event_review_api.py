from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.infrastructure.memory_company_store import InMemoryCompanyRepository
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(
    evidence_versions: InMemoryEvidenceVersionRepository,
    companies: InMemoryCompanyRepository,
) -> AsyncIterator[AsyncClient]:
    app = create_app(evidence_versions=evidence_versions, companies=companies)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


PAYLOAD: dict[str, Any] = {
    "event_id": "acme-q2-2026",
    "company_id": "ACME-AU",
    "comparisons": [
        {
            "actual": {
                "metric": "revenue",
                "value": "125.0",
                "unit": "AUD_millions",
                "period": "2026-Q2",
                "basis": "reported",
                "evidence": {
                    "document_id": "acme-q2-results",
                    "document_version_id": "acme-q2-results:version-1",
                    "locator": "page=2;table=results;row=revenue",
                },
            },
            "baseline": {
                "metric": "revenue",
                "value": "120.0",
                "unit": "AUD_millions",
                "period": "2026-Q2",
                "basis": "reported",
            },
        }
    ],
}


@pytest.mark.anyio
async def test_create_event_review_persists_pending_findings(client: AsyncClient) -> None:
    response = await client.post("/v1/event-reviews", json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["event_id"] == "acme-q2-2026"
    assert body["company_id"] == "ACME-AU"
    assert body["revision"] == 1
    assert len(body["findings"]) == 1
    reviewed = body["findings"][0]
    assert reviewed["finding_id"].startswith("finding-")
    assert reviewed["version"] == 1
    assert reviewed["outcome"] == "pending"
    assert reviewed["finding"]["metric"] == "revenue"
    assert reviewed["finding"]["delta"] == "5.0"
    assert reviewed["finding"]["status"] == "proposed"


@pytest.mark.anyio
async def test_get_event_review_returns_stored_state(client: AsyncClient) -> None:
    created = await client.post("/v1/event-reviews", json=PAYLOAD)

    response = await client.get("/v1/event-reviews/acme-q2-2026")

    assert response.status_code == 200
    assert response.json() == created.json()


@pytest.mark.anyio
async def test_create_event_review_rejects_duplicate_event(client: AsyncClient) -> None:
    await client.post("/v1/event-reviews", json=PAYLOAD)

    response = await client.post("/v1/event-reviews", json=PAYLOAD)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.anyio
async def test_citation_is_unresolved_without_extracted_span(client: AsyncClient) -> None:
    response = await client.post("/v1/event-reviews", json=PAYLOAD)

    assert response.json()["findings"][0]["citation_resolved"] is False
    listed = await client.get("/v1/event-reviews")
    assert listed.json()[0]["citations_unresolved"] == 1


@pytest.mark.anyio
async def test_citation_resolves_to_an_extracted_span(client: AsyncClient) -> None:
    uploaded = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={"file": ("results.txt", b"Revenue was 125.0 million.\n", "text/plain")},
    )
    version_id = uploaded.json()["version_id"]
    payload = deepcopy(PAYLOAD)
    evidence = payload["comparisons"][0]["actual"]["evidence"]
    evidence["document_version_id"] = version_id
    evidence["locator"] = "page=1;span=1"
    wrong = deepcopy(payload)
    wrong["event_id"] = "acme-q2-2026-wrong"
    wrong["comparisons"][0]["actual"]["evidence"]["locator"] = "page=1;span=9"

    resolved = await client.post("/v1/event-reviews", json=payload)
    unresolved = await client.post("/v1/event-reviews", json=wrong)

    assert resolved.json()["findings"][0]["citation_resolved"] is True
    assert unresolved.json()["findings"][0]["citation_resolved"] is False
    listed = await client.get("/v1/event-reviews")
    assert [item["citations_unresolved"] for item in listed.json()] == [0, 1]


@pytest.mark.anyio
async def test_citation_resolves_to_a_table_cell(client: AsyncClient) -> None:
    uploaded = await client.post(
        "/v1/evidence/versions",
        data={
            "document_id": "acme-q2-results",
            "source_name": "ACME investor relations",
            "rights_basis": "public",
            "published_at": "2026-08-20T08:00:00Z",
            "available_at": "2026-08-20T08:01:00Z",
        },
        files={
            "file": (
                "results.html",
                b'<html><body><table id="results"><tr><td>Revenue</td><td>125.0</td></tr>'
                b"</table></body></html>",
                "text/html",
            )
        },
    )
    payload = deepcopy(PAYLOAD)
    evidence = payload["comparisons"][0]["actual"]["evidence"]
    evidence["document_version_id"] = uploaded.json()["version_id"]
    evidence["locator"] = "page=1;table=results;row=1;col=2"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.json()["findings"][0]["citation_resolved"] is True


@pytest.mark.anyio
async def test_create_event_review_tracks_every_comparison(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    ebitda = deepcopy(payload["comparisons"][0])
    ebitda["actual"]["metric"] = "ebitda"
    ebitda["baseline"]["metric"] = "ebitda"
    payload["comparisons"].append(ebitda)

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 201
    findings = response.json()["findings"]
    assert len(findings) == 2
    assert len({finding["finding_id"] for finding in findings}) == 2
    listed = await client.get("/v1/event-reviews")
    assert listed.json()[0]["findings_total"] == 2
    assert listed.json()[0]["findings_pending"] == 2


@pytest.mark.anyio
async def test_same_metric_against_estimate_and_consensus_are_distinct(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    consensus = deepcopy(payload["comparisons"][0])
    consensus["baseline"]["value"] = "122.0"
    consensus["baseline"]["target"] = "consensus"
    payload["comparisons"].append(consensus)

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 201
    findings = response.json()["findings"]
    assert [item["finding"]["baseline_target"] for item in findings] == ["estimate", "consensus"]
    assert [item["finding"]["delta"] for item in findings] == ["5.0", "3.0"]
    assert len({item["finding_id"] for item in findings}) == 2


@pytest.mark.anyio
async def test_create_event_review_rejects_duplicate_comparisons(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["comparisons"].append(deepcopy(payload["comparisons"][0]))

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "duplicate finding identity"


@pytest.mark.anyio
async def test_create_event_review_rejects_uningested_evidence(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["comparisons"][0]["actual"]["evidence"]["document_version_id"] = (
        "acme-q2-results:version-9"
    )

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "evidence version not found: acme-q2-results:version-9"


@pytest.mark.anyio
async def test_create_event_review_rejects_evidence_from_another_document(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    payload["comparisons"][0]["actual"]["evidence"]["document_id"] = "acme-q1-results"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert "acme-q1-results" in response.json()["detail"]


@pytest.mark.anyio
async def test_create_event_review_rejects_unregistered_company(client: AsyncClient) -> None:
    payload = deepcopy(PAYLOAD)
    payload["company_id"] = "NOPE-AU"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "company not found: NOPE-AU"


@pytest.mark.anyio
async def test_get_unknown_event_review_returns_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/event-reviews/missing")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_event_reviews_is_empty_initially(client: AsyncClient) -> None:
    response = await client.get("/v1/event-reviews")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_list_event_reviews_returns_ordered_summaries(client: AsyncClient) -> None:
    zeta = deepcopy(PAYLOAD)
    zeta["event_id"] = "zeta-q2-2026"
    zeta["company_id"] = "ZETA-AU"
    await client.post("/v1/event-reviews", json=zeta)
    created = await client.post("/v1/event-reviews", json=PAYLOAD)
    finding_id = created.json()["findings"][0]["finding_id"]
    await client.post(
        f"/v1/event-reviews/acme-q2-2026/findings/{finding_id}/decisions",
        json={
            "expected_revision": 1,
            "expected_version": 1,
            "outcome": "accepted",
            "reviewer_id": "analyst-7",
        },
    )

    response = await client.get("/v1/event-reviews")

    assert response.json() == [
        {
            "event_id": "acme-q2-2026",
            "company_id": "ACME-AU",
            "revision": 2,
            "findings_total": 1,
            "findings_pending": 0,
            "citations_unresolved": 1,
        },
        {
            "event_id": "zeta-q2-2026",
            "company_id": "ZETA-AU",
            "revision": 1,
            "findings_total": 1,
            "findings_pending": 1,
            "citations_unresolved": 1,
        },
    ]


@pytest.mark.anyio
async def test_create_event_review_keeps_unresolved_findings_pending(
    client: AsyncClient,
) -> None:
    payload = deepcopy(PAYLOAD)
    payload["comparisons"][0]["baseline"]["basis"] = "underlying"

    response = await client.post("/v1/event-reviews", json=payload)

    assert response.status_code == 201
    reviewed = response.json()["findings"][0]
    assert reviewed["outcome"] == "pending"
    assert reviewed["finding"]["status"] == "unresolved"
    assert reviewed["finding"]["reason"] == "basis_mismatch"

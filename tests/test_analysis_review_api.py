import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.domain.provider import ProviderResponse, ProviderUsage
from blue_wren.infrastructure.memory_company_store import InMemoryCompanyRepository
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository
from blue_wren.infrastructure.stub_analysis_provider import StubAnalysisProvider

TEXT = b"Revenue was 125.0 million.\n\nEBITDA was 30.0 million.\n"
BASELINES: list[dict[str, str]] = [
    {
        "metric": "revenue",
        "value": "120.0",
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
    },
    {
        "metric": "ebitda",
        "value": "32.0",
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
    },
]


def _observation(metric: str, value: str, locator: str, version_id: str) -> dict[str, str]:
    return {
        "metric": metric,
        "value_text": value,
        "unit": "AUD_millions",
        "period": "2026-Q2",
        "basis": "reported",
        "document_version_id": version_id,
        "locator": locator,
    }


def _provider(
    version_id: str, *, partial: bool = False, script: bool = True
) -> StubAnalysisProvider:
    if not script:
        return StubAnalysisProvider([])
    observations = [_observation("revenue", "125.0", "page=1;span=1", version_id)]
    if not partial:
        observations.append(_observation("ebitda", "30.0", "page=1;span=2", version_id))
    text = json.dumps({"observations": observations})
    return StubAnalysisProvider(
        [ProviderResponse(text, ProviderUsage(100, 40), "end_turn", "stub-model", "req-1")]
    )


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
        uploaded = await test_client.post(
            "/v1/evidence/versions",
            data={
                "document_id": "acme-q2-results",
                "source_name": "ACME investor relations",
                "rights_basis": "public",
                "published_at": "2026-08-20T08:00:00Z",
                "available_at": "2026-08-20T08:01:00Z",
            },
            files={"file": ("results.txt", TEXT, "text/plain")},
        )
        test_client.headers["x-version-id"] = uploaded.json()["version_id"]
        test_client.headers["x-app-id"] = str(id(app))
        _APPS[str(id(app))] = app
        yield test_client


_APPS: dict[str, Any] = {}


async def _run(client: AsyncClient, *, partial: bool = False, script: bool = True) -> str:
    version_id = client.headers["x-version-id"]
    _APPS[client.headers["x-app-id"]].state.analysis_provider = _provider(
        version_id, partial=partial, script=script
    )
    created = await client.post(
        "/v1/analysis-runs",
        json={
            "event_id": "acme-q2-2026",
            "company_id": "ACME-AU",
            "idempotency_key": f"job-{partial}-{script}",
            "cutoff_at": "2026-08-20T09:00:00Z",
            "source_version_ids": [version_id],
            "baselines": BASELINES,
        },
    )
    assert created.status_code == 201
    run_id: str = created.json()["run_id"]
    return run_id


@pytest.mark.anyio
async def test_complete_run_becomes_a_review_with_resolved_citations(client: AsyncClient) -> None:
    run_id = await _run(client)

    response = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES}
    )

    assert response.status_code == 201
    findings = response.json()["findings"]
    assert [item["finding"]["metric"] for item in findings] == ["revenue", "ebitda"]
    assert [item["finding"]["delta"] for item in findings] == ["5.0", "-2.0"]
    assert all(item["citation_resolved"] for item in findings)
    readiness = await client.get("/v1/event-reviews/acme-q2-2026/export-readiness")
    assert readiness.json()["allowed"] is False
    assert {item["code"] for item in readiness.json()["blockers"]} == {"review_pending"}


@pytest.mark.anyio
async def test_accepting_every_finding_allows_export(client: AsyncClient) -> None:
    run_id = await _run(client)
    review = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES}
    )
    for item in review.json()["findings"]:
        decided = await client.post(
            f"/v1/event-reviews/acme-q2-2026/findings/{item['finding_id']}/decisions",
            json={"expected_version": 1, "outcome": "accepted", "reviewer_id": "analyst-7"},
        )
        assert decided.status_code == 200

    readiness = await client.get("/v1/event-reviews/acme-q2-2026/export-readiness")

    assert readiness.json() == {
        "event_id": "acme-q2-2026",
        "revision": 3,
        "allowed": True,
        "blockers": [],
    }


@pytest.mark.anyio
async def test_partial_run_reviews_only_covered_metrics(client: AsyncClient) -> None:
    run_id = await _run(client, partial=True)

    response = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES}
    )

    assert response.status_code == 201
    assert [item["finding"]["metric"] for item in response.json()["findings"]] == ["revenue"]


@pytest.mark.anyio
async def test_failed_run_cannot_be_reviewed(client: AsyncClient) -> None:
    run_id = await _run(client, script=False)

    response = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES}
    )

    assert response.status_code == 409
    assert "failed" in response.json()["detail"]


@pytest.mark.anyio
async def test_second_review_for_the_event_conflicts(client: AsyncClient) -> None:
    run_id = await _run(client)
    await client.post(f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES})

    response = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": BASELINES}
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.anyio
async def test_mismatched_baselines_are_rejected(client: AsyncClient) -> None:
    run_id = await _run(client)
    changed = [dict(BASELINES[0], value="121.0"), BASELINES[1]]

    response = await client.post(
        f"/v1/analysis-runs/{run_id}/event-review", json={"baselines": changed}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "baselines do not match the run"


@pytest.mark.anyio
async def test_unknown_run_returns_not_found(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/analysis-runs/run-missing/event-review", json={"baselines": BASELINES}
    )

    assert response.status_code == 404

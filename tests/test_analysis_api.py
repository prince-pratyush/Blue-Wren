import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from blue_wren.api.main import create_app
from blue_wren.domain.provider import ProviderResponse, ProviderUsage
from blue_wren.infrastructure.memory_company_store import InMemoryCompanyRepository
from blue_wren.infrastructure.memory_evidence_store import InMemoryEvidenceVersionRepository
from blue_wren.infrastructure.stub_analysis_provider import StubAnalysisProvider

TEXT = b"Revenue was 125.0 million.\n\nEBITDA was 30.0 million.\n"


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


def _scripted(version_id: str) -> StubAnalysisProvider:
    text = json.dumps(
        {
            "observations": [
                _observation("revenue", "125.0", "page=1;span=1", version_id),
                _observation("ebitda", "30.0", "page=1;span=2", version_id),
            ]
        }
    )
    response = ProviderResponse(text, ProviderUsage(120, 50), "end_turn", "stub-model", "req-1")
    return StubAnalysisProvider([response, response])


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _upload(client: AsyncClient) -> str:
    uploaded = await client.post(
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
    version_id: str = uploaded.json()["version_id"]
    return version_id


def _request(version_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event_id": "acme-q2-2026",
        "company_id": "ACME-AU",
        "idempotency_key": "job-1",
        "cutoff_at": "2026-08-20T09:00:00Z",
        "source_version_ids": [version_id],
        "baselines": [
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
        ],
    }
    body.update(overrides)
    return body


@pytest.fixture
async def client(
    evidence_versions: InMemoryEvidenceVersionRepository,
    companies: InMemoryCompanyRepository,
) -> AsyncIterator[AsyncClient]:
    app = create_app(evidence_versions=evidence_versions, companies=companies)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        version_id = await _upload(test_client)
        app.state.analysis_provider = _scripted(version_id)
        test_client.headers["x-version-id"] = version_id
        yield test_client


@pytest.mark.anyio
async def test_create_run_returns_complete_proposals(client: AsyncClient) -> None:
    version_id = client.headers["x-version-id"]

    response = await client.post("/v1/analysis-runs", json=_request(version_id))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "complete"
    assert body["failure"] is None
    assert [item["metric"] for item in body["proposed"]] == ["revenue", "ebitda"]
    assert body["proposed"][0]["evidence"] == {
        "document_id": "acme-q2-results",
        "document_version_id": version_id,
        "locator": "page=1;span=1",
    }
    assert body["usage"]["provider_calls"] == 1
    assert "Revenue was" not in response.text
    assert "source-span" not in response.text


@pytest.mark.anyio
async def test_identical_replay_returns_stored_run_without_a_new_call(client: AsyncClient) -> None:
    version_id = client.headers["x-version-id"]
    first = await client.post("/v1/analysis-runs", json=_request(version_id))

    second = await client.post("/v1/analysis-runs", json=_request(version_id))

    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(client.headers) >= 1


@pytest.mark.anyio
async def test_key_reuse_with_a_different_request_conflicts(client: AsyncClient) -> None:
    version_id = client.headers["x-version-id"]
    await client.post("/v1/analysis-runs", json=_request(version_id))
    changed = _request(version_id)
    changed["baselines"][0]["value"] = "121.0"

    response = await client.post("/v1/analysis-runs", json=changed)

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"source_version_ids": ["missing:v1"]}, "evidence version not found"),
        ({"source_version_ids": ["acme-q2-results:version-1"]}, "has no extraction"),
        ({"cutoff_at": "2026-08-20T08:00:30Z"}, "available after cutoff"),
        ({"company_id": "NOPE-AU"}, "company not found"),
    ],
)
@pytest.mark.anyio
async def test_scope_problems_are_unprocessable(
    client: AsyncClient, overrides: dict[str, Any], fragment: str
) -> None:
    response = await client.post(
        "/v1/analysis-runs", json=_request(client.headers["x-version-id"], **overrides)
    )

    assert response.status_code == 422
    assert fragment in response.json()["detail"]


@pytest.mark.anyio
async def test_failed_run_is_persisted_and_returned(
    evidence_versions: InMemoryEvidenceVersionRepository, companies: InMemoryCompanyRepository
) -> None:
    app = create_app(evidence_versions=evidence_versions, companies=companies)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        version_id = await _upload(client)

        response = await client.post("/v1/analysis-runs", json=_request(version_id))
        listed = await client.get("/v1/analysis-runs", params={"event_id": "acme-q2-2026"})

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure"] == "provider_rejected"
    assert listed.json()[0]["failure"] == "provider_rejected"
    assert listed.json()[0]["proposed_count"] == 0


@pytest.mark.anyio
async def test_get_and_list_runs(client: AsyncClient) -> None:
    version_id = client.headers["x-version-id"]
    created = await client.post("/v1/analysis-runs", json=_request(version_id))
    run_id = created.json()["run_id"]

    fetched = await client.get(f"/v1/analysis-runs/{run_id}")
    listed = await client.get("/v1/analysis-runs", params={"event_id": "acme-q2-2026"})
    empty = await client.get("/v1/analysis-runs", params={"event_id": "other"})
    missing = await client.get("/v1/analysis-runs/run-missing")

    assert fetched.json() == created.json()
    assert [item["run_id"] for item in listed.json()] == [run_id]
    assert listed.json()[0]["proposed_count"] == 2
    assert empty.json() == []
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_runs_survive_restart_with_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("BLUE_WREN_DB", str(tmp_path / "wren.db"))
    first_app = create_app()
    async with AsyncClient(transport=ASGITransport(app=first_app), base_url="http://test") as first:
        await first.post(
            "/v1/companies",
            json={"company_id": "ACME-AU", "name": "ACME Limited", "exchange": "ASX"},
        )
        version_id = await _upload(first)
        first_app.state.analysis_provider = _scripted(version_id)
        created = await first.post("/v1/analysis-runs", json=_request(version_id))
        assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as second:
        fetched = await second.get(f"/v1/analysis-runs/{created.json()['run_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    assert deepcopy(fetched.json())["status"] == "complete"

from pathlib import Path

import pytest

from blue_wren.application.company_store import (
    CompanyConflict,
    CompanyNotFound,
    CompanyRepository,
)
from blue_wren.domain.company import Company
from blue_wren.infrastructure.memory_company_store import InMemoryCompanyRepository
from blue_wren.infrastructure.sqlite_company_store import SqliteCompanyRepository

ACME = Company(company_id="ACME-AU", name="ACME Limited", exchange="ASX")
ZETA = Company(company_id="ZETA-AU", name="Zeta Holdings", exchange="ASX")


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> CompanyRepository:
    if request.param == "memory":
        return InMemoryCompanyRepository()
    return SqliteCompanyRepository(tmp_path / "companies.db")


def test_create_then_get_returns_the_company(repository: CompanyRepository) -> None:
    assert repository.create(ACME) == ACME
    assert repository.get("ACME-AU") == ACME


def test_create_rejects_a_duplicate_identifier(repository: CompanyRepository) -> None:
    repository.create(ACME)

    with pytest.raises(CompanyConflict, match="ACME-AU"):
        repository.create(Company(company_id="ACME-AU", name="Other", exchange="NYSE"))


def test_get_unknown_company_raises_not_found(repository: CompanyRepository) -> None:
    with pytest.raises(CompanyNotFound, match="missing"):
        repository.get("missing")


def test_list_is_ordered_by_identifier(repository: CompanyRepository) -> None:
    repository.create(ZETA)
    repository.create(ACME)

    assert repository.list() == (ACME, ZETA)


def test_sqlite_companies_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "companies.db"
    first = SqliteCompanyRepository(path)
    first.create(ACME)
    first.close()

    assert SqliteCompanyRepository(path).get("ACME-AU") == ACME

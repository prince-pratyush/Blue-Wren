from blue_wren.application.company_store import CompanyConflict, CompanyNotFound
from blue_wren.domain.company import Company


class InMemoryCompanyRepository:
    def __init__(self) -> None:
        self._companies: dict[str, Company] = {}

    def get(self, company_id: str) -> Company:
        try:
            return self._companies[company_id]
        except KeyError as error:
            raise CompanyNotFound(f"company not found: {company_id}") from error

    def list(self) -> tuple[Company, ...]:
        return tuple(self._companies[key] for key in sorted(self._companies))

    def create(self, company: Company) -> Company:
        if company.company_id in self._companies:
            raise CompanyConflict(f"company already exists: {company.company_id}")
        self._companies[company.company_id] = company
        return company

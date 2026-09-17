from typing import Protocol

from blue_wren.domain.company import Company


class CompanyNotFound(LookupError):
    pass


class CompanyConflict(ValueError):
    pass


class CompanyRepository(Protocol):
    def get(self, company_id: str) -> Company: ...

    def list(self) -> tuple[Company, ...]: ...

    def create(self, company: Company) -> Company: ...

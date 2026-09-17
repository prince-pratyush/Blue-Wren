from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Company:
    company_id: str
    name: str
    exchange: str

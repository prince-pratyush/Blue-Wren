import sqlite3
from pathlib import Path
from threading import Lock

from blue_wren.application.company_store import CompanyConflict, CompanyNotFound
from blue_wren.domain.company import Company

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL
)
"""


class SqliteCompanyRepository:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def get(self, company_id: str) -> Company:
        with self._lock:
            row = self._connection.execute(
                "SELECT company_id, name, exchange FROM companies WHERE company_id = ?",
                (company_id,),
            ).fetchone()
        if row is None:
            raise CompanyNotFound(f"company not found: {company_id}")
        return Company(company_id=row[0], name=row[1], exchange=row[2])

    def list(self) -> tuple[Company, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT company_id, name, exchange FROM companies ORDER BY company_id"
            ).fetchall()
        return tuple(Company(company_id=row[0], name=row[1], exchange=row[2]) for row in rows)

    def create(self, company: Company) -> Company:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO companies (company_id, name, exchange) VALUES (?, ?, ?)",
                    (company.company_id, company.name, company.exchange),
                )
        except sqlite3.IntegrityError as error:
            raise CompanyConflict(f"company already exists: {company.company_id}") from error
        return company

import re
from dataclasses import dataclass
from decimal import Decimal

_CURRENCY_UNIT = re.compile(
    r"^(?P<currency>[A-Z]{3})_(?P<scale>units|ones|thousands|millions|billions)$"
)
_SCALES = {
    "units": Decimal("1"),
    "ones": Decimal("1"),
    "thousands": Decimal("1000"),
    "millions": Decimal("1000000"),
    "billions": Decimal("1000000000"),
}


@dataclass(frozen=True, slots=True)
class _Unit:
    dimension: str
    factor: Decimal


@dataclass(frozen=True, slots=True)
class FinancialNormalization:
    source_value: Decimal
    source_unit: str
    normalized_value: Decimal
    normalized_unit: str


def convert_financial_value(
    value: Decimal,
    *,
    source_unit: str,
    target_unit: str,
) -> Decimal | None:
    if source_unit == target_unit:
        return value
    source = _parse_unit(source_unit)
    target = _parse_unit(target_unit)
    if source is None or target is None or source.dimension != target.dimension:
        return None
    return value * source.factor / target.factor


def _parse_unit(value: str) -> _Unit | None:
    currency = _CURRENCY_UNIT.fullmatch(value)
    if currency is not None:
        return _Unit(
            dimension=f"currency:{currency.group('currency')}",
            factor=_SCALES[currency.group("scale")],
        )
    if value == "basis_points":
        return _Unit(dimension="rate", factor=Decimal("0.01"))
    if value == "percentage_points":
        return _Unit(dimension="rate", factor=Decimal("1"))
    return None

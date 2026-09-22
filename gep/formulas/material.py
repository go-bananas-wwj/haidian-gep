"""GB/T 46869--2025 A.2 material-product residual-value calculation."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


_RESIDUAL_INDICATORS = {"P1", "P2", "P3", "P4", "P7"}
_COST_FIELDS = ("intermediate_cost", "labor", "depreciation", "tax_net", "capital_return")
_QUANTITY_FIELDS = {
    "P1": "quantity",
    "P2": "harvest_quantity",
    "P3": "eligible_quantity",
    "P4": "harvest_quantity",
    "P7": "deliverable_quantity",
}
_COMBINED_COST_INDICATORS = {"P3", "P4", "P7"}


@dataclass(frozen=True)
class MaterialResult:
    """One A.2 product result, or a precise no-value calculation blocker."""

    calculated: bool
    physical_value: float | None
    physical_unit: str | None
    output_value_yuan: float | None
    value_yuan: float | None
    value_wan_yuan: float | None
    standard_clause: str
    review_status: str
    blocking_fields: tuple[str, ...]


def _measurement(inputs: Mapping[str, Any], field: str, unit: str) -> float | None:
    candidate = inputs.get(field)
    if not isinstance(candidate, Mapping) or candidate.get("unit") != unit:
        return None
    value = candidate.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _price_unit(quantity_unit: str) -> str | None:
    if not quantity_unit.endswith("/a"):
        return None
    denominator = quantity_unit.removesuffix("/a")
    return f"元/{denominator}" if denominator else None


def calculate_residual_value(indicator_id: str, inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate ``(O-IC)-L-D-Tn-rK`` without converting missing data to zero.

    The caller supplies each scalar with its declared unit.  This operation is
    requires the individual non-ecological cost components for P1/P2. P3/P4/P7
    instead require one reviewed ``production_cost`` whose evidence documents
    the complete same-boundary total of those components.
    """
    if indicator_id not in _RESIDUAL_INDICATORS:
        raise ValueError("A.2 residual-value implementation does not support this indicator")
    quantity_field = _QUANTITY_FIELDS[indicator_id]
    quantity = inputs.get(quantity_field)
    quantity_unit = quantity.get("unit") if isinstance(quantity, Mapping) else None
    expected_price_unit = _price_unit(quantity_unit) if isinstance(quantity_unit, str) else None
    quantity_value = _measurement(inputs, quantity_field, quantity_unit) if isinstance(quantity_unit, str) else None
    price = _measurement(inputs, "producer_price", expected_price_unit) if expected_price_unit else None
    invalid = []
    if quantity_value is None:
        invalid.append(quantity_field)
    if price is None:
        invalid.append("producer_price")
    if indicator_id in _COMBINED_COST_INDICATORS:
        production_cost = _measurement(inputs, "production_cost", "元/a")
        if production_cost is None:
            invalid.append("production_cost")
        total_cost = production_cost
    else:
        costs = {field: _measurement(inputs, field, "元/a") for field in _COST_FIELDS}
        invalid.extend(field for field, value in costs.items() if value is None)
        total_cost = sum(costs.values()) if not invalid else None
    if invalid:
        return MaterialResult(
            False, None, None, None, None, None, "A.2", "blocked", tuple(sorted(invalid)),
        )
    output_value = quantity_value * price
    residual = output_value - total_cost
    return MaterialResult(
        True, quantity_value, quantity_unit, output_value, residual, residual / 10_000,
        "A.2", "requires_human_review" if residual < 0 else "calculated", (),
    )

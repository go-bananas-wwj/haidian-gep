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


def calculate_freshwater_supply(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate P5 from locally used water after external and recycled routes are removed."""
    local_used = _measurement(inputs, "local_used_water", "m3/a")
    outside = _measurement(inputs, "outside_water", "m3/a")
    recycled = _measurement(inputs, "recycled_water", "m3/a")
    price = _measurement(inputs, "valuation_parameter", "元/m3")
    values = {
        "local_used_water": local_used,
        "outside_water": outside,
        "recycled_water": recycled,
        "valuation_parameter": price,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.1/A.2", "blocked", tuple(sorted(invalid)))
    local_natural_water = local_used - outside - recycled
    value_yuan = local_natural_water * price
    return MaterialResult(
        True, local_natural_water, "m3/a", None, value_yuan, value_yuan / 10_000,
        "A.1/A.2", "requires_human_review" if local_natural_water < 0 else "calculated", (),
    )


def calculate_ecological_energy(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate P6 from the locally produced energy that was actually used in 2024."""
    output = _measurement(inputs, "actual_energy_output", "kWh/a")
    use = _measurement(inputs, "actual_use", "kWh/a")
    price = _measurement(inputs, "producer_price", "元/kWh")
    cost = _measurement(inputs, "production_cost", "元/a")
    values = {
        "actual_energy_output": output,
        "actual_use": use,
        "producer_price": price,
        "production_cost": cost,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.1", "blocked", tuple(sorted(invalid)))
    eligible_energy = min(output, use)
    output_value = eligible_energy * price
    residual = output_value - cost
    return MaterialResult(
        True, eligible_energy, "kWh/a", output_value, residual, residual / 10_000,
        "A.1", "requires_human_review" if residual < 0 else "calculated", (),
    )

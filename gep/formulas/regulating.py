"""GB/T 46869--2025 regulating-service calculations with explicit units."""
from __future__ import annotations

import math
from typing import Any, Mapping

from .material import MaterialResult


def _measurement(inputs: Mapping[str, Any], field: str, unit: str) -> float | None:
    candidate = inputs.get(field)
    if not isinstance(candidate, Mapping) or candidate.get("unit") != unit:
        return None
    value = candidate.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def calculate_carbon_from_npp(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R6 via reviewed annual NPP, alpha conversion, area and carbon price.

    The documented NPP path first converts gC/m²/a over hectares to tC/a,
    applies the reviewed NPP-to-net-carbon conversion factor, and then converts
    carbon to CO₂ using 44/12.  It intentionally does not treat NPP itself as
    NEP or borrow a default factor when a local method is absent.
    """
    npp = _measurement(inputs, "npp_or_nep", "gC/m2/a")
    alpha = _measurement(inputs, "respiration_or_conversion", "fraction")
    area = _measurement(inputs, "ecosystem_area", "hm2")
    price = _measurement(inputs, "carbon_price", "元/tCO2")
    invalid = []
    if npp is None or npp < 0:
        invalid.append("npp_or_nep")
    if alpha is None or not 0 < alpha <= 1:
        invalid.append("respiration_or_conversion")
    if area is None or area <= 0:
        invalid.append("ecosystem_area")
    if price is None or price < 0:
        invalid.append("carbon_price")
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.34--A.54", "blocked", tuple(sorted(invalid)))
    carbon_tco2 = npp * area * 0.01 * alpha * (44 / 12)
    value_yuan = carbon_tco2 * price
    return MaterialResult(
        True, carbon_tco2, "tCO2/a", None, value_yuan, value_yuan / 10_000,
        "A.34--A.54", "calculated", (),
    )


def calculate_oxygen_from_carbon(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R7 from a compatible annual CO₂ sequestration flow (A.55)."""
    carbon = _measurement(inputs, "carbon_sequestration_rate", "tCO2/a")
    price = _measurement(inputs, "oxygen_price", "元/tO2")
    invalid = []
    if carbon is None or carbon < 0:
        invalid.append("carbon_sequestration_rate")
    if price is None or price < 0:
        invalid.append("oxygen_price")
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.55--A.56", "blocked", tuple(sorted(invalid)))
    oxygen_tonnes = carbon * (32 / 44)
    value_yuan = oxygen_tonnes * price
    return MaterialResult(
        True, oxygen_tonnes, "tO2/a", None, value_yuan, value_yuan / 10_000,
        "A.55--A.56", "calculated", (),
    )


def calculate_water_balance(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R1 annual water conservation from P - surface runoff - actual ET."""
    precipitation = _measurement(inputs, "precipitation", "mm/a")
    runoff = _measurement(inputs, "surface_runoff", "mm/a")
    actual_et = _measurement(inputs, "actual_et", "mm/a")
    area = _measurement(inputs, "ecosystem_area", "m2")
    value_rate = _measurement(inputs, "valuation_parameter", "元/m3")
    values = {
        "precipitation": precipitation,
        "surface_runoff": runoff,
        "actual_et": actual_et,
        "ecosystem_area": area,
        "valuation_parameter": value_rate,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    if area is not None and area <= 0 and "ecosystem_area" not in invalid:
        invalid.append("ecosystem_area")
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.4--A.6", "blocked", tuple(sorted(invalid)))
    volume_m3 = (precipitation - runoff - actual_et) * area * 1e-3
    value_yuan = volume_m3 * value_rate
    return MaterialResult(
        True, volume_m3, "m3/a", None, value_yuan, value_yuan / 10_000,
        "A.4--A.6", "requires_human_review" if volume_m3 < 0 else "calculated", (),
    )

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


def calculate_crop_pollination(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R12 only after P1/R12 chooses this crop's value to be booked under R12."""
    quantity = _measurement(inputs, "crop_quantity", "t/a")
    dependence = _measurement(inputs, "pollination_dependence", "fraction")
    price = _measurement(inputs, "crop_price", "元/t")
    choice = inputs.get("deduplication_choice")
    invalid = [
        field for field, value in (("crop_quantity", quantity), ("pollination_dependence", dependence), ("crop_price", price))
        if value is None or value < 0
    ]
    if dependence is not None and dependence > 1:
        invalid.append("pollination_dependence")
    if not isinstance(choice, Mapping) or choice.get("unit") != "choice" or choice.get("value") != "exclusive_to_r12":
        invalid.append("deduplication_choice")
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.70--A.71", "blocked", tuple(sorted(invalid)))
    pollinated_quantity = quantity * dependence
    value_yuan = pollinated_quantity * price
    return MaterialResult(
        True, pollinated_quantity, "t/a", None, value_yuan, value_yuan / 10_000,
        "A.70--A.71", "calculated", (),
    )


def calculate_soil_retention(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R2 as annual potential RUSLE loss less actual cover-adjusted loss."""
    erosivity = _measurement(inputs, "rainfall_erosivity", "RUSLE-R")
    erodibility = _measurement(inputs, "soil_erodibility", "RUSLE-K")
    slope = _measurement(inputs, "slope_length", "RUSLE-LS")
    cover = _measurement(inputs, "cover_factor", "fraction")
    area = _measurement(inputs, "area", "hm2")
    price = _measurement(inputs, "valuation_parameter", "元/t")
    values = {
        "rainfall_erosivity": erosivity,
        "soil_erodibility": erodibility,
        "slope_length": slope,
        "cover_factor": cover,
        "area": area,
        "valuation_parameter": price,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    if cover is not None and cover > 1:
        invalid.append("cover_factor")
    if area is not None and area <= 0 and "area" not in invalid:
        invalid.append("area")
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.7--A.10", "blocked", tuple(sorted(invalid)))
    potential_loss = erosivity * erodibility * slope * area
    retained_soil = potential_loss * (1 - cover)
    value_yuan = retained_soil * price
    return MaterialResult(
        True, retained_soil, "t/a", None, value_yuan, value_yuan / 10_000,
        "A.7--A.10", "calculated", (),
    )


def calculate_water_purification(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate R9 from annual boundary loads after separately recorded artificial treatment."""
    inflow = _measurement(inputs, "inflow_load", "t/a")
    local = _measurement(inputs, "local_emission", "t/a")
    outflow = _measurement(inputs, "outflow_load", "t/a")
    artificial = _measurement(inputs, "artificial_treatment", "t/a")
    price = _measurement(inputs, "valuation_parameter", "元/t")
    values = {
        "inflow_load": inflow,
        "local_emission": local,
        "outflow_load": outflow,
        "artificial_treatment": artificial,
        "valuation_parameter": price,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    if invalid:
        return MaterialResult(False, None, None, None, None, None, "A.60--A.62", "blocked", tuple(sorted(invalid)))
    purified_load = inflow + local - outflow - artificial
    value_yuan = purified_load * price
    return MaterialResult(
        True, purified_load, "t/a", None, value_yuan, value_yuan / 10_000,
        "A.60--A.62", "requires_human_review" if purified_load < 0 else "calculated", (),
    )

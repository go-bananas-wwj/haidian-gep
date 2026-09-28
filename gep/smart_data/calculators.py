"""Pure, finite numeric calculators used by allowlisted Demo methods."""
from __future__ import annotations

import math


def _values(*items: float) -> tuple[float, ...]:
    result = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError("calculator input must be finite")
        result.append(float(item))
    return tuple(result)


def calculate_water_balance_demo(precipitation: float, surface_runoff: float, actual_et: float, ecosystem_area: float) -> dict:
    precipitation, surface_runoff, actual_et, ecosystem_area = _values(precipitation, surface_runoff, actual_et, ecosystem_area)
    if min(precipitation, surface_runoff, actual_et) < 0 or ecosystem_area <= 0: raise ValueError("water-balance inputs are outside their valid range")
    return {"value": (precipitation - surface_runoff - actual_et) * ecosystem_area * 10, "unit": "m3/a"}


def calculate_carbon_demo(npp: float, conversion: float, ecosystem_area: float) -> dict:
    npp, conversion, ecosystem_area = _values(npp, conversion, ecosystem_area)
    if npp < 0 or not 0 < conversion <= 1 or ecosystem_area <= 0: raise ValueError("carbon inputs are outside their valid range")
    return {"value": npp * ecosystem_area * 10 * conversion * (44 / 12), "unit": "tCO2/a"}


def calculate_oxygen_demo(carbon_sequestration_rate: float) -> dict:
    (carbon,) = _values(carbon_sequestration_rate)
    if carbon < 0: raise ValueError("carbon rate must not be negative")
    return {"value": carbon * (32 / 44), "unit": "tO2/a"}


def calculate_soil_factors_demo(rainfall_erosivity: float, soil_erodibility: float, slope_length: float, cover_factor: float, area: float) -> dict:
    rainfall_erosivity, soil_erodibility, slope_length, cover_factor, area = _values(
        rainfall_erosivity, soil_erodibility, slope_length, cover_factor, area,
    )
    if min(rainfall_erosivity, soil_erodibility, slope_length) < 0 or not 0 <= cover_factor <= 1 or area <= 0:
        raise ValueError("soil-factor inputs are outside their valid range")
    return {"value": rainfall_erosivity * soil_erodibility * slope_length * area * (1 - cover_factor), "unit": "t/a"}


def calculate_local_climate_demo(transpiration: float, ecosystem_area: float, service_days: float, energy_efficiency: float) -> dict:
    transpiration, ecosystem_area, service_days, energy_efficiency = _values(
        transpiration, ecosystem_area, service_days, energy_efficiency,
    )
    if min(transpiration, service_days) < 0 or ecosystem_area <= 0 or not 0 < energy_efficiency <= 1:
        raise ValueError("local-climate inputs are outside their valid range")
    return {"value": transpiration * ecosystem_area * 10 * 680 * service_days * energy_efficiency, "unit": "kWh/a"}


def calculate_inland_applicability_demo(inland_boundary_evidence: float) -> dict:
    (evidence,) = _values(inland_boundary_evidence)
    if evidence != 1: raise ValueError("inland boundary evidence must equal one")
    return {"value": "not_applicable", "unit": "applicability"}

"""Versioned allowlist of smart-data Demo calculation methods."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SmartMethod:
    method_id: str
    indicator_id: str
    target_metric: str
    input_units: dict[str, str]
    output_unit: str
    calculator: str
    formula: str
    version: str = "v1"


_METHODS = (
    SmartMethod("R1.water_balance.demo.v1", "R1", "water_conservation",
                {"precipitation":"mm/a", "surface_runoff":"mm/a", "actual_et":"mm/a", "ecosystem_area":"hm2"},
                "m3/a", "calculate_water_balance_demo", "(P - R - ET) × area × 10"),
    SmartMethod("R2.spatial_factors.demo.v1", "R2", "soil_retention",
                {"rainfall_erosivity":"RUSLE-R", "soil_erodibility":"RUSLE-K", "slope_length":"RUSLE-LS", "cover_factor":"fraction", "area":"hm2"},
                "t/a", "calculate_soil_factors_demo", "R × K × LS × area × (1-C)"),
    SmartMethod("R4.inland_applicability.demo.v1", "R4", "coastal_applicability",
                {"inland_boundary_evidence":"boolean"}, "applicability", "calculate_inland_applicability_demo", "verified inland boundary → not applicable"),
    SmartMethod("R6.npp_conversion.demo.v1", "R6", "carbon_sequestration_rate",
                {"npp":"kgC/m2/a", "respiration_or_conversion":"fraction", "ecosystem_area":"hm2"},
                "tCO2/a", "calculate_carbon_demo", "NPP × area × 10 × α × 44/12"),
    SmartMethod("R7.oxygen_link.demo.v1", "R7", "oxygen_provision",
                {"carbon_sequestration_rate":"tCO2/a"}, "tO2/a", "calculate_oxygen_demo", "CO2 × 32/44"),
    SmartMethod("R10.local_climate.demo.v1", "R10", "local_climate_energy",
                {"transpiration":"mm/service_day", "ecosystem_area":"hm2", "service_days":"day", "energy_efficiency":"fraction"},
                "kWh/a", "calculate_local_climate_demo", "transpiration × area × 10 × 680 × days × efficiency"),
)

SMART_METHODS = {method.method_id: method for method in _METHODS}
METHOD_BY_TARGET = {(method.indicator_id, method.target_metric): method for method in _METHODS}

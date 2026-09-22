"""Human-reviewable method-card registry for the 2024 Haidian GEP scope.

Cards identify the cited GB/T appendix range and the input contract.  They do
not supply prices, coefficients, or fabricated calculations: every card begins
pending human approval and may only become executable in a frozen data version.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MethodCard:
    indicator_id: str
    standard_clause: str
    method_id: str
    required_fields: tuple[str, ...]
    applicability_rule: str
    deduplication_rule: str
    approval_status: str = "pending_human_approval"


_CARDS = (
    MethodCard("P1", "A.1", "material.residual_value.v1",
               ("quantity", "producer_price", "intermediate_cost", "labor", "depreciation", "tax_net", "capital_return"),
               "2024 local agricultural harvest must be confirmed by product and origin.",
               "Use a mutually exclusive product hierarchy; R12 inclusion is selected once."),
    MethodCard("P2", "A.1", "material.residual_value.v1",
               ("harvest_quantity", "producer_price", "intermediate_cost", "labor", "depreciation", "tax_net", "capital_return"),
               "Local primary forest product harvest needs a 2024 operating record or verified zero evidence.",
               "Do not overlap P1 fruit, P6 biomass energy, or P7 nursery products."),
    MethodCard("P3", "A.1及表1选项", "material.residual_value.v1",
               ("applicability_evidence", "eligible_quantity", "producer_price", "production_cost"),
               "Pasture eligibility and local origin must be reviewed before valuation.",
               "Exclude purchased or out-of-area livestock products."),
    MethodCard("P4", "A.1", "material.residual_value.v1",
               ("harvest_quantity", "local_origin", "producer_price", "production_cost"),
               "Each waterbody's 2024 local harvest and inputs must be evidenced.",
               "Do not count out-of-area aquatic products."),
    MethodCard("P5", "A.1/A.2", "material.freshwater_supply.v1",
               ("local_used_water", "outside_water", "recycled_water", "valuation_parameter"),
               "Only ecosystem-provided water actually used within the accounting boundary is eligible.",
               "A water-supply path is mutually exclusive with the corresponding freshwater product value."),
    MethodCard("P6", "A.1", "material.ecological_energy.v1",
               ("actual_energy_output", "actual_use", "producer_price", "production_cost"),
               "Energy must be locally produced and actually used in 2024.",
               "Do not duplicate sales and consumption or P2 biomass material."),
    MethodCard("P7", "A.1", "material.residual_value.v1",
               ("deliverable_quantity", "product_ownership", "producer_price", "production_cost"),
               "Flower, nursery, seed, and other primary products require mutually exclusive product ownership.",
               "Product IDs must not overlap P1, P2, or P6."),
    MethodCard("R1", "A.4/A.5/A.6", "regulating.water_balance.v1",
               ("precipitation", "surface_runoff", "actual_et", "ecosystem_area", "valuation_parameter"),
               "Use 12 complete 2024 months and actual ET/surface runoff for eligible ecosystem units.",
               "Record external water separately; do not duplicate P5 under a supply method."),
    MethodCard("R2", "A.7--A.10", "regulating.soil_retention.v1",
               ("rainfall_erosivity", "soil_erodibility", "slope_length", "cover_factor", "area", "valuation_parameter"),
               "Factors and monthly cover must match the 2024 accounting period and spatial units.",
               "A prevented pollutant load is not re-booked as R9 water purification."),
    MethodCard("R3", "A.11--A.12", "regulating.wind_erosion_avoidance.v1",
               ("wind_field", "soil_properties", "roughness", "cover_factor", "valuation_parameter"),
               "Annual wind erosion process and local soil/cover applicability must be evidenced.",
               "Only the potential-minus-actual service is counted once."),
    MethodCard("R4", "A.13--A.14", "regulating.coastal_protection.v1",
               ("inland_boundary_evidence",),
               "Haidian's inland boundary evidence must be reviewed before setting not_applicable.",
               "No coastal value is created when the card is not_applicable."),
    MethodCard("R5", "A.15--A.33", "regulating.flood_storage.v1",
               ("storm_flow", "water_level", "storage_change", "ecosystem_area", "valuation_parameter"),
               "Use 2024 events or annual service-period records; do not repeat reservoir capacity monthly.",
               "Storage service and the same avoided damage are booked once."),
    MethodCard("R6", "A.34--A.54", "regulating.carbon_sequestration.v1",
               ("npp_or_nep", "respiration_or_conversion", "ecosystem_area", "carbon_price"),
               "Choose and review one eligible annual carbon pathway by ecosystem type and 2024 price basis.",
               "Annual flow is distinct from carbon stock and supports R7 only with an explicit method link."),
    MethodCard("R7", "A.55--A.56", "regulating.oxygen_provision.v1",
               ("carbon_sequestration_rate", "oxygen_price"),
               "Use the compatible approved carbon-rate pathway and a sourced oxygen price.",
               "Do not silently reuse an incompatible NEP result."),
    MethodCard("R8", "A.57--A.59", "regulating.air_purification.v1",
               ("pollutant_concentration", "emission_inventory", "removal_parameter", "ecosystem_area", "treatment_cost"),
               "Pollutants and functional-zone concentration conditions must be reviewed individually.",
               "Removal is counted by pollutant and cannot overlap another treatment service."),
    MethodCard("R9", "A.60--A.62", "regulating.water_purification.v1",
               ("inflow_load", "outflow_load", "local_emission", "artificial_treatment", "valuation_parameter"),
               "Use a source-resolved 2024 mass balance and deduct artificial treatment.",
               "Do not re-book R2's same prevented non-point load."),
    MethodCard("R10", "A.63--A.67", "regulating.local_climate.v1",
               ("temperature_humidity", "transpiration", "service_days", "energy_efficiency", "electricity_price"),
               "Only observed 2024 cooling/humidification demand days are eligible.",
               "Do not treat all ET or all green space as a service automatically."),
    MethodCard("R11", "A.68--A.69", "regulating.noise_reduction.v1",
               ("near_far_noise", "road_greenbelt_geometry", "service_days", "barrier_cost"),
               "Comparable roadside observations and eligible annual service days are required.",
               "Do not add decibel readings across road segments or duplicate barriers."),
    MethodCard("R12", "A.70--A.71", "regulating.crop_pollination.v1",
               ("crop_quantity", "pollination_dependence", "crop_price", "deduplication_choice"),
               "Use crop-specific 2024 quantity, dependency, phenology, and local applicability evidence.",
               "P1 and R12 use an explicit one-time inclusion choice."),
    MethodCard("C1", "A.72--A.75", "cultural.travel_cost.v1",
               ("visitor_count", "origin", "travel_time", "travel_cost", "attribution"),
               "Natural-site visitor records, purpose attribution, and stratified 2024 travel inputs are required.",
               "Do not substitute total tourism revenue; overlap with C2 activity time is removed."),
    MethodCard("C2", "A.76--A.77", "cultural.recreation_time.v1",
               ("visitor_count", "stay_duration", "hourly_wage", "deduplication_choice"),
               "Park/greenway user-hours need 2024 counts, duration sampling, and local hourly wage denominator.",
               "C1's same visitor activity time is not double counted."),
    MethodCard("C3", "A.78--A.82", "cultural.landscape_premium.v1",
               ("hotel_room_nights", "housing_service_area", "service_price", "landscape_premium"),
               "Use annual service use and evidenced landscape premium, not property asset sale value.",
               "Deduct overlap between accommodation/housing premium and travel expenditure."),
)


def method_cards() -> tuple[MethodCard, ...]:
    """Return all immutable method cards in stable indicator order."""
    return _CARDS

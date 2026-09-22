"""Admission checks for immutable, evidence-backed GEP input versions."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .task_service import INDICATORS


INDICATOR_IDS = tuple(
    [f"P{number}" for number in range(1, 8)]
    + [f"R{number}" for number in range(1, 13)]
    + [f"C{number}" for number in range(1, 4)]
)
APPLICABILITY_STATUSES = {"applicable", "not_applicable", "verified_zero"}
ALLOWED_UNITS = {
    "t/a", "m3/a", "元/a", "万元/a", "人次/a", "hm2", "m2", "kWh/a",
    "person-visits/a", "person-hours/a", "room-nights/a", "h/visit", "元/h",
    "元/visit", "元/room-night", "元/(m2*a)", "元/m3", "元/kWh", "元/t", "fraction", "metadata", "choice",
    "RUSLE-R", "RUSLE-K", "RUSLE-LS",
}
STRUCTURED_FIELD_UNITS = {
    "origin": "metadata",
    "deduplication_choice": "choice",
}
CORE_FIELDS = {
    "P1": "quantity|producer_price|intermediate_cost|labor|depreciation|tax_net|capital_return",
    "P2": "harvest_quantity|producer_price|intermediate_cost|labor|depreciation|tax_net|capital_return",
    "P3": "applicability_evidence|eligible_quantity|producer_price|production_cost",
    "P4": "harvest_quantity|local_origin|producer_price|production_cost",
    "P5": "local_used_water|outside_water|recycled_water|valuation_parameter",
    "P6": "actual_energy_output|actual_use|producer_price|production_cost",
    "P7": "deliverable_quantity|product_ownership|producer_price|production_cost",
    "R1": "precipitation|surface_runoff|actual_et|ecosystem_area|valuation_parameter",
    "R2": "rainfall_erosivity|soil_erodibility|slope_length|cover_factor|area|valuation_parameter",
    "R3": "wind_field|soil_properties|roughness|cover_factor|valuation_parameter",
    "R4": "inland_boundary_evidence",
    "R5": "storm_flow|water_level|storage_change|ecosystem_area|valuation_parameter",
    "R6": "npp_or_nep|respiration_or_conversion|ecosystem_area|carbon_price",
    "R7": "carbon_sequestration_rate|oxygen_price",
    "R8": "pollutant_concentration|emission_inventory|removal_parameter|ecosystem_area|treatment_cost",
    "R9": "inflow_load|outflow_load|local_emission|artificial_treatment|valuation_parameter",
    "R10": "temperature_humidity|transpiration|service_days|energy_efficiency|electricity_price",
    "R11": "near_far_noise|road_greenbelt_geometry|service_days|barrier_cost",
    "R12": "crop_quantity|pollination_dependence|crop_price|deduplication_choice",
    "C1": "visitor_count|origin|travel_time|hourly_wage|travel_cost|attribution",
    "C2": "visitor_count|stay_duration|hourly_wage|deduplication_choice",
    "C3": "hotel_room_nights|hotel_room_price|hotel_landscape_premium|housing_service_area|housing_service_price|housing_landscape_premium",
}


@dataclass(frozen=True)
class AdmissionBlocker:
    node_id: str
    code: str
    message: str


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    blockers: tuple[AdmissionBlocker, ...]
    manifest_sha256: str
    manifest: Mapping[str, Any]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _manifest_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep rejected source identities auditable without serializing NaN/Infinity."""
    result = dict(record)
    value = result.get("value")
    if isinstance(value, float) and not math.isfinite(value):
        result["value"] = None
        result["invalid_value"] = "non_finite"
    return result


def _block(node_id: Any, code: str, message: str) -> AdmissionBlocker:
    return AdmissionBlocker(str(node_id), code, message)


def admit(
    records: Iterable[Mapping[str, Any]],
    indicator_states: Mapping[str, str],
    required_nodes: Mapping[str, Iterable[str]],
    adjustments: Iterable[Mapping[str, Any]],
) -> AdmissionResult:
    """Validate accounting inputs and return a deterministic admission manifest.

    A record is admitted only when it is a reviewed 2024 Haidian source with a
    finite value, permitted unit and SHA-256 identity.  This function does not
    calculate values; it returns stable node IDs so callers can route a human
    to the precise missing or invalid input.
    """
    normalized_records = [dict(record) for record in records]
    normalized_adjustments = [dict(adjustment) for adjustment in adjustments]
    blockers: list[AdmissionBlocker] = []
    record_node_ids: set[str] = set()
    product_nodes: dict[str, list[dict[str, Any]]] = {}

    for record in normalized_records:
        node_id = str(record.get("node_id", ""))
        record_node_ids.add(node_id)
        if record.get("region_code") != "110108" or record.get("year") != 2024:
            blockers.append(_block(node_id, "outside_scope", "input must be for Haidian 110108 in 2024"))
            continue
        value = record.get("value")
        unit = record.get("unit")
        field = node_id.rsplit(".", 1)[-1]
        if _is_blank(value):
            blockers.append(_block(node_id, "missing_value", "required input has no value"))
            continue
        expected_structured_unit = STRUCTURED_FIELD_UNITS.get(field)
        if expected_structured_unit is not None:
            if unit != expected_structured_unit or not isinstance(value, str) or not value.strip():
                blockers.append(_block(node_id, "invalid_structured_value", "structured field needs its declared non-empty text value"))
                continue
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            blockers.append(_block(node_id, "non_finite_value", "input value must be a finite numeric measurement"))
            continue
        if record.get("status") != "approved":
            blockers.append(_block(node_id, "source_not_approved", "source version has not passed human review"))
            continue
        if not str(record.get("source_id", "")).strip():
            blockers.append(_block(node_id, "missing_source", "input needs a stable source ID"))
        if unit not in ALLOWED_UNITS:
            blockers.append(_block(node_id, "unsupported_unit", "input unit is not permitted by annual rules"))
        source_hash = str(record.get("sha256", ""))
        if len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash.lower()):
            blockers.append(_block(node_id, "invalid_source_hash", "input source must have a SHA-256 hash"))
        product_id = str(record.get("product_id", "")).strip()
        if product_id:
            product_nodes.setdefault(product_id, []).append(record)

    for product_records in product_nodes.values():
        indicator_ids = {str(record.get("indicator_id", "")) for record in product_records}
        if len(indicator_ids) > 1:
            for record in product_records:
                blockers.append(_block(record.get("node_id", ""), "duplicate_product_ownership", "product is assigned to more than one indicator"))

    for indicator_id in INDICATOR_IDS:
        state = indicator_states.get(indicator_id)
        if state not in APPLICABILITY_STATUSES:
            blockers.append(_block(indicator_id, "applicability_unresolved", "indicator needs an applicability conclusion"))
            continue
        if state != "applicable":
            continue
        for node_id in required_nodes.get(indicator_id, ()):
            if node_id not in record_node_ids:
                blockers.append(_block(node_id, "missing_required_field", "applicable indicator is missing a required input"))

    seen_adjustments: set[str] = set()
    for adjustment in normalized_adjustments:
        adjustment_id = str(adjustment.get("adjustment_id", "")).strip()
        node_id = str(adjustment.get("node_id", adjustment_id))
        if not adjustment_id:
            blockers.append(_block(node_id, "missing_adjustment_id", "adjustment needs a stable ID"))
        elif adjustment_id in seen_adjustments:
            blockers.append(_block(node_id, "duplicate_adjustment_id", "external/overlap adjustment IDs must be unique"))
        seen_adjustments.add(adjustment_id)
        if adjustment.get("kind") not in {"outside", "overlap"}:
            blockers.append(_block(node_id, "invalid_adjustment_kind", "adjustment kind must be outside or overlap"))

    unique = {(blocker.node_id, blocker.code): blocker for blocker in blockers}
    ordered = tuple(unique[key] for key in sorted(unique))
    manifest = {
        "schema_version": 1,
        "region_code": "110108",
        "year": 2024,
        "records": sorted((_manifest_record(record) for record in normalized_records), key=lambda record: str(record.get("node_id", ""))),
        "indicator_states": dict(sorted(indicator_states.items())),
        "required_nodes": {key: sorted(value) for key, value in sorted(required_nodes.items())},
        "adjustments": sorted(normalized_adjustments, key=lambda adjustment: str(adjustment.get("adjustment_id", ""))),
        "blockers": [blocker.__dict__ for blocker in ordered],
    }
    manifest_sha256 = hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    return AdmissionResult(not ordered, ordered, manifest_sha256, manifest)


def write_manifest(path: str | Path, result: AdmissionResult) -> Path:
    """Create one immutable JSON manifest; replacing a frozen version is forbidden."""
    target = Path(path)
    payload = {**result.manifest, "manifest_sha256": result.manifest_sha256, "accepted": result.accepted}
    with target.open("x", encoding="utf-8") as output:
        output.write(_canonical(payload))
        output.write("\n")
    return target


def write_admission_catalogs(directory: str | Path, result: AdmissionResult) -> dict[str, Path]:
    """Create a non-overwritable, versioned admission package for all 22 items."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=False)
    status = "accepted" if result.accepted else "blocked"
    files = {
        "indicator_catalog.csv": (
            ["indicator_id", "name", "category", "applicability_status", "admission_status"],
            [
                [indicator_id, name, category, result.manifest["indicator_states"].get(indicator_id, "pending"), status]
                for indicator_id, name, category in INDICATORS
            ],
        ),
        "field_matrix.csv": (
            ["indicator_id", "core_required_fields", "field_status"],
            [[indicator_id, CORE_FIELDS[indicator_id], "pending_data_or_review"] for indicator_id in INDICATOR_IDS],
        ),
        "annual_rules.csv": (
            ["region_code", "year", "start_date", "end_date_exclusive", "day_count", "price_base_year", "status"],
            [["110108", "2024", "2024-01-01", "2025-01-01", "366", "2024", "frozen_scope"]],
        ),
        "adjustments.csv": (
            ["adjustment_id", "kind", "amount_yuan", "booking_level", "source_id", "reason", "status"],
            [],
        ),
        "data_manifest.csv": (
            ["manifest_sha256", "admission_status", "record_count", "blocker_count", "scope"],
            [[result.manifest_sha256, status, str(len(result.manifest["records"])), str(len(result.blockers)), "input_admission"]],
        ),
    }
    written: dict[str, Path] = {}
    for filename, (headers, rows) in files.items():
        output = target / filename
        with output.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        written[filename] = output
    return written

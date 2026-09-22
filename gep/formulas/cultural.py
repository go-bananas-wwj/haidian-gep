"""GB/T 46869--2025 annual cultural-service calculations."""
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


def _origin_is_recorded(inputs: Mapping[str, Any]) -> bool:
    origin = inputs.get("origin")
    return isinstance(origin, Mapping) and origin.get("unit") == "metadata" and isinstance(origin.get("value"), str) and bool(origin["value"].strip())


def _choice_is_exclusive_to_c2(inputs: Mapping[str, Any]) -> bool:
    choice = inputs.get("deduplication_choice")
    return isinstance(choice, Mapping) and choice.get("unit") == "choice" and choice.get("value") == "exclusive_to_c2"


def _blocked(clause: str, fields: list[str]) -> MaterialResult:
    return MaterialResult(False, None, None, None, None, None, clause, "blocked", tuple(sorted(fields)))


def calculate_travel_cost(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate C1 as annual visitor count times attributed time and direct cost."""
    visitors = _measurement(inputs, "visitor_count", "person-visits/a")
    travel_time = _measurement(inputs, "travel_time", "h/visit")
    wage = _measurement(inputs, "hourly_wage", "元/h")
    cost = _measurement(inputs, "travel_cost", "元/visit")
    attribution = _measurement(inputs, "attribution", "fraction")
    invalid = [
        field for field, value in (("visitor_count", visitors), ("travel_time", travel_time), ("hourly_wage", wage), ("travel_cost", cost), ("attribution", attribution))
        if value is None or value < 0
    ]
    if attribution is not None and attribution > 1:
        invalid.append("attribution")
    if not _origin_is_recorded(inputs):
        invalid.append("origin")
    if invalid:
        return _blocked("A.72--A.75", invalid)
    value_yuan = visitors * (travel_time * wage + cost) * attribution
    return MaterialResult(True, visitors, "person-visits/a", None, value_yuan, value_yuan / 10_000, "A.72--A.75", "calculated", ())


def calculate_recreation_time(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate C2 only when the C1 overlap choice explicitly assigns this activity to C2."""
    visitors = _measurement(inputs, "visitor_count", "person-visits/a")
    duration = _measurement(inputs, "stay_duration", "h/visit")
    wage = _measurement(inputs, "hourly_wage", "元/h")
    invalid = [
        field for field, value in (("visitor_count", visitors), ("stay_duration", duration), ("hourly_wage", wage))
        if value is None or value < 0
    ]
    if not _choice_is_exclusive_to_c2(inputs):
        invalid.append("deduplication_choice")
    if invalid:
        return _blocked("A.76--A.77", invalid)
    hours = visitors * duration
    value_yuan = hours * wage
    return MaterialResult(True, hours, "person-hours/a", None, value_yuan, value_yuan / 10_000, "A.76--A.77", "calculated", ())


def calculate_landscape_premium(inputs: Mapping[str, Any]) -> MaterialResult:
    """Calculate C3 from annual accommodation and housing service flows, never asset values."""
    room_nights = _measurement(inputs, "hotel_room_nights", "room-nights/a")
    room_price = _measurement(inputs, "hotel_room_price", "元/room-night")
    room_premium = _measurement(inputs, "hotel_landscape_premium", "fraction")
    home_area = _measurement(inputs, "housing_service_area", "m2")
    home_price = _measurement(inputs, "housing_service_price", "元/(m2*a)")
    home_premium = _measurement(inputs, "housing_landscape_premium", "fraction")
    values = {
        "hotel_room_nights": room_nights,
        "hotel_room_price": room_price,
        "hotel_landscape_premium": room_premium,
        "housing_service_area": home_area,
        "housing_service_price": home_price,
        "housing_landscape_premium": home_premium,
    }
    invalid = [field for field, value in values.items() if value is None or value < 0]
    invalid.extend(field for field in ("hotel_landscape_premium", "housing_landscape_premium") if values[field] is not None and values[field] > 1)
    if invalid:
        return _blocked("A.78--A.82", invalid)
    value_yuan = room_nights * room_price * room_premium + home_area * home_price * home_premium
    return MaterialResult(True, None, None, None, value_yuan, value_yuan / 10_000, "A.78--A.82", "calculated", ())

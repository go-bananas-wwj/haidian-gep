"""Exactly-once external-source and overlap adjustment ledger."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Adjustment:
    adjustment_id: str
    kind: str
    amount_yuan: float
    booking_level: str
    reason: str


@dataclass(frozen=True)
class LedgerResult:
    gross_value_yuan: float
    total_adjustment_yuan: float
    gep_value_yuan: float
    gep_value_wan_yuan: float
    applied_adjustment_ids: tuple[str, ...]
    already_booked_adjustment_ids: tuple[str, ...]


def apply_adjustments(category_values_yuan: Mapping[str, float], adjustments: Iterable[Adjustment]) -> LedgerResult:
    """Apply only adjustments not already deducted inside a category/item value."""
    amounts = []
    for category, value in category_values_yuan.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"category {category} must have a finite yuan value")
        amounts.append(float(value))
    normalized = list(adjustments)
    identifiers = [adjustment.adjustment_id for adjustment in normalized]
    if any(not identifier.strip() for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("each adjustment needs a unique non-empty adjustment_id")
    for adjustment in normalized:
        if adjustment.kind not in {"outside", "overlap"}:
            raise ValueError("adjustment kind must be outside or overlap")
        if adjustment.booking_level not in {"item", "total"}:
            raise ValueError("adjustment booking_level must be item or total")
        if isinstance(adjustment.amount_yuan, bool) or not isinstance(adjustment.amount_yuan, (int, float)) or not math.isfinite(adjustment.amount_yuan) or adjustment.amount_yuan < 0:
            raise ValueError("adjustment amount must be a finite non-negative yuan value")
        if not adjustment.reason.strip():
            raise ValueError("adjustment reason is required")
    gross = sum(amounts)
    total_level = tuple(adjustment for adjustment in normalized if adjustment.booking_level == "total")
    item_level = tuple(adjustment for adjustment in normalized if adjustment.booking_level == "item")
    deduction = sum(float(adjustment.amount_yuan) for adjustment in total_level)
    return LedgerResult(
        gross, deduction, gross - deduction, (gross - deduction) / 10_000,
        tuple(adjustment.adjustment_id for adjustment in total_level),
        tuple(adjustment.adjustment_id for adjustment in item_level),
    )

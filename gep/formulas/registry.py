"""Approved formula dispatch without fallback estimates or fabricated values."""
from __future__ import annotations

from typing import Any, Mapping

from ..methods import method_cards
from .material import MaterialResult, calculate_residual_value
from .regulating import calculate_carbon_from_npp, calculate_oxygen_from_carbon


_CARDS = {card.indicator_id: card for card in method_cards()}


def calculate_indicator(indicator_id: str, inputs: Mapping[str, Any]) -> MaterialResult:
    """Dispatch an implemented method or return a durable no-value blocker.

    A card being reviewed is not the same thing as its mathematical method
    being implemented.  The registry makes that gap explicit so a complete
    looking graph cannot create an unsupported formal GEP figure.
    """
    if indicator_id not in _CARDS:
        raise ValueError("indicator must be one of the 22 registered GEP subjects")
    if indicator_id in {"P1", "P2"}:
        return calculate_residual_value(indicator_id, inputs)
    if indicator_id == "R6":
        return calculate_carbon_from_npp(inputs)
    if indicator_id == "R7":
        return calculate_oxygen_from_carbon(inputs)
    return MaterialResult(
        False, None, None, None, None, None,
        _CARDS[indicator_id].standard_clause, "blocked", ("method_implementation_pending",),
    )

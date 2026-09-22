"""Deterministic evaluation of immutable task-graph snapshots."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .formulas.registry import calculate_indicator
from .methods import method_cards


@dataclass(frozen=True)
class RunEvaluation:
    """Computed item values plus the exact reasons a formal total is unavailable."""

    formal_gep_value_yuan: float | None
    item_results: Mapping[str, Mapping[str, Any]]
    partial_category_totals_yuan: Mapping[str, float]
    blocking_nodes: tuple[str, ...]


def _indicator_inputs(nodes: list[Mapping[str, Any]], indicator_id: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.get("kind") != "input" or node.get("parent_key") != indicator_id:
            continue
        field = str(node.get("node_key", "")).rsplit(".", 1)[-1]
        if field in fields:
            # A product hierarchy needs an explicit aggregation method, not an
            # arbitrary last-write-wins choice.
            fields[field] = {"value": None, "unit": None}
        else:
            fields[field] = {"value": node.get("value"), "unit": node.get("unit")}
    return fields


def _empty_item(status: str) -> dict[str, Any]:
    return {
        "calculated": False,
        "physical_value": None,
        "physical_unit": None,
        "output_value_yuan": None,
        "value_yuan": None,
        "value_wan_yuan": None,
        "standard_clause": None,
        "review_status": status,
        "blocking_fields": (),
    }


def evaluate_frozen_graph(graph: Mapping[str, Any]) -> RunEvaluation:
    """Evaluate supported approved methods and never infer a missing GEP total.

    This function has no database writes and consumes only the supplied frozen
    graph.  It exposes a partial category subtotal solely for independently
    calculated items; a formal total exists only when every registered subject
    is present and either calculated or explicitly non-applicable/verified-zero.
    """
    nodes = list(graph.get("nodes", ()))
    indicators = {
        str(node.get("node_key")): node
        for node in nodes
        if node.get("kind") == "indicator"
    }
    items: dict[str, dict[str, Any]] = {}
    category_totals = {"material": 0.0, "regulating": 0.0, "cultural": 0.0}
    blocking: list[str] = []
    for card in method_cards():
        indicator = indicators.get(card.indicator_id)
        if indicator is None:
            items[card.indicator_id] = _empty_item("missing_indicator")
            blocking.append(f"{card.indicator_id}:missing_indicator")
            continue
        applicability = indicator.get("applicability_status")
        if applicability == "not_applicable":
            items[card.indicator_id] = _empty_item("not_applicable")
            continue
        if applicability == "verified_zero":
            item = _empty_item("verified_zero")
            item["value_yuan"] = 0.0
            item["value_wan_yuan"] = 0.0
            items[card.indicator_id] = item
            continue
        if applicability != "applicable":
            items[card.indicator_id] = _empty_item("applicability_unresolved")
            blocking.append(f"{card.indicator_id}:applicability_unresolved")
            continue
        result = asdict(calculate_indicator(card.indicator_id, _indicator_inputs(nodes, card.indicator_id)))
        items[card.indicator_id] = result
        if result["calculated"]:
            category_totals[str(indicator.get("category"))] += float(result["value_yuan"])
        else:
            blocking.extend(f"{card.indicator_id}:{field}" for field in result["blocking_fields"])
    adjustment_ledger = graph.get("adjustment_ledger")
    if not isinstance(adjustment_ledger, Mapping) or adjustment_ledger.get("status") != "approved":
        blocking.append("adjustment_ledger:missing_or_unapproved")
    return RunEvaluation(
        None if blocking else sum(category_totals.values()),
        items,
        {category: value for category, value in category_totals.items() if value},
        tuple(sorted(blocking)),
    )

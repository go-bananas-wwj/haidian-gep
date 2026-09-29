"""Deterministic provenance, scope, unit, freshness, and conflict checks."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ValidationResult:
    accepted_items: tuple[dict[str, Any], ...]
    rejected_items: tuple[dict[str, Any], ...]
    risk_tier: str
    conflicts: tuple[dict[str, Any], ...]
    unit_conversions: tuple[dict[str, Any], ...]
    human_action: dict[str, Any] | None


class EvidenceValidator:
    LOCAL_TYPES = {"admitted_observation", "local_admitted", "derived_observation"}
    OFFICIAL_TYPES = {"official_web", "official_dataset", "public_dataset", "government_statistics"}
    PROXY_TYPES = {"paper", "literature", "model_estimate", "proxy"}

    CONVERSIONS: dict[tuple[str, str], tuple[float, float, str]] = {
        ("km2", "hm2"): (100.0, 0.0, "km2 × 100 = hm2"),
        ("m2", "hm2"): (0.0001, 0.0, "m2 × 0.0001 = hm2"),
        ("ha", "hm2"): (1.0, 0.0, "ha × 1 = hm2"),
        ("hm2", "ha"): (1.0, 0.0, "hm2 × 1 = ha"),
        ("hm2", "km2"): (0.01, 0.0, "hm2 × 0.01 = km2"),
        ("C", "K"): (1.0, 273.15, "C + 273.15 = K"),
    }

    @staticmethod
    def _reject(item: Mapping[str, Any], reason: str) -> dict[str, Any]:
        return {"item": dict(item), "reason": reason}

    @staticmethod
    def _provenance_complete(item: Mapping[str, Any]) -> bool:
        source_hash = item.get("source_sha256") or item.get("content_sha256")
        checked = item.get("checked_utc") or item.get("fetched_utc")
        return all(str(value or "").strip() for value in (item.get("source_id"), item.get("locator"), source_hash, checked))

    def _normalize_unit(
        self,
        value: Any,
        source_unit: str,
        target_unit: str,
    ) -> tuple[Any, dict[str, Any] | None]:
        if source_unit == target_unit:
            return value, None
        conversion = self.CONVERSIONS.get((source_unit, target_unit))
        if conversion is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("unit_mismatch")
        factor, offset, formula = conversion
        normalized = float(value) * factor + offset
        return normalized, {
            "from_unit": source_unit,
            "to_unit": target_unit,
            "factor": factor,
            "offset": offset,
            "formula": formula,
            "input_value": value,
            "output_value": normalized,
        }

    @staticmethod
    def _conflict(accepted: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
        numeric = [
            (item.get("source_id"), item.get("normalized_value"))
            for item in accepted
            if isinstance(item.get("normalized_value"), (int, float))
            and not isinstance(item.get("normalized_value"), bool)
            and math.isfinite(float(item["normalized_value"]))
        ]
        if len(numeric) < 2:
            return None
        reference = float(numeric[0][1])
        if all(math.isclose(float(value), reference, rel_tol=1e-9, abs_tol=1e-9) for _source, value in numeric[1:]):
            return None
        return {
            "reason_code": "source_conflict",
            "values": [{"source_id": source, "value": value} for source, value in numeric],
        }

    def validate(
        self,
        target: Mapping[str, Any],
        items: Sequence[Mapping[str, Any]],
    ) -> ValidationResult:
        metric = str(target.get("metric", ""))
        region_code = str(target.get("region_code", ""))
        year = int(target.get("year") or 0)
        unit = str(target.get("unit", ""))
        if not metric or not region_code or year <= 0 or not unit:
            raise ValueError("target requires metric, region_code, year, and unit")

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        conversions: list[dict[str, Any]] = []
        tiers: list[str] = []

        for raw in items:
            item = dict(raw)
            if str(item.get("metric", "")) != metric:
                rejected.append(self._reject(item, "metric_mismatch"))
                continue
            if not self._provenance_complete(item):
                rejected.append(self._reject(item, "missing_provenance"))
                continue
            source_type = str(item.get("source_type", ""))
            item_region = str(item.get("region_code", ""))
            if item_region == region_code:
                region_match = "exact"
            elif item.get("proxy_allowed"):
                region_match = "proxy"
            else:
                rejected.append(self._reject(item, "region_mismatch"))
                continue
            try:
                item_year = int(item.get("year") or 0)
            except (TypeError, ValueError):
                rejected.append(self._reject(item, "year_mismatch"))
                continue

            cautions: list[str] = []
            time_match = "exact" if item_year == year else "historical"
            value_kind = str(target.get("value_kind") or "")
            is_price = value_kind == "price" or metric.endswith("_price") or metric == "price"
            if item_year != year:
                max_age = int(target.get("max_age_years", 0 if not is_price else 1))
                if is_price and year - item_year > max_age:
                    cautions.append("stale")
                elif not item.get("proxy_allowed"):
                    rejected.append(self._reject(item, "year_mismatch"))
                    continue
                else:
                    cautions.append("historical_proxy")
            try:
                normalized_value, conversion = self._normalize_unit(item.get("value"), str(item.get("unit", "")), unit)
            except ValueError:
                rejected.append(self._reject(item, "unit_mismatch"))
                continue
            if conversion:
                conversions.append({"source_id": item.get("source_id"), **conversion})

            if source_type in self.LOCAL_TYPES and region_match == "exact" and time_match == "exact":
                tier = "A"
            elif source_type in self.OFFICIAL_TYPES and item.get("reproducible", False):
                tier = "B"
            else:
                tier = "C"
            if region_match == "proxy" or cautions or source_type in self.PROXY_TYPES:
                tier = "C"
            normalized = {
                **item,
                "normalized_value": normalized_value,
                "normalized_unit": unit,
                "region_match": region_match,
                "time_match": time_match,
                "cautions": tuple(cautions),
                "risk_tier": tier,
            }
            accepted.append(normalized)
            tiers.append(tier)

        conflict = self._conflict(accepted)
        if conflict:
            source_ids = [str(item.get("source_id")) for item in accepted]
            return ValidationResult(
                accepted_items=tuple(accepted),
                rejected_items=tuple(rejected),
                risk_tier="D",
                conflicts=(conflict,),
                unit_conversions=tuple(conversions),
                human_action={
                    "reason_code": "source_conflict",
                    "title": "确认冲突数据口径",
                    "source_ids": source_ids,
                },
            )
        if not accepted:
            return ValidationResult(
                accepted_items=(),
                rejected_items=tuple(rejected),
                risk_tier="D",
                conflicts=(),
                unit_conversions=tuple(conversions),
                human_action={
                    "reason_code": "no_valid_evidence",
                    "title": "补充可核验的数据来源",
                    "source_ids": [],
                },
            )
        severity = {"A": 1, "B": 2, "C": 3}
        risk_tier = max(tiers, key=severity.__getitem__)
        return ValidationResult(
            accepted_items=tuple(accepted),
            rejected_items=tuple(rejected),
            risk_tier=risk_tier,
            conflicts=(),
            unit_conversions=tuple(conversions),
            human_action=None,
        )

"""Strict, JSON-safe smart-data records shared by storage and execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import math
from typing import Any, Mapping
from urllib.parse import urlparse


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _sha256(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text.lower()):
        raise ValueError(f"{name} must be a 64-character SHA-256")
    return text.lower()


def _date(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO date") from error
    return text


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _json_safe(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain only finite JSON numbers")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, name) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, name) for key, item in value.items()}
    raise ValueError(f"{name} must contain JSON data only")


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    asset_version: str
    asset_type: str
    title: str
    publisher: str
    source_url: str | None
    license_or_access: str
    period_start: str
    period_end: str
    region_code: str
    bbox: tuple[float, float, float, float] | None
    crs: str | None
    local_path: str | None
    sha256: str
    quality_status: str
    quality: dict[str, Any]
    created_utc: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AssetRecord":
        source_url = _text(payload.get("source_url"), "source_url", optional=True)
        if source_url is not None and urlparse(source_url).scheme != "https":
            raise ValueError("remote source_url must use HTTPS")
        raw_bbox = payload.get("bbox")
        bbox = None
        if raw_bbox is not None:
            if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
                raise ValueError("bbox must contain west, south, east, north")
            bbox = tuple(_finite(value, "bbox") for value in raw_bbox)
            if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise ValueError("bbox bounds are reversed")
        period_start = _date(payload.get("period_start"), "period_start")
        period_end = _date(payload.get("period_end"), "period_end")
        if period_start > period_end:
            raise ValueError("asset period_start must not follow period_end")
        return cls(
            asset_id=_text(payload.get("asset_id"), "asset_id"),
            asset_version=_text(payload.get("asset_version"), "asset_version"),
            asset_type=_text(payload.get("asset_type"), "asset_type"),
            title=_text(payload.get("title"), "title"),
            publisher=_text(payload.get("publisher"), "publisher"),
            source_url=source_url,
            license_or_access=_text(payload.get("license_or_access"), "license_or_access"),
            period_start=period_start,
            period_end=period_end,
            region_code=_text(payload.get("region_code"), "region_code"),
            bbox=bbox,
            crs=_text(payload.get("crs"), "crs", optional=True),
            local_path=_text(payload.get("local_path"), "local_path", optional=True),
            sha256=_sha256(payload.get("sha256"), "sha256"),
            quality_status=_text(payload.get("quality_status"), "quality_status"),
            quality=_json_safe(payload.get("quality", {}), "quality"),
            created_utc=_text(payload.get("created_utc", _now()), "created_utc"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id, "asset_version": self.asset_version, "asset_type": self.asset_type,
            "title": self.title, "publisher": self.publisher, "source_url": self.source_url,
            "license_or_access": self.license_or_access, "period_start": self.period_start,
            "period_end": self.period_end, "region_code": self.region_code,
            "bbox": list(self.bbox) if self.bbox is not None else None, "crs": self.crs,
            "local_path": self.local_path, "sha256": self.sha256, "quality_status": self.quality_status,
            "quality": self.quality, "created_utc": self.created_utc,
        }


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    metric: str
    value: float
    unit: str
    region_code: str
    year: int
    spatial_grain: str
    method_id: str
    method_version: str
    input_asset_ids: tuple[str, ...]
    confidence: float
    uncertainty: dict[str, Any]
    evidence_class: str
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    created_utc: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservationRecord":
        year = payload.get("year")
        if isinstance(year, bool) or not isinstance(year, int) or year < 1900 or year > 2200:
            raise ValueError("year must be a four-digit integer")
        asset_ids = payload.get("input_asset_ids")
        if not isinstance(asset_ids, (list, tuple)) or not asset_ids:
            raise ValueError("input_asset_ids must not be empty")
        normalized_ids = tuple(_text(item, "input_asset_id") for item in asset_ids)
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("input_asset_ids must be unique")
        confidence = _finite(payload.get("confidence"), "confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        artifact_path = _text(payload.get("artifact_path"), "artifact_path", optional=True)
        artifact_sha256 = _sha256(payload.get("artifact_sha256"), "artifact_sha256", optional=True)
        if artifact_path is not None and artifact_sha256 is None:
            raise ValueError("artifact_path requires artifact_sha256")
        return cls(
            observation_id=_text(payload.get("observation_id"), "observation_id"),
            metric=_text(payload.get("metric"), "metric"), value=_finite(payload.get("value"), "value"),
            unit=_text(payload.get("unit"), "unit"), region_code=_text(payload.get("region_code"), "region_code"),
            year=year, spatial_grain=_text(payload.get("spatial_grain"), "spatial_grain"),
            method_id=_text(payload.get("method_id"), "method_id"),
            method_version=_text(payload.get("method_version"), "method_version"),
            input_asset_ids=normalized_ids, confidence=confidence,
            uncertainty=_json_safe(payload.get("uncertainty", {}), "uncertainty"),
            evidence_class=_text(payload.get("evidence_class"), "evidence_class"),
            artifact_path=artifact_path, artifact_sha256=artifact_sha256,
            created_utc=_text(payload.get("created_utc", _now()), "created_utc"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id, "metric": self.metric, "value": self.value,
            "unit": self.unit, "region_code": self.region_code, "year": self.year,
            "spatial_grain": self.spatial_grain, "method_id": self.method_id,
            "method_version": self.method_version, "input_asset_ids": list(self.input_asset_ids),
            "confidence": self.confidence, "uncertainty": self.uncertainty,
            "evidence_class": self.evidence_class, "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256, "created_utc": self.created_utc,
        }


@dataclass(frozen=True)
class CalculationPlan:
    plan_id: str
    task_id: str
    node_id: str
    target_metric: str
    method_id: str
    method_version: str
    input_bindings: dict[str, str]
    operations: tuple[dict[str, Any], ...]
    planner: str
    planner_model: str
    explanation: str
    schema_version: str
    status: str
    created_utc: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CalculationPlan":
        bindings = payload.get("input_bindings")
        if not isinstance(bindings, Mapping) or not bindings:
            raise ValueError("input_bindings must not be empty")
        clean_bindings = {_text(key, "input binding"): _text(value, "observation_id") for key, value in bindings.items()}
        operations = payload.get("operations")
        if not isinstance(operations, (list, tuple)):
            raise ValueError("operations must be a list")
        clean_operations = _json_safe(operations, "operations")
        if not all(isinstance(operation, dict) for operation in clean_operations):
            raise ValueError("every operation must be an object")
        return cls(
            plan_id=_text(payload.get("plan_id"), "plan_id"), task_id=_text(payload.get("task_id"), "task_id"),
            node_id=_text(payload.get("node_id"), "node_id"), target_metric=_text(payload.get("target_metric"), "target_metric"),
            method_id=_text(payload.get("method_id"), "method_id"), method_version=_text(payload.get("method_version"), "method_version"),
            input_bindings=clean_bindings, operations=tuple(clean_operations), planner=_text(payload.get("planner"), "planner"),
            planner_model=_text(payload.get("planner_model"), "planner_model"), explanation=_text(payload.get("explanation"), "explanation"),
            schema_version=_text(payload.get("schema_version"), "schema_version"), status=_text(payload.get("status"), "status"),
            created_utc=_text(payload.get("created_utc", _now()), "created_utc"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id, "task_id": self.task_id, "node_id": self.node_id,
            "target_metric": self.target_metric, "method_id": self.method_id,
            "method_version": self.method_version, "input_bindings": dict(self.input_bindings),
            "operations": list(self.operations), "planner": self.planner, "planner_model": self.planner_model,
            "explanation": self.explanation, "schema_version": self.schema_version,
            "status": self.status, "created_utc": self.created_utc,
        }


@dataclass(frozen=True)
class CalculationResult:
    calculation_run_id: str
    plan_id: str
    code_version: str
    input_manifest_sha256: str
    parameter_manifest_sha256: str
    result: dict[str, Any]
    result_sha256: str
    quality: dict[str, Any]
    status: str
    error_code: str | None
    created_utc: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CalculationResult":
        result = _json_safe(payload.get("result"), "result")
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        return cls(
            calculation_run_id=_text(payload.get("calculation_run_id"), "calculation_run_id"),
            plan_id=_text(payload.get("plan_id"), "plan_id"), code_version=_text(payload.get("code_version"), "code_version"),
            input_manifest_sha256=_sha256(payload.get("input_manifest_sha256"), "input_manifest_sha256"),
            parameter_manifest_sha256=_sha256(payload.get("parameter_manifest_sha256"), "parameter_manifest_sha256"),
            result=result, result_sha256=_sha256(payload.get("result_sha256"), "result_sha256"),
            quality=_json_safe(payload.get("quality", {}), "quality"), status=_text(payload.get("status"), "status"),
            error_code=_text(payload.get("error_code"), "error_code", optional=True),
            created_utc=_text(payload.get("created_utc", _now()), "created_utc"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "calculation_run_id": self.calculation_run_id, "plan_id": self.plan_id,
            "code_version": self.code_version, "input_manifest_sha256": self.input_manifest_sha256,
            "parameter_manifest_sha256": self.parameter_manifest_sha256, "result": self.result,
            "result_sha256": self.result_sha256, "quality": self.quality, "status": self.status,
            "error_code": self.error_code, "created_utc": self.created_utc,
        }

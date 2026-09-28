"""Weakly supervised, spatially validated classification of 2024 AEF embeddings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import tempfile
from typing import Any, Iterable

from .types import ObservationRecord
from .aef_pipeline import load_boundary_descriptor


CLASS_NAMES = {
    10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
    50: "built_up", 60: "bare_sparse", 70: "snow_ice", 80: "water",
    90: "herbaceous_wetland", 95: "mangroves", 100: "moss_lichen",
}
GREEN_CLASSES = frozenset({10, 20, 30, 40, 90, 95, 100})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def _features(raw: Any) -> Any:
    import numpy as np
    values = raw.astype("float32")
    return np.sign(values) * np.square(values / np.float32(127.5))


@dataclass(frozen=True)
class SpatialSplit:
    train_indices: tuple[int, ...]
    holdout_indices: tuple[int, ...]
    train_block_ids: tuple[int, ...]
    holdout_block_ids: tuple[int, ...]


@dataclass(frozen=True)
class ClassificationGate:
    auto_usable: bool
    reasons: tuple[str, ...]
    official_area_difference_fraction: float | None


@dataclass(frozen=True)
class AefModelResult:
    model_path: Path
    report_path: Path
    model_sha256: str
    sample_index_sha256: str
    parameters_sha256: str
    aef_sha256: str
    label_sha256: str
    macro_f1: float
    per_class_recall: dict[int, float]
    per_class_iou: dict[int, float]
    classes: tuple[int, ...]
    train_block_ids: tuple[int, ...]
    holdout_block_ids: tuple[int, ...]
    auto_usable: bool
    gate_reasons: tuple[str, ...]
    random_seed: int


@dataclass(frozen=True)
class AefClassificationResult:
    output_path: Path
    report_path: Path
    output_sha256: str
    model_sha256: str
    macro_f1: float
    per_class_recall: dict[int, float]
    per_class_iou: dict[int, float]
    confidence_coverage: float
    area_hm2: dict[int, float]
    auto_usable: bool
    gate_reasons: tuple[str, ...]


def spatial_block_split(
    rows: Iterable[int], columns: Iterable[int], *, block_size: int,
    holdout_fraction: float, random_seed: int,
) -> SpatialSplit:
    import numpy as np
    if block_size <= 0 or not 0 < holdout_fraction < 1:
        raise ValueError("block_size must be positive and holdout_fraction must be between 0 and 1")
    row_values = np.asarray(tuple(rows), dtype="int64")
    column_values = np.asarray(tuple(columns), dtype="int64")
    if row_values.shape != column_values.shape or row_values.size < 2:
        raise ValueError("spatial split needs matching row/column coordinates")
    blocks_wide = int(column_values.max() // block_size) + 1
    block_ids = (row_values // block_size) * blocks_wide + (column_values // block_size)
    unique = np.unique(block_ids)
    if unique.size < 2:
        raise ValueError("spatial split needs at least two independent blocks")
    shuffled = unique.copy(); np.random.default_rng(random_seed).shuffle(shuffled)
    holdout_count = min(unique.size - 1, max(1, int(round(unique.size * holdout_fraction))))
    holdout_blocks = np.sort(shuffled[:holdout_count])
    holdout_mask = np.isin(block_ids, holdout_blocks)
    return SpatialSplit(
        train_indices=tuple(int(index) for index in np.flatnonzero(~holdout_mask)),
        holdout_indices=tuple(int(index) for index in np.flatnonzero(holdout_mask)),
        train_block_ids=tuple(int(value) for value in np.unique(block_ids[~holdout_mask])),
        holdout_block_ids=tuple(int(value) for value in holdout_blocks),
    )


def classification_quality_gate(
    macro_f1: float, per_class_recall: dict[int, float], modeled_green_area_hm2: float | None,
    official_green_area_hm2: float | None,
) -> ClassificationGate:
    reasons = []
    if macro_f1 < 0.70:
        reasons.append("macro_f1_below_0.70")
    if any(recall < 0.50 for recall in per_class_recall.values()):
        reasons.append("class_recall_below_0.50")
    difference = None
    if modeled_green_area_hm2 is not None and official_green_area_hm2 is not None:
        if official_green_area_hm2 <= 0:
            raise ValueError("official green area must be positive")
        difference = abs(modeled_green_area_hm2 - official_green_area_hm2) / official_green_area_hm2
        if difference > 0.20:
            reasons.append("official_area_difference_above_20_percent")
    return ClassificationGate(not reasons, tuple(reasons), difference)


def align_worldcover_labels(aef_path: Path, labels_path: Path, output_path: Path) -> Path:
    import numpy as np
    import rasterio
    from rasterio.warp import Resampling, reproject
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(aef_path) as feature_grid, rasterio.open(labels_path) as labels:
        if feature_grid.crs is None or labels.crs is None:
            raise ValueError("AEF and WorldCover require a CRS")
        destination = np.zeros((feature_grid.height, feature_grid.width), dtype="uint8")
        reproject(
            source=labels.read(1), destination=destination,
            src_transform=labels.transform, src_crs=labels.crs,
            dst_transform=feature_grid.transform, dst_crs=feature_grid.crs,
            src_nodata=labels.nodata or 0, dst_nodata=0, resampling=Resampling.nearest,
        )
        profile = feature_grid.profile.copy()
        profile.update(driver="GTiff", count=1, dtype="uint8", nodata=0, compress="DEFLATE")
        with rasterio.open(output_path, "w", **profile) as output:
            output.write(destination, 1)
    return output_path


def _per_class_iou(expected: Any, predicted: Any, classes: Iterable[int]) -> dict[int, float]:
    result = {}
    for code in classes:
        intersection = int(((expected == code) & (predicted == code)).sum())
        union = int(((expected == code) | (predicted == code)).sum())
        result[int(code)] = intersection / union if union else 0.0
    return result


def train_aef_classifier(
    aef_path: Path, labels_path: Path, boundary_path: Path, output_dir: Path,
    random_seed: int = 20240928,
) -> AefModelResult:
    import numpy as np
    import rasterio
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score, recall_score

    boundary = load_boundary_descriptor(Path(boundary_path))
    if boundary.get("status") not in {"approved", "unconfirmed_osm_demo_boundary"}:
        raise ValueError("classifier boundary status is not allowed")
    with rasterio.open(aef_path) as aef, rasterio.open(labels_path) as labels:
        if (aef.crs != labels.crs or aef.transform != labels.transform
                or aef.width != labels.width or aef.height != labels.height):
            raise ValueError("WorldCover labels must be aligned to the AEF grid")
        if aef.count != 64 or any(dtype != "int8" for dtype in aef.dtypes):
            raise ValueError("classifier requires 64 signed Int8 AEF bands")
        raw = aef.read()
        label_values = labels.read(1)
    valid = (label_values > 0) & (raw[0] != -128)
    rows, columns = np.nonzero(valid)
    if rows.size < 4:
        raise ValueError("classifier has too few valid labelled pixels")
    block_size = max(2, min(64, min(label_values.shape) // 3))
    split = spatial_block_split(rows, columns, block_size=block_size, holdout_fraction=0.25, random_seed=random_seed)
    labels_flat = label_values[rows, columns]
    train_positions = np.asarray(split.train_indices, dtype="int64")
    holdout_positions = np.asarray(split.holdout_indices, dtype="int64")
    rng = np.random.default_rng(random_seed)
    selected = []
    for code in np.unique(labels_flat[train_positions]):
        positions = train_positions[labels_flat[train_positions] == code]
        if positions.size > 5000:
            positions = rng.choice(positions, 5000, replace=False)
        selected.extend(int(value) for value in positions)
    selected = np.asarray(sorted(selected), dtype="int64")
    flat_features = raw[:, rows, columns].T
    parameters = {
        "n_estimators": 64, "max_depth": 16, "class_weight": "balanced_subsample",
        "random_state": random_seed, "block_size": block_size, "holdout_fraction": 0.25,
    }
    model = RandomForestClassifier(
        n_estimators=64, max_depth=16, class_weight="balanced_subsample",
        random_state=random_seed, n_jobs=-1,
    )
    model.fit(_features(flat_features[selected]), labels_flat[selected])
    expected = labels_flat[holdout_positions]
    predicted = model.predict(_features(flat_features[holdout_positions]))
    classes = tuple(int(code) for code in sorted(np.unique(labels_flat)))
    macro_f1 = float(f1_score(expected, predicted, labels=classes, average="macro", zero_division=0))
    recalls = recall_score(expected, predicted, labels=classes, average=None, zero_division=0)
    per_class_recall = {code: float(value) for code, value in zip(classes, recalls)}
    per_class_iou = _per_class_iou(expected, predicted, classes)
    gate = classification_quality_gate(macro_f1, per_class_recall, None, None)

    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "aef_worldcover_rf_2024.pkl"
    report_path = output_dir / "aef_worldcover_rf_2024.validation.json"
    with model_path.open("wb") as handle:
        pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)
    sample_hash = hashlib.sha256(selected.tobytes()).hexdigest()
    report = {
        "macro_f1": macro_f1, "per_class_recall": per_class_recall, "per_class_iou": per_class_iou,
        "classes": list(classes), "train_block_ids": list(split.train_block_ids),
        "holdout_block_ids": list(split.holdout_block_ids), "sample_index_sha256": sample_hash,
        "parameters": parameters, "parameters_sha256": _json_hash(parameters),
        "model_sha256": _sha256(model_path), "aef_sha256": _sha256(Path(aef_path)),
        "label_sha256": _sha256(Path(labels_path)), "auto_usable": gate.auto_usable,
        "gate_reasons": list(gate.reasons), "boundary_status": boundary["status"],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return AefModelResult(
        model_path=model_path, report_path=report_path, model_sha256=report["model_sha256"],
        sample_index_sha256=sample_hash, parameters_sha256=report["parameters_sha256"],
        aef_sha256=report["aef_sha256"], label_sha256=report["label_sha256"], macro_f1=macro_f1,
        per_class_recall=per_class_recall, per_class_iou=per_class_iou, classes=classes,
        train_block_ids=split.train_block_ids, holdout_block_ids=split.holdout_block_ids,
        auto_usable=gate.auto_usable, gate_reasons=gate.reasons, random_seed=random_seed,
    )


def classify_aef(
    model_result: AefModelResult, aef_path: Path, output_dir: Path,
    official_green_area_hm2: float | None = None,
) -> AefClassificationResult:
    import numpy as np
    import rasterio
    from rasterio.shutil import copy as raster_copy
    if _sha256(Path(aef_path)) != model_result.aef_sha256:
        raise ValueError("AEF classification input changed after model training")
    with model_result.model_path.open("rb") as handle:
        model = pickle.load(handle)
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "aef_ecosystem_class_2024.tif"
    report_path = output_dir / "aef_ecosystem_class_2024.report.json"
    counts = {code: 0 for code in model_result.classes}
    confident = valid_total = 0
    with tempfile.TemporaryDirectory(prefix="aef-classify-", dir=output_dir) as temporary:
        raw_output = Path(temporary) / "classes.tif"
        cog_output = Path(temporary) / output_path.name
        with rasterio.open(aef_path) as source:
            profile = source.profile.copy()
            profile.update(driver="GTiff", count=1, dtype="uint8", nodata=0, compress="DEFLATE")
            with rasterio.open(raw_output, "w", **profile) as destination:
                for _, window in source.block_windows(1):
                    raw = source.read(window=window)
                    valid = raw[0] != -128
                    classified = np.zeros(valid.shape, dtype="uint8")
                    if valid.any():
                        vectors = raw[:, valid].T
                        predictions = model.predict(_features(vectors)).astype("uint8")
                        probabilities = model.predict_proba(_features(vectors)).max(axis=1)
                        classified[valid] = predictions
                        valid_total += int(valid.sum()); confident += int((probabilities >= 0.60).sum())
                        unique, class_counts = np.unique(predictions, return_counts=True)
                        for code, count in zip(unique, class_counts): counts[int(code)] = counts.get(int(code), 0) + int(count)
                    destination.write(classified, 1, window=window)
            raster_copy(raw_output, cog_output, driver="COG", compress="DEFLATE", blocksize=512)
            pixel_area_hm2 = abs(source.transform.a * source.transform.e) / 10000.0
        os.replace(cog_output, output_path)
    area_hm2 = {code: round(count * pixel_area_hm2, 10) for code, count in sorted(counts.items()) if count}
    modeled_green = sum(area for code, area in area_hm2.items() if code in GREEN_CLASSES)
    gate = classification_quality_gate(
        model_result.macro_f1, model_result.per_class_recall, modeled_green, official_green_area_hm2,
    )
    auto_usable = model_result.auto_usable and gate.auto_usable
    reasons = tuple(dict.fromkeys((*model_result.gate_reasons, *gate.reasons)))
    report = {
        "output_sha256": _sha256(output_path), "model_sha256": model_result.model_sha256,
        "macro_f1": model_result.macro_f1, "per_class_recall": model_result.per_class_recall,
        "per_class_iou": model_result.per_class_iou,
        "confidence_coverage": confident / valid_total if valid_total else 0.0,
        "area_hm2": area_hm2, "modeled_green_area_hm2": modeled_green,
        "official_green_area_hm2": official_green_area_hm2,
        "official_area_difference_fraction": gate.official_area_difference_fraction,
        "auto_usable": auto_usable, "gate_reasons": list(reasons),
        "boundary_status": "unconfirmed_osm_demo_boundary",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return AefClassificationResult(
        output_path=output_path, report_path=report_path, output_sha256=report["output_sha256"],
        model_sha256=model_result.model_sha256, macro_f1=model_result.macro_f1,
        per_class_recall=model_result.per_class_recall, per_class_iou=model_result.per_class_iou,
        confidence_coverage=report["confidence_coverage"], area_hm2=area_hm2,
        auto_usable=auto_usable, gate_reasons=reasons,
    )


def build_area_observations(
    classification: AefClassificationResult, *, input_asset_ids: tuple[str, ...],
    region_code: str, year: int,
) -> list[ObservationRecord]:
    result = []
    for code, area in sorted(classification.area_hm2.items()):
        result.append(ObservationRecord.from_dict({
            "observation_id": f"aef-{year}-ecosystem-area-{code}", "metric": "ecosystem_area",
            "value": area, "unit": "hm2", "region_code": region_code, "year": year,
            "spatial_grain": f"worldcover_class_{code}", "method_id": "aef.random_forest.worldcover",
            "method_version": "v1", "input_asset_ids": list(input_asset_ids),
            "confidence": max(0.0, min(1.0, classification.macro_f1)),
            "uncertainty": {
                "class_code": code, "class_name": CLASS_NAMES.get(code, f"class_{code}"),
                "macro_f1": classification.macro_f1,
                "class_recall": classification.per_class_recall.get(code, 0.0),
                "class_iou": classification.per_class_iou.get(code, 0.0),
                "confidence_coverage": classification.confidence_coverage,
                "model_sha256": classification.model_sha256,
                "auto_usable": classification.auto_usable,
                "gate_reasons": list(classification.gate_reasons),
                "boundary_status": "unconfirmed_osm_demo_boundary",
            },
            "evidence_class": "model_estimate", "artifact_path": str(classification.output_path),
            "artifact_sha256": classification.output_sha256,
        }))
    return result


def register_area_observations(
    store: Any, classification: AefClassificationResult, *, input_asset_ids: tuple[str, ...],
    region_code: str, year: int,
) -> list[dict[str, Any]]:
    """Persist the classification's reusable area observations idempotently."""
    observations = build_area_observations(
        classification, input_asset_ids=input_asset_ids, region_code=region_code, year=year,
    )
    return [store.register_observation(observation) for observation in observations]

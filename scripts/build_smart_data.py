#!/usr/bin/env python3
"""Build versioned smart-data spatial artifacts outside the application runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gep.smart_data.aef_pipeline import build_aef_subset, plan_aef_subset
from gep.smart_data.aef_classifier import (
    align_worldcover_labels, build_area_observations, classify_aef, train_aef_classifier,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Haidian 2024 smart-data artifacts")
    subparsers = parser.add_subparsers(dest="stage", required=True)
    aef = subparsers.add_parser("aef")
    aef.add_argument("--data-root", required=True)
    aef.add_argument("--boundary", required=True)
    aef.add_argument("--year", type=int, default=2024)
    aef.add_argument("--index")
    aef.add_argument("--output-dir")
    classify = subparsers.add_parser("classify")
    classify.add_argument("--aef", required=True)
    classify.add_argument("--worldcover", required=True)
    classify.add_argument("--boundary", required=True)
    classify.add_argument("--output-dir", required=True)
    classify.add_argument("--official-green-area-hm2", type=float)
    classify.add_argument("--region-code", default="110108")
    classify.add_argument("--year", type=int, default=2024)
    classify.add_argument("--source-asset-id", action="append")
    args = parser.parse_args()
    if args.stage == "aef":
        root = Path(args.data_root)
        boundary = json.loads(Path(args.boundary).read_text(encoding="utf-8"))
        indexes = [Path(args.index)] if args.index else sorted(root.glob("**/aef_index.parquet"))
        if len(indexes) != 1:
            parser.error("exactly one AEF index is required")
        output = Path(args.output_dir) if args.output_dir else root / "03_features" / "alphaearth_2024"
        result = build_aef_subset(plan_aef_subset(indexes[0], boundary, args.year), output)
        payload = result.as_dict()
    else:
        output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
        aligned = align_worldcover_labels(Path(args.aef), Path(args.worldcover), output / "worldcover_aligned.tif")
        model = train_aef_classifier(Path(args.aef), aligned, Path(args.boundary), output / "model")
        result = classify_aef(model, Path(args.aef), output / "classification", args.official_green_area_hm2)
        source_ids = tuple(args.source_asset_id or ("alphaearth-2024-subset", "esa-worldcover-2021"))
        observations = build_area_observations(
            result, input_asset_ids=source_ids, region_code=args.region_code, year=args.year,
        )
        (output / "observations.json").write_text(json.dumps(
            [item.as_dict() for item in observations], ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        payload = {
            "auto_usable": result.auto_usable, "macro_f1": result.macro_f1,
            "area_hm2": result.area_hm2, "observation_count": len(observations),
            "classification_file": str(result.output_path), "report_file": str(result.report_path),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

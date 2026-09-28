#!/usr/bin/env python3
"""Build versioned smart-data spatial artifacts outside the application runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gep.smart_data.aef_pipeline import build_aef_subset, load_boundary_descriptor, plan_aef_subset
from gep.smart_data.aef_classifier import (
    align_worldcover_labels, build_area_observations, classify_aef, train_aef_classifier,
)
from gep.smart_data.assets import scan_known_assets
from gep.smart_data.observations import (
    build_cover_observations, build_modis_observations, build_nasa_power_observations,
    build_terrain_observations,
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
    observations = subparsers.add_parser("observations")
    observations.add_argument("--data-root", required=True)
    observations.add_argument("--output", required=True)
    observations.add_argument("--region-code", default="110108")
    observations.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()
    if args.stage == "aef":
        root = Path(args.data_root)
        boundary = load_boundary_descriptor(Path(args.boundary))
        indexes = [Path(args.index)] if args.index else sorted(root.glob("**/aef_index.parquet"))
        if len(indexes) != 1:
            parser.error("exactly one AEF index is required")
        output = Path(args.output_dir) if args.output_dir else root / "03_features" / "alphaearth_2024"
        result = build_aef_subset(plan_aef_subset(indexes[0], boundary, args.year), output)
        payload = result.as_dict()
    elif args.stage == "classify":
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
    else:
        root = Path(args.data_root)
        known = scan_known_assets(root)
        id_by_path = {asset.local_path: asset.asset_id for asset in known if asset.local_path}
        def asset_id(path: Path, fallback: str) -> str:
            try: relative = path.relative_to(root).as_posix()
            except ValueError: return fallback
            return id_by_path.get(relative, fallback)
        climate = root / "derived" / "nasa_power_monthly_point.csv"
        npp = root / "derived" / "npp_2024_kgC_m2.tif"; npp_qc = root / "derived" / "npp_2024_qc.tif"
        et = root / "derived" / "et_2024_mm.tif"; periods = root / "derived" / "et_2024_valid_period_count.tif"
        rasters = sorted(root.glob("raw/public/**/*.tif"))
        dem = [path for path in rasters if "dem" in path.name.lower()]
        covers = [path for path in rasters if "worldcover" in path.name.lower()]
        if len(covers) != 1:
            parser.error("exactly one WorldCover raster is required")
        built = [
            *build_nasa_power_observations(climate, asset_id=asset_id(climate, "nasa-power-monthly-point"),
                                           year=args.year, region_code=args.region_code),
            *build_modis_observations(npp, npp_qc, et, periods, asset_ids={
                "npp": asset_id(npp, "modis-npp-2024"), "npp_qc": asset_id(npp_qc, "modis-npp-qc-2024"),
                "et": asset_id(et, "modis-et-2024"), "et_periods": asset_id(periods, "modis-et-valid-periods-2024"),
            }, year=args.year, region_code=args.region_code),
            *build_terrain_observations(dem, asset_ids=[asset_id(path, f"dem-{number}") for number, path in enumerate(dem)],
                                        year=args.year, region_code=args.region_code),
            *build_cover_observations(covers[0], asset_id=asset_id(covers[0], "worldcover-2021"),
                                      year=args.year, region_code=args.region_code),
        ]
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps([item.as_dict() for item in built], ensure_ascii=False, indent=2), encoding="utf-8")
        payload = {"observation_count": len(built), "output": str(output)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build versioned smart-data spatial artifacts outside the application runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gep.smart_data.aef_pipeline import build_aef_subset, plan_aef_subset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Haidian 2024 smart-data artifacts")
    subparsers = parser.add_subparsers(dest="stage", required=True)
    aef = subparsers.add_parser("aef")
    aef.add_argument("--data-root", required=True)
    aef.add_argument("--boundary", required=True)
    aef.add_argument("--year", type=int, default=2024)
    aef.add_argument("--index")
    aef.add_argument("--output-dir")
    args = parser.parse_args()
    root = Path(args.data_root)
    boundary = json.loads(Path(args.boundary).read_text(encoding="utf-8"))
    indexes = [Path(args.index)] if args.index else sorted(root.glob("**/aef_index.parquet"))
    if len(indexes) != 1:
        parser.error("exactly one AEF index is required")
    output = Path(args.output_dir) if args.output_dir else root / "03_features" / "alphaearth_2024"
    result = build_aef_subset(plan_aef_subset(indexes[0], boundary, args.year), output)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

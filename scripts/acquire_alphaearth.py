#!/usr/bin/env python3
"""Select 2024 AlphaEarth assets from a locally frozen index; never downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gep.geo.alphaearth import select_2024_assets, validate_boundary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path, help="local JSON array converted from the frozen index")
    parser.add_argument("--boundary", required=True, type=Path, help="approved boundary descriptor JSON")
    parser.add_argument("--out", required=True, type=Path, help="new selected-assets JSON; existing files are refused")
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    boundary = validate_boundary(json.loads(args.boundary.read_text(encoding="utf-8")))
    if not isinstance(index, list):
        raise ValueError("index JSON must be an array of frozen index records")
    selected = select_2024_assets(index, boundary)
    payload = {"schema_version": 1, "boundary": boundary, "assets": selected, "downloaded": False}
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(f"selected={len(selected)} downloaded=false")


if __name__ == "__main__":
    main()

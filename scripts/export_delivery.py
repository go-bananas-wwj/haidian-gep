#!/usr/bin/env python3
"""Export a hashed, incomplete-task evidence package without a formal GEP claim."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gep.delivery import export_incomplete_task_delivery
from gep.task_service import GepStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    store = GepStore(args.database)
    try:
        manifest = export_incomplete_task_delivery(store, args.task, args.out)
    finally:
        store.close()
    print(f"delivery={args.out}")
    print("formal_gep_value=null")
    print(f"appendix_e_row_count={manifest['appendix_e_row_count']}")


if __name__ == "__main__":
    main()

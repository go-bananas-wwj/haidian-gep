#!/usr/bin/env python3
"""Standalone wrapper for the packaged knowledge-index command."""
from __future__ import annotations

import argparse
import json

from gep.agent.knowledge import index_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(description="Index approved GEP project knowledge")
    parser.add_argument("--database", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--pdf", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(index_knowledge(args.database, args.data_root, pdf_paths=args.pdf), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

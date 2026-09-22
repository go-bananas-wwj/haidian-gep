"""Read-only inspection of frozen GEP input-data releases."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .release import verify


VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class DataPackageCatalog:
    """Expose sealed data packages without granting them accounting admission."""

    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root is not None else None

    def versions(self) -> list[str]:
        if self.root is None:
            return []
        release_root = self.root / "05_release"
        if not release_root.is_dir() or release_root.is_symlink():
            return []
        return sorted(
            path.name for path in release_root.iterdir()
            if path.is_dir() and not path.is_symlink() and VERSION.fullmatch(path.name)
        )

    def summary(self, data_version: str) -> dict[str, Any]:
        if not VERSION.fullmatch(data_version):
            raise KeyError("data version not found")
        if self.root is None:
            raise KeyError("data version not found")
        package = self.root / "05_release" / data_version
        if not package.is_dir() or package.is_symlink():
            raise KeyError("data version not found")
        verification = verify(package)
        manifest = self._json(package / "manifest.json")
        quality = self._json(package / "quality_report.json")
        missing = self._missing_inputs(package / "missing_inputs.csv")
        alphaearth = self._alphaearth_candidates(self.root / "00_catalog" / "aef_2024_candidate_tiles.json")
        return {
            "data_version": data_version,
            "release_id": manifest.get("release_id"),
            "scope": manifest.get("scope"),
            "accounting_ready": bool(manifest.get("accounting_ready")),
            "full_gep_computed": bool(quality.get("full_gep_computed")),
            "release_verification": verification,
            "remaining": quality.get("remaining", []),
            "missing_input_count": len(missing),
            "missing_inputs": missing,
            "alphaearth_candidates": alphaearth,
        }

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _missing_inputs(path: Path) -> list[dict[str, str]]:
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {"item", "name", "status", "required_next_step"}
                if set(reader.fieldnames or ()) != required:
                    return []
                return [{key: str(row.get(key, "")) for key in sorted(required)} for row in reader]
        except OSError:
            return []

    @classmethod
    def _alphaearth_candidates(cls, path: Path) -> dict[str, Any]:
        document = cls._json(path)
        tiles = document.get("tiles")
        if not isinstance(tiles, list):
            return {"candidate_tile_count": 0, "boundary_statuses": [], "selection_states": [], "coverage_validated": False}
        statuses = sorted({str(tile.get("boundary_status", "")) for tile in tiles if isinstance(tile, dict)})
        selections = sorted({str(tile.get("selection", "")) for tile in tiles if isinstance(tile, dict)})
        return {
            "candidate_tile_count": len(tiles),
            "boundary_statuses": statuses,
            "selection_states": selections,
            "coverage_validated": False,
        }

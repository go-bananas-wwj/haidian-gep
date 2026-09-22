"""Truthful delivery envelopes for blocked, evidence-first GEP tasks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .task_service import GepStore


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_incomplete_task_delivery(store: GepStore, task_id: str, destination: str | Path) -> dict[str, Any]:
    """Export the current task evidence without claiming an unavailable formal GEP.

    The destination is created exactly once.  A later data/method revision must
    therefore receive a distinct delivery version instead of overwriting the
    evidence this package describes.
    """
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=False)
    graph = store.graph(task_id)
    appendix = store.appendix_e(task_id)
    events = store.events(task_id)
    files = {
        "graph.json": graph,
        "appendix_e.json": appendix,
        "events.json": {"task_id": task_id, "events": events},
    }
    for name, content in files.items():
        _write_json(output / name, content)
    (output / "README.md").write_text(
        "# Haidian GEP task evidence package\n\n"
        "Scope: incomplete evidence-first 2024 task delivery.\n\n"
        "This package does not publish a formal total GEP: `formal_gep_value` is null until all applicable "
        "indicators, evidence, methods, admissions, snapshot and run gates pass human review.\n",
        encoding="utf-8",
    )
    artifact_files = ("README.md", "graph.json", "appendix_e.json", "events.json")
    manifest = {
        "schema_version": 1,
        "scope": "incomplete_task_evidence",
        "task_id": task_id,
        "formal_gep_value": None,
        "appendix_e_row_count": appendix["row_count"],
        "artifact_sha256": {name: _sha256(output / name) for name in artifact_files},
    }
    _write_json(output / "manifest.json", manifest)
    checksum_files = (*artifact_files, "manifest.json")
    (output / "checksums.sha256").write_text(
        "".join(f"{_sha256(output / name)}  {name}\n" for name in checksum_files), encoding="utf-8"
    )
    return manifest

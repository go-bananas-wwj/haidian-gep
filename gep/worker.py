"""Persistent supplement worker independent of the HTTP request process."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .dify import DifyWorkflow
from .task_service import GepStore, SupplementWorkflow


class SupplementWorker:
    def __init__(self, database_path: str | Path, supplement_workflow: SupplementWorkflow | None = None):
        self.database_path = database_path
        self.supplement_workflow = supplement_workflow

    def run_once(self) -> dict[str, Any] | None:
        workflow = self.supplement_workflow if self.supplement_workflow is not None else DifyWorkflow.from_environment()
        store = GepStore(self.database_path, supplement_workflow=workflow)
        try:
            return store.process_next_supplement()
        finally:
            store.close()

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        while True:
            result = self.run_once()
            if result is None:
                time.sleep(poll_seconds)

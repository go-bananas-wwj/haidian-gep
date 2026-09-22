import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gep.delivery import export_incomplete_task_delivery
from gep.task_service import GepStore


class IncompleteTaskDeliveryTests(unittest.TestCase):
    """Break caught: a blocked task could be exported without its 22-item evidence or be mislabeled as a formal total."""

    def test_export_keeps_formal_gep_null_and_hashes_every_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GepStore(Path(directory) / "tasks.sqlite3")
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
                output = Path(directory) / "delivery"

                manifest = export_incomplete_task_delivery(store, task["task_id"], output)

                self.assertEqual(manifest["formal_gep_value"], None)
                self.assertEqual(manifest["appendix_e_row_count"], 22)
                appendix = json.loads((output / "appendix_e.json").read_text(encoding="utf-8"))
                self.assertEqual(appendix["formal_gep_value"], None)
                self.assertIn("incomplete", (output / "README.md").read_text(encoding="utf-8"))
                checksums = (output / "checksums.sha256").read_text(encoding="utf-8").splitlines()
                for line in checksums:
                    digest, filename = line.split("  ")
                    self.assertEqual(digest, hashlib.sha256((output / filename).read_bytes()).hexdigest())
            finally:
                store.close()

    def test_export_refuses_to_overwrite_an_existing_delivery_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GepStore(Path(directory) / "tasks.sqlite3")
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
                output = Path(directory) / "delivery"
                export_incomplete_task_delivery(store, task["task_id"], output)

                with self.assertRaises(FileExistsError):
                    export_incomplete_task_delivery(store, task["task_id"], output)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

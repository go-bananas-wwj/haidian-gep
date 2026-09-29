import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class KnowledgeIndexCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        (self.data / "04_docs").mkdir(parents=True)
        (self.data / "catalog").mkdir()
        (self.data / "04_docs" / "water-method.md").write_text(
            "# 水源涵养方法\n\n水源涵养量按降水、径流、蒸散发和面积计算。\n", encoding="utf-8",
        )
        (self.data / "catalog" / "field-dictionary.json").write_text(json.dumps({
            "ecosystem_area": "生态系统面积", "unit": "hm2",
        }, ensure_ascii=False), encoding="utf-8")
        (self.data / "catalog" / "gbt-standard.txt").write_text(
            "GB/T 46869-2025：水源涵养量按照水量平衡法核算。", encoding="utf-8",
        )
        self.broken_pdf = self.data / "04_docs" / "broken.pdf"
        self.broken_pdf.write_bytes(b"not a pdf")
        self.database = self.root / "tasks.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self):
        return subprocess.run(
            [sys.executable, "-m", "gep", "index-knowledge", "--database", str(self.database),
             "--data-root", str(self.data), "--pdf", str(self.broken_pdf)],
            cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True,
        )

    def test_indexes_allowed_documents_with_complete_provenance(self):
        """Break caught: imported knowledge could be searchable but not traceable to a file and hash."""
        completed = self.run_cli()
        result = json.loads(completed.stdout)
        self.assertEqual(result["indexed_count"], 3)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM knowledge_documents ORDER BY document_id").fetchall()
            self.assertEqual(len(rows), 3)
            for row in rows:
                payload = json.loads(row["payload_json"])
                for key in ("title", "publisher", "locator", "content_sha256", "license_or_access", "review_state"):
                    self.assertTrue(str(payload.get(key, "")).strip(), key)
                self.assertEqual(len(payload["content_sha256"]), 64)
        finally:
            connection.close()

    def test_repeated_index_is_idempotent(self):
        """Break caught: rebuilding the knowledge index could duplicate unchanged documents and chunks."""
        self.run_cli()
        second = json.loads(self.run_cli().stdout)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0], 3)
            self.assertEqual(second["indexed_count"], 0)
            self.assertEqual(second["unchanged_count"], 3)
        finally:
            connection.close()

    def test_unreadable_pdf_is_reported_without_rolling_back_other_documents(self):
        """Break caught: one corrupt PDF could prevent valid Markdown and JSON knowledge from being committed."""
        result = json.loads(self.run_cli().stdout)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["path"], str(self.broken_pdf))
        self.assertNotIn("not a pdf", result["errors"][0]["error"])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 3)
        finally:
            connection.close()

    def test_sensitive_catalog_document_is_not_written_to_sqlite(self):
        """Break caught: an API key in a catalog JSON could be copied into the searchable knowledge database."""
        sensitive = self.data / "catalog" / "private.json"
        sensitive.write_text(json.dumps({"api_key": "sensitive-value-that-must-not-be-stored"}), encoding="utf-8")
        result = json.loads(self.run_cli().stdout)
        self.assertEqual(result["indexed_count"], 3)
        self.assertEqual(result["error_count"], 2)
        connection = sqlite3.connect(self.database)
        try:
            payloads = "\n".join(row[0] for row in connection.execute("SELECT payload_json FROM knowledge_documents"))
            chunks = "\n".join(row[0] for row in connection.execute("SELECT text FROM knowledge_chunks"))
            self.assertNotIn("sensitive-value-that-must-not-be-stored", payloads + chunks)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()

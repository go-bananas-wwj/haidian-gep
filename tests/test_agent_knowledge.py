import tempfile
import unittest
from pathlib import Path


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "knowledge.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _document(**overrides):
        document = {
            "document_id": "doc-water-2024",
            "title": "海淀区水源涵养公开资料",
            "publisher": "示例政府部门",
            "source_url": "https://example.gov.cn/water",
            "license_or_access": "公开访问",
            "locator": "第 3 页，表 2",
            "region_code": "110108",
            "year_start": 2024,
            "year_end": 2024,
            "review_state": "verified",
            "content": "2024 年海淀区水源涵养核算使用降水量、蒸散量和区域面积。",
            "created_utc": "2026-09-29T00:00:00Z",
        }
        document.update(overrides)
        return document

    def test_search_returns_source_locator_and_hash(self):
        """Break caught: a knowledge hit could lose the provenance needed for audit."""
        from gep.agent.knowledge import KnowledgeBase

        knowledge = KnowledgeBase(self.database)
        try:
            saved = knowledge.add_document(self._document())
            hits = knowledge.search("水源涵养", limit=5)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["document_id"], "doc-water-2024")
            self.assertEqual(hits[0]["title"], "海淀区水源涵养公开资料")
            self.assertEqual(hits[0]["publisher"], "示例政府部门")
            self.assertEqual(hits[0]["locator"], "第 3 页，表 2")
            self.assertEqual(hits[0]["content_sha256"], saved["content_sha256"])
            self.assertIn("降水量", hits[0]["fragment"])
        finally:
            knowledge.close()

    def test_search_filters_region_year_and_review_state(self):
        """Break caught: an otherwise relevant result could be used for the wrong place, year, or review state."""
        from gep.agent.knowledge import KnowledgeBase

        knowledge = KnowledgeBase(self.database)
        try:
            knowledge.add_document(self._document())
            knowledge.add_document(self._document(
                document_id="doc-beijing-2023", region_code="110000", year_start=2023, year_end=2023,
                review_state="unreviewed", content="北京市水源涵养历史方法参数。",
            ))
            hits = knowledge.search(
                "水源涵养", filters={"region_code": "110108", "year": 2024, "review_state": "verified"}, limit=5,
            )
            self.assertEqual([hit["document_id"] for hit in hits], ["doc-water-2024"])
        finally:
            knowledge.close()

    def test_duplicate_document_is_idempotent(self):
        """Break caught: re-indexing an unchanged document could grow duplicate chunks."""
        from gep.agent.knowledge import KnowledgeBase

        knowledge = KnowledgeBase(self.database)
        try:
            first = knowledge.add_document(self._document())
            second = knowledge.add_document(self._document())
            self.assertEqual(first, second)
            count = knowledge.connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            knowledge.close()

    def test_fts5_unavailable_uses_bounded_like_fallback(self):
        """Break caught: a SQLite build without FTS5 could disable all knowledge retrieval."""
        from gep.agent.knowledge import KnowledgeBase

        knowledge = KnowledgeBase(self.database, force_fts=False, fallback_scan_limit=1)
        try:
            knowledge.add_document(self._document())
            knowledge.add_document(self._document(
                document_id="doc-carbon", content="海淀区碳汇核算方法。", title="碳汇资料",
            ))
            hits = knowledge.search("水源涵养", limit=5)
            self.assertEqual([hit["document_id"] for hit in hits], ["doc-water-2024"])
            outside_scan_window = knowledge.search("碳汇核算", limit=5)
            self.assertEqual(outside_scan_window, [])
            self.assertFalse(knowledge.fts_available)
        finally:
            knowledge.close()


if __name__ == "__main__":
    unittest.main()

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


class EvidenceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.release = self.root / "05_release" / "reference-2024-v0.1"
        self.release.mkdir(parents=True)
        source_hash = "a" * 64
        observation = {
            "region_code": "110108", "year": "2024", "metric": "玉米产量", "value": 2935.1,
            "unit": "吨", "source_type": "observed",
            "source_file": "01_raw/statistics/yearbook_2025_selected.pdf", "table_id": "5-11", "printed_page": "71",
            "status": "pending_review",
        }
        pending = {
            "region_code": "110108", "year": "2024", "metric": "水产品产量", "value": None,
            "unit": "吨", "source_type": "blank_unresolved",
            "source_file": "01_raw/statistics/yearbook_2025_selected.pdf", "table_id": "5-5", "printed_page": "67",
            "status": "pending_review", "note": "原表空白",
        }
        (self.release / "observations.json").write_text(json.dumps([observation], ensure_ascii=False), encoding="utf-8")
        (self.release / "pending.json").write_text(json.dumps([pending], ensure_ascii=False), encoding="utf-8")
        (self.release / "provenance.json").write_text(json.dumps({"source_extraction_sha256": source_hash}), encoding="utf-8")
        (self.release / "source_receipts.json").write_text(json.dumps({
            "sources": [{"source_id": "haidian_yearbook_2025", "path": "01_raw/statistics/haidian_yearbook_2025.zip"}],
        }), encoding="utf-8")
        with (self.release / "missing_inputs.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["indicator_id", "indicator_name", "status", "missing_inputs"])
            writer.writerow(["R4", "海岸防护", "pending_data_or_applicability_review", "海淀内陆不适用结论及审核"])
        manifest = {"files": {"observations.json": {"sha256": hashlib.sha256((self.release / "observations.json").read_bytes()).hexdigest()}}}
        (self.release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_matches_exact_region_year_and_known_node_metric(self):
        """Break caught: a work order could receive evidence for another place, year, or field."""
        from gep.evidence_catalog import EvidenceCatalog

        catalog = EvidenceCatalog(self.root)
        evidence = catalog.for_work_order({
            "data_version": "reference-2024-v0.1", "region_code": "110108", "year": 2024,
            "node_key": "P1.maize.quantity", "indicator_id": "P1", "node_kind": "input",
        })
        wrong_year = catalog.for_work_order({
            "data_version": "reference-2024-v0.1", "region_code": "110108", "year": 2023,
            "node_key": "P1.maize.quantity", "indicator_id": "P1", "node_kind": "input",
        })

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["source_id"], "haidian_yearbook_2025")
        self.assertEqual(evidence[0]["locator"], "表 5-11，印刷页 71")
        self.assertEqual(evidence[0]["source_sha256"], "a" * 64)
        self.assertEqual(wrong_year, [])

    def test_normalizes_pending_and_indicator_gap_records(self):
        """Break caught: unresolved blanks or applicability gaps could disappear before agent review."""
        from gep.evidence_catalog import EvidenceCatalog

        catalog = EvidenceCatalog(self.root)
        pending = catalog.for_work_order({
            "data_version": "reference-2024-v0.1", "region_code": "110108", "year": 2024,
            "node_key": "P4.harvest_quantity", "indicator_id": "P4", "node_kind": "input",
        })
        gap = catalog.for_work_order({
            "data_version": "reference-2024-v0.1", "region_code": "110108", "year": 2024,
            "node_key": "R4", "indicator_id": "R4", "node_kind": "indicator",
        })

        self.assertIsNone(pending[0]["value"])
        self.assertEqual(pending[0]["raw_status"], "blank_unresolved")
        self.assertEqual(gap[0]["source_type"], "gap_register")
        self.assertEqual(len(gap[0]["source_sha256"]), 64)

    def test_rejects_data_version_path_traversal(self):
        """Break caught: a task-controlled version could read files outside the admitted release root."""
        from gep.evidence_catalog import EvidenceCatalog

        with self.assertRaises(ValueError):
            EvidenceCatalog(self.root).for_work_order({
                "data_version": "../../private", "region_code": "110108", "year": 2024,
                "node_key": "R4", "indicator_id": "R4", "node_kind": "indicator",
            })


class EvidenceAwareWorkflowTests(unittest.TestCase):
    def test_exact_observed_record_builds_candidate_deterministically(self):
        """Break caught: model wording variability could discard an exact admitted observation."""
        from gep.supplement import EvidenceAwareWorkflow

        allowed = {
            "source_id": "yearbook", "source_type": "observed", "source_sha256": "a" * 64,
            "locator": "表 5-11，印刷页 71", "license_or_access": "review",
            "tool_run_id": "catalog-1", "extracted_fragment": "玉米产量 2935.1 吨",
            "metric": "玉米产量", "value": 2935.1, "unit": "吨", "raw_status": "observed",
        }

        class Catalog:
            def for_work_order(self, _work_order):
                return [allowed]

        class Provider:
            def run(self, _work_order):
                return {"outcome": "manual_required", "reason_code": "insufficient_evidence", "explanation": "请人工复核年鉴行。"}

        result = EvidenceAwareWorkflow(Provider(), Catalog()).run({"node_kind": "input", "node_label": "玉米产量"})

        self.assertEqual(result["outcome"], "candidate")
        self.assertEqual(result["value"], 2935.1)
        self.assertEqual(result["unit"], "吨")
        self.assertEqual(result["explanation"], "请人工复核年鉴行。")
        self.assertEqual(result["evidence"]["source_id"], "yearbook")

    def test_skips_provider_without_evidence(self):
        """Break caught: the system could spend model calls or invent values with no admitted source."""
        from gep.supplement import EvidenceAwareWorkflow

        class Catalog:
            def for_work_order(self, _work_order):
                return []

        class Provider:
            def run(self, _work_order):
                raise AssertionError("provider must not be called")

        result = EvidenceAwareWorkflow(Provider(), Catalog()).run({"node_key": "R1.precipitation"})
        self.assertEqual(result["outcome"], "manual_required")
        self.assertEqual(result["reason_code"], "source_missing")

    def test_rejects_a_candidate_that_cites_unavailable_evidence(self):
        """Break caught: a malicious model could cite a source not supplied to that work order."""
        from gep.supplement import EvidenceAwareWorkflow

        allowed = {"source_id": "allowed", "source_sha256": "a" * 64}

        class Catalog:
            def for_work_order(self, _work_order):
                return [allowed]

        class Provider:
            def run(self, _work_order):
                return {
                    "outcome": "candidate", "value": 1, "unit": "t", "explanation": "x",
                    "evidence": {"source_id": "unknown", "source_sha256": "b" * 64},
                }

        with self.assertRaises(ValueError):
            EvidenceAwareWorkflow(Provider(), Catalog()).run({"node_key": "P1.maize.quantity"})


if __name__ == "__main__":
    unittest.main()

import math
import tempfile
import unittest
from pathlib import Path

from gep.admission import admit, write_admission_catalogs, write_manifest
from gep.catalog import build_reference_admission


ALL_INDICATORS = {
    **{f"P{i}": "applicable" for i in range(1, 8)},
    **{f"R{i}": "applicable" for i in range(1, 13)},
    **{f"C{i}": "applicable" for i in range(1, 4)},
}


def record(node_id="P1.maize.quantity", **changes):
    result = {
        "node_id": node_id,
        "indicator_id": node_id.split(".")[0],
        "region_code": "110108",
        "year": 2024,
        "source_id": "yearbook-5-11",
        "value": 2935.1,
        "unit": "t/a",
        "status": "approved",
        "sha256": "a" * 64,
        "product_id": "maize-2024",
    }
    result.update(changes)
    return result


class AdmissionTests(unittest.TestCase):
    def admit_one(self, rows, required_nodes=("P1.maize.quantity",)):
        return admit(rows, ALL_INDICATORS, {"P1": required_nodes}, [])

    def test_wrong_year_blocks_the_record_node(self):
        result = self.admit_one([record(year=2023)])

        self.assertFalse(result.accepted)
        self.assertEqual([block.node_id for block in result.blockers], ["P1.maize.quantity"])
        self.assertEqual(result.blockers[0].code, "outside_scope")

    def test_blank_value_blocks_the_record_node(self):
        result = self.admit_one([record(value="")])

        self.assertFalse(result.accepted)
        self.assertEqual(result.blockers[0].node_id, "P1.maize.quantity")
        self.assertEqual(result.blockers[0].code, "missing_value")

    def test_nan_blocks_the_record_node(self):
        result = self.admit_one([record(value=math.nan)])

        self.assertFalse(result.accepted)
        self.assertEqual(result.blockers[0].node_id, "P1.maize.quantity")
        self.assertEqual(result.blockers[0].code, "non_finite_value")

    def test_unreviewed_source_blocks_the_record_node(self):
        result = self.admit_one([record(status="pending_review")])

        self.assertFalse(result.accepted)
        self.assertEqual(result.blockers[0].node_id, "P1.maize.quantity")
        self.assertEqual(result.blockers[0].code, "source_not_approved")

    def test_duplicate_product_ownership_blocks_both_nodes(self):
        result = self.admit_one([
            record("P1.maize.quantity"),
            record("P7.maize.quantity", indicator_id="P7"),
        ])

        self.assertFalse(result.accepted)
        self.assertEqual(
            [(block.node_id, block.code) for block in result.blockers],
            [("P1.maize.quantity", "duplicate_product_ownership"),
             ("P7.maize.quantity", "duplicate_product_ownership")],
        )

    def test_missing_price_and_cost_return_stable_missing_node_ids(self):
        result = self.admit_one(
            [record()],
            required_nodes=("P1.maize.quantity", "P1.maize.price", "P1.maize.cost"),
        )

        self.assertFalse(result.accepted)
        self.assertEqual(
            [(block.node_id, block.code) for block in result.blockers],
            [("P1.maize.cost", "missing_required_field"),
             ("P1.maize.price", "missing_required_field")],
        )

    def test_admission_accepts_the_typed_cultural_service_inputs_required_by_method_cards(self):
        """Break caught: valid 2024 cultural inputs could be rejected before a formula sees them."""
        cultural = [
            record("C1.visitor_count", indicator_id="C1", value=1000, unit="person-visits/a", product_id=""),
            record("C1.origin", indicator_id="C1", value="stratified_2024_survey", unit="metadata", product_id=""),
            record("C1.travel_time", indicator_id="C1", value=4, unit="h/visit", product_id=""),
            record("C1.hourly_wage", indicator_id="C1", value=100, unit="元/h", product_id=""),
            record("C1.travel_cost", indicator_id="C1", value=300, unit="元/visit", product_id=""),
            record("C1.attribution", indicator_id="C1", value=0.5, unit="fraction", product_id=""),
            record("C2.visitor_count", indicator_id="C2", value=1000, unit="person-visits/a", product_id=""),
            record("C2.stay_duration", indicator_id="C2", value=2, unit="h/visit", product_id=""),
            record("C2.hourly_wage", indicator_id="C2", value=50, unit="元/h", product_id=""),
            record("C2.deduplication_choice", indicator_id="C2", value="exclusive_to_c2", unit="choice", product_id=""),
            record("C3.hotel_room_nights", indicator_id="C3", value=100, unit="room-nights/a", product_id=""),
            record("C3.hotel_room_price", indicator_id="C3", value=500, unit="元/room-night", product_id=""),
            record("C3.hotel_landscape_premium", indicator_id="C3", value=0.1, unit="fraction", product_id=""),
            record("C3.housing_service_area", indicator_id="C3", value=1000, unit="m2", product_id=""),
            record("C3.housing_service_price", indicator_id="C3", value=20, unit="元/(m2*a)", product_id=""),
            record("C3.housing_landscape_premium", indicator_id="C3", value=0.05, unit="fraction", product_id=""),
        ]
        states = {indicator: "not_applicable" for indicator in ALL_INDICATORS}
        states.update({"C1": "applicable", "C2": "applicable", "C3": "applicable"})
        required = {
            "C1": tuple(row["node_id"] for row in cultural if row["indicator_id"] == "C1"),
            "C2": tuple(row["node_id"] for row in cultural if row["indicator_id"] == "C2"),
            "C3": tuple(row["node_id"] for row in cultural if row["indicator_id"] == "C3"),
        }

        result = admit(cultural, states, required, [])

        self.assertTrue(result.accepted)
        self.assertEqual(result.blockers, ())

    def test_reference_catalog_imports_observations_as_unreviewed_without_rewriting_source(self):
        fields = "region_code,year,table_id,printed_page,pdf_page,source_file,metric,value,unit,status,notes\n"
        rows = (
            "110108,2024,5-11,71,71,01_raw/a.pdf,玉米产量,2935.1,吨,observed,\n"
            "110108,2024,5-5,67,67,01_raw/a.pdf,水产品,,吨,blank_unresolved,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "yearbook.csv")
            source.write_text(fields + rows, encoding="utf-8")

            result = build_reference_admission(source)

            self.assertFalse(result.accepted)
            self.assertEqual(len(result.manifest["records"]), 2)
            self.assertEqual(result.manifest["records"][0]["status"], "pending_review")
            self.assertTrue(result.manifest_sha256)
            output = Path(directory, "manifest.json")
            write_manifest(output, result)
            self.assertEqual(source.read_text(encoding="utf-8"), fields + rows)
            with self.assertRaises(FileExistsError):
                write_manifest(output, result)

    def test_catalog_writer_creates_a_versioned_22_indicator_blocked_package(self):
        result = self.admit_one([record()], required_nodes=("P1.maize.quantity", "P1.maize.price"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "admission-v0.1")

            written = write_admission_catalogs(output, result)

            self.assertEqual(set(written), {
                "indicator_catalog.csv", "field_matrix.csv", "annual_rules.csv", "adjustments.csv", "data_manifest.csv",
            })
            indicator_rows = written["indicator_catalog.csv"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(indicator_rows), 23)
            self.assertIn("P1,农产品,material,applicable,blocked", indicator_rows)
            self.assertIn(result.manifest_sha256, written["data_manifest.csv"].read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_admission_catalogs(output, result)


if __name__ == "__main__":
    unittest.main()

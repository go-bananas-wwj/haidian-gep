import unittest

from gep.formulas.adjustments import Adjustment, apply_adjustments


class AdjustmentLedgerTests(unittest.TestCase):
    """Break caught: an external or overlap adjustment could be omitted or deducted twice."""

    def test_325_wan_example_deducts_only_total_level_external_and_overlap_entries(self):
        result = apply_adjustments(
            {"material": 1_000_000, "regulating": 2_000_000, "cultural": 500_000},
            [
                Adjustment("outside-1", "outside", 200_000, "total", "external source share"),
                Adjustment("overlap-1", "overlap", 50_000, "total", "unbooked overlap"),
            ],
        )

        self.assertEqual(result.gross_value_yuan, 3_500_000)
        self.assertEqual(result.total_adjustment_yuan, 250_000)
        self.assertEqual(result.gep_value_yuan, 3_250_000)
        self.assertEqual(result.gep_value_wan_yuan, 325)
        self.assertEqual(result.applied_adjustment_ids, ("outside-1", "overlap-1"))

    def test_item_level_adjustment_is_audit_visible_but_not_deducted_again(self):
        result = apply_adjustments(
            {"material": 800_000, "regulating": 2_000_000, "cultural": 500_000},
            [Adjustment("outside-already-net", "outside", 200_000, "item", "already netted in P1")],
        )

        self.assertEqual(result.gep_value_yuan, 3_300_000)
        self.assertEqual(result.total_adjustment_yuan, 0)
        self.assertEqual(result.already_booked_adjustment_ids, ("outside-already-net",))

    def test_duplicate_adjustment_identity_is_rejected_before_any_total_is_reported(self):
        with self.assertRaises(ValueError):
            apply_adjustments(
                {"material": 1, "regulating": 2, "cultural": 3},
                [
                    Adjustment("dup", "outside", 1, "total", "one"),
                    Adjustment("dup", "overlap", 1, "total", "two"),
                ],
            )


if __name__ == "__main__":
    unittest.main()

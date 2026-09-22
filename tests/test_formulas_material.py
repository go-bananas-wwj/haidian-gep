import unittest

from gep.formulas.material import calculate_ecological_energy, calculate_freshwater_supply, calculate_residual_value
from gep.formulas.registry import calculate_indicator


class MaterialFormulaTests(unittest.TestCase):
    """Break caught: a material-product result could erase costs or mask a negative residual as zero."""

    def test_residual_value_uses_a2_output_less_non_ecological_inputs(self):
        result = calculate_residual_value("P1", {
            "quantity": {"value": 10_000, "unit": "t/a"},
            "producer_price": {"value": 100, "unit": "元/t"},
            "intermediate_cost": {"value": 300_000, "unit": "元/a"},
            "labor": {"value": 200_000, "unit": "元/a"},
            "depreciation": {"value": 80_000, "unit": "元/a"},
            "tax_net": {"value": 20_000, "unit": "元/a"},
            "capital_return": {"value": 50_000, "unit": "元/a"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 10_000)
        self.assertEqual(result.physical_unit, "t/a")
        self.assertEqual(result.output_value_yuan, 1_000_000)
        self.assertEqual(result.value_yuan, 350_000)
        self.assertEqual(result.value_wan_yuan, 35.0)
        self.assertEqual(result.standard_clause, "A.2")

    def test_residual_value_keeps_a_negative_result_for_review(self):
        result = calculate_residual_value("P2", {
            "harvest_quantity": {"value": 1, "unit": "m3/a"},
            "producer_price": {"value": 100, "unit": "元/m3"},
            "intermediate_cost": {"value": 101, "unit": "元/a"},
            "labor": {"value": 0, "unit": "元/a"},
            "depreciation": {"value": 0, "unit": "元/a"},
            "tax_net": {"value": 0, "unit": "元/a"},
            "capital_return": {"value": 0, "unit": "元/a"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.value_yuan, -1)
        self.assertEqual(result.review_status, "requires_human_review")

    def test_residual_value_blocks_missing_or_wrong_units_without_a_value(self):
        result = calculate_residual_value("P1", {
            "quantity": {"value": 1, "unit": "t/a"},
            "producer_price": {"value": 1, "unit": "元/kg"},
            "intermediate_cost": {"value": 0, "unit": "元/a"},
            "labor": {"value": 0, "unit": "元/a"},
            "depreciation": {"value": 0, "unit": "元/a"},
            "tax_net": {"value": 0, "unit": "元/a"},
        })

        self.assertFalse(result.calculated)
        self.assertIsNone(result.value_yuan)
        self.assertEqual(result.blocking_fields, ("capital_return", "producer_price"))

    def test_registry_calculates_p3_p4_and_p7_from_actual_quantity_price_and_complete_production_cost(self):
        """Break caught: applicable products could remain unimplemented or use a value without their cost deduction."""
        cases = {
            "P3": {
                "eligible_quantity": {"value": 10, "unit": "t/a"},
                "producer_price": {"value": 100, "unit": "元/t"},
                "production_cost": {"value": 250, "unit": "元/a"},
            },
            "P4": {
            "harvest_quantity": {"value": 60, "unit": "t/a"},
                "producer_price": {"value": 100, "unit": "元/t"},
                "production_cost": {"value": 1_000, "unit": "元/a"},
            },
            "P7": {
                "deliverable_quantity": {"value": 100, "unit": "盆/a"},
                "producer_price": {"value": 50, "unit": "元/盆"},
                "production_cost": {"value": 1_000, "unit": "元/a"},
            },
        }

        results = {indicator: calculate_indicator(indicator, inputs) for indicator, inputs in cases.items()}

        self.assertEqual(results["P3"].value_yuan, 750)
        self.assertEqual(results["P4"].value_yuan, 5_000)
        self.assertEqual(results["P7"].value_yuan, 4_000)
        self.assertTrue(all(result.calculated for result in results.values()))
        self.assertTrue(all(result.standard_clause == "A.2" for result in results.values()))

    def test_p5_deducts_outside_and_recycled_water_from_locally_used_water(self):
        result = calculate_freshwater_supply({
            "local_used_water": {"value": 1000, "unit": "m3/a"},
            "outside_water": {"value": 300, "unit": "m3/a"},
            "recycled_water": {"value": 200, "unit": "m3/a"},
            "valuation_parameter": {"value": 2, "unit": "元/m3"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 500)
        self.assertEqual(result.physical_unit, "m3/a")
        self.assertEqual(result.value_yuan, 1_000)
        self.assertEqual(result.standard_clause, "A.1/A.2")

    def test_p6_counts_only_energy_that_is_both_locally_produced_and_actually_used(self):
        result = calculate_ecological_energy({
            "actual_energy_output": {"value": 1000, "unit": "kWh/a"},
            "actual_use": {"value": 600, "unit": "kWh/a"},
            "producer_price": {"value": 1, "unit": "元/kWh"},
            "production_cost": {"value": 100, "unit": "元/a"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 600)
        self.assertEqual(result.physical_unit, "kWh/a")
        self.assertEqual(result.output_value_yuan, 600)
        self.assertEqual(result.value_yuan, 500)
        self.assertEqual(result.standard_clause, "A.1")

    def test_registry_dispatches_p5_and_p6_instead_of_a_pending_placeholder(self):
        freshwater = calculate_indicator("P5", {
            "local_used_water": {"value": 1, "unit": "m3/a"},
            "outside_water": {"value": 0, "unit": "m3/a"},
            "recycled_water": {"value": 0, "unit": "m3/a"},
            "valuation_parameter": {"value": 1, "unit": "元/m3"},
        })
        energy = calculate_indicator("P6", {
            "actual_energy_output": {"value": 1, "unit": "kWh/a"},
            "actual_use": {"value": 1, "unit": "kWh/a"},
            "producer_price": {"value": 1, "unit": "元/kWh"},
            "production_cost": {"value": 0, "unit": "元/a"},
        })

        self.assertEqual(freshwater.value_yuan, 1)
        self.assertEqual(energy.value_yuan, 1)


if __name__ == "__main__":
    unittest.main()

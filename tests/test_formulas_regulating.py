import unittest

from gep.formulas.regulating import calculate_carbon_from_npp, calculate_oxygen_from_carbon, calculate_water_balance
from gep.formulas.registry import calculate_indicator


class RegulatingFormulaTests(unittest.TestCase):
    """Break caught: carbon conversion or price changes could alter an untraceable or dimensionally invalid value."""

    def test_r6_npp_alpha_path_matches_the_documented_hand_calculation(self):
        result = calculate_carbon_from_npp({
            "npp_or_nep": {"value": 100, "unit": "gC/m2/a"},
            "respiration_or_conversion": {"value": 0.3599, "unit": "fraction"},
            "ecosystem_area": {"value": 1, "unit": "hm2"},
            "carbon_price": {"value": 60, "unit": "元/tCO2"},
        })

        self.assertTrue(result.calculated)
        self.assertAlmostEqual(result.physical_value, 1.3196333333333332)
        self.assertEqual(result.physical_unit, "tCO2/a")
        self.assertAlmostEqual(result.value_yuan, 79.178)
        self.assertAlmostEqual(result.value_wan_yuan, 0.0079178)
        self.assertEqual(result.standard_clause, "A.34--A.54")

    def test_r6_blocks_missing_or_wrongly_dimensioned_inputs_without_a_value(self):
        result = calculate_carbon_from_npp({
            "npp_or_nep": {"value": 100, "unit": "tC/a"},
            "respiration_or_conversion": {"value": 0.3599, "unit": "fraction"},
            "ecosystem_area": {"value": 1, "unit": "hm2"},
        })

        self.assertFalse(result.calculated)
        self.assertIsNone(result.value_yuan)
        self.assertEqual(result.blocking_fields, ("carbon_price", "npp_or_nep"))

    def test_registry_dispatches_r6_without_using_a_generic_pending_method(self):
        result = calculate_indicator("R6", {
            "npp_or_nep": {"value": 100, "unit": "gC/m2/a"},
            "respiration_or_conversion": {"value": 0.3599, "unit": "fraction"},
            "ecosystem_area": {"value": 1, "unit": "hm2"},
            "carbon_price": {"value": 60, "unit": "元/tCO2"},
        })

        self.assertTrue(result.calculated)
        self.assertNotIn("method_implementation_pending", result.blocking_fields)

    def test_r7_uses_only_a_compatible_co2_carbon_rate_and_oxygen_price(self):
        result = calculate_oxygen_from_carbon({
            "carbon_sequestration_rate": {"value": 1.3196333333333332, "unit": "tCO2/a"},
            "oxygen_price": {"value": 80, "unit": "元/tO2"},
        })

        self.assertTrue(result.calculated)
        self.assertAlmostEqual(result.physical_value, 0.9597333333333332)
        self.assertEqual(result.physical_unit, "tO2/a")
        self.assertAlmostEqual(result.value_yuan, 76.77866666666667)
        self.assertEqual(result.standard_clause, "A.55--A.56")

    def test_r7_blocks_an_incompatible_carbon_unit_without_creating_a_value(self):
        result = calculate_oxygen_from_carbon({
            "carbon_sequestration_rate": {"value": 1, "unit": "tC/a"},
            "oxygen_price": {"value": 80, "unit": "元/tO2"},
        })

        self.assertFalse(result.calculated)
        self.assertIsNone(result.value_yuan)
        self.assertEqual(result.blocking_fields, ("carbon_sequestration_rate",))

    def test_registry_dispatches_r7_to_the_compatible_carbon_path(self):
        result = calculate_indicator("R7", {
            "carbon_sequestration_rate": {"value": 1.3196333333333332, "unit": "tCO2/a"},
            "oxygen_price": {"value": 80, "unit": "元/tO2"},
        })

        self.assertTrue(result.calculated)
        self.assertAlmostEqual(result.value_yuan, 76.77866666666667)

    def test_r1_water_balance_uses_precipitation_minus_surface_runoff_minus_actual_et(self):
        result = calculate_water_balance({
            "precipitation": {"value": 1000, "unit": "mm/a"},
            "surface_runoff": {"value": 200, "unit": "mm/a"},
            "actual_et": {"value": 300, "unit": "mm/a"},
            "ecosystem_area": {"value": 10_000, "unit": "m2"},
            "valuation_parameter": {"value": 1, "unit": "元/m3"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 5000)
        self.assertEqual(result.physical_unit, "m3/a")
        self.assertEqual(result.value_yuan, 5000)
        self.assertEqual(result.standard_clause, "A.4--A.6")

    def test_r1_preserves_a_negative_water_balance_for_review(self):
        result = calculate_water_balance({
            "precipitation": {"value": 100, "unit": "mm/a"},
            "surface_runoff": {"value": 200, "unit": "mm/a"},
            "actual_et": {"value": 300, "unit": "mm/a"},
            "ecosystem_area": {"value": 10_000, "unit": "m2"},
            "valuation_parameter": {"value": 1, "unit": "元/m3"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, -4000)
        self.assertEqual(result.review_status, "requires_human_review")

    def test_registry_dispatches_r1_to_the_annual_water_balance_path(self):
        result = calculate_indicator("R1", {
            "precipitation": {"value": 1000, "unit": "mm/a"},
            "surface_runoff": {"value": 200, "unit": "mm/a"},
            "actual_et": {"value": 300, "unit": "mm/a"},
            "ecosystem_area": {"value": 10_000, "unit": "m2"},
            "valuation_parameter": {"value": 1, "unit": "元/m3"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.value_yuan, 5000)


if __name__ == "__main__":
    unittest.main()

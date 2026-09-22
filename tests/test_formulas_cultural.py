import unittest

from gep.formulas.cultural import (
    calculate_landscape_premium,
    calculate_recreation_time,
    calculate_travel_cost,
)
from gep.formulas.registry import calculate_indicator


class CulturalFormulaTests(unittest.TestCase):
    """Break caught: cultural-use values could omit attribution or count an ineligible overlap."""

    def test_c1_travel_cost_uses_visitor_count_time_cost_and_attribution(self):
        result = calculate_travel_cost({
            "visitor_count": {"value": 1_000, "unit": "person-visits/a"},
            "origin": {"value": "stratified_2024_survey", "unit": "metadata"},
            "travel_time": {"value": 4, "unit": "h/visit"},
            "hourly_wage": {"value": 100, "unit": "元/h"},
            "travel_cost": {"value": 300, "unit": "元/visit"},
            "attribution": {"value": 0.5, "unit": "fraction"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 1_000)
        self.assertEqual(result.physical_unit, "person-visits/a")
        self.assertEqual(result.value_yuan, 350_000)
        self.assertEqual(result.value_wan_yuan, 35)
        self.assertEqual(result.standard_clause, "A.72--A.75")

    def test_c2_recreation_time_requires_an_explicit_c1_exclusion_choice(self):
        complete = {
            "visitor_count": {"value": 1_000, "unit": "person-visits/a"},
            "stay_duration": {"value": 2, "unit": "h/visit"},
            "hourly_wage": {"value": 50, "unit": "元/h"},
            "deduplication_choice": {"value": "exclusive_to_c2", "unit": "choice"},
        }

        result = calculate_recreation_time(complete)

        self.assertTrue(result.calculated)
        self.assertEqual(result.physical_value, 2_000)
        self.assertEqual(result.physical_unit, "person-hours/a")
        self.assertEqual(result.value_yuan, 100_000)

        blocked = calculate_recreation_time({**complete, "deduplication_choice": {"value": "unresolved", "unit": "choice"}})
        self.assertFalse(blocked.calculated)
        self.assertEqual(blocked.blocking_fields, ("deduplication_choice",))
        self.assertIsNone(blocked.value_yuan)

    def test_c3_landscape_premium_prices_annual_service_flows_not_asset_sales(self):
        result = calculate_landscape_premium({
            "hotel_room_nights": {"value": 100, "unit": "room-nights/a"},
            "hotel_room_price": {"value": 500, "unit": "元/room-night"},
            "hotel_landscape_premium": {"value": 0.1, "unit": "fraction"},
            "housing_service_area": {"value": 1_000, "unit": "m2"},
            "housing_service_price": {"value": 20, "unit": "元/(m2*a)"},
            "housing_landscape_premium": {"value": 0.05, "unit": "fraction"},
        })

        self.assertTrue(result.calculated)
        self.assertIsNone(result.physical_value)
        self.assertEqual(result.value_yuan, 6_000)
        self.assertEqual(result.value_wan_yuan, 0.6)
        self.assertEqual(result.standard_clause, "A.78--A.82")

    def test_registry_dispatches_cultural_method_instead_of_a_pending_placeholder(self):
        result = calculate_indicator("C1", {
            "visitor_count": {"value": 1, "unit": "person-visits/a"},
            "origin": {"value": "stratified_2024_survey", "unit": "metadata"},
            "travel_time": {"value": 1, "unit": "h/visit"},
            "hourly_wage": {"value": 1, "unit": "元/h"},
            "travel_cost": {"value": 1, "unit": "元/visit"},
            "attribution": {"value": 1, "unit": "fraction"},
        })

        self.assertTrue(result.calculated)
        self.assertEqual(result.value_yuan, 2)


if __name__ == "__main__":
    unittest.main()

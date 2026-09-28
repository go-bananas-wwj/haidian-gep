import unittest

from gep.smart_data import CalculationPlan, ObservationRecord
from gep.smart_data.calculators import (
    calculate_carbon_demo, calculate_local_climate_demo, calculate_oxygen_demo,
    calculate_soil_factors_demo, calculate_water_balance_demo,
)
from gep.smart_data.methods import SMART_METHODS
from gep.smart_data.planning import execute_plan, resolve_plan


def observation(metric, value, unit, *, suffix="1", year=2024, region="110108", confidence=.8):
    return ObservationRecord.from_dict({
        "observation_id": f"{metric}-{suffix}", "metric": metric, "value": value, "unit": unit,
        "region_code": region, "year": year, "spatial_grain": "district", "method_id": "fixture",
        "method_version": "v1", "input_asset_ids": [f"asset-{metric}-{suffix}"], "confidence": confidence,
        "uncertainty": {}, "evidence_class": "model_estimate",
    })


class SmartDataPlanningTests(unittest.TestCase):
    def test_registry_and_calculators_match_hand_calculations(self):
        self.assertEqual(set(SMART_METHODS), {
            "R1.water_balance.demo.v1", "R2.spatial_factors.demo.v1", "R4.inland_applicability.demo.v1",
            "R6.npp_conversion.demo.v1", "R7.oxygen_link.demo.v1", "R10.local_climate.demo.v1",
        })
        self.assertEqual(calculate_water_balance_demo(1000, 200, 300, 1), {"value": 5000.0, "unit": "m3/a"})
        self.assertAlmostEqual(calculate_carbon_demo(.1, .3599, 1)["value"], 1.3196333333333332)
        self.assertAlmostEqual(calculate_oxygen_demo(1.3196333333333332)["value"], .9597333333333332)
        self.assertEqual(calculate_soil_factors_demo(10, 2, 3, .4, 5), {"value": 180.0, "unit": "t/a"})
        self.assertEqual(calculate_local_climate_demo(10, 1, 2, .5), {"value": 68000.0, "unit": "kWh/a"})

    def r1_observations(self):
        return [
            observation("precipitation", 1000, "mm/a"), observation("surface_runoff", 200, "mm/a"),
            observation("actual_et", 300, "mm/a"), observation("ecosystem_area", 1, "hm2"),
        ]

    def work_order(self, **changes):
        payload = {"task_id": "task-1", "node_id": "node-r1", "node_key": "R1",
                   "indicator_id": "R1", "target_metric": "water_conservation",
                   "year": 2024, "region_code": "110108", "node_version": 1}
        payload.update(changes); return payload

    def test_resolver_builds_a_deterministic_plan_and_provider_failure_keeps_it(self):
        class FailingProvider:
            def run(self, _payload):
                raise RuntimeError("offline")

        plan = resolve_plan(self.work_order(), self.r1_observations(), provider=FailingProvider())

        self.assertEqual(plan.method_id, "R1.water_balance.demo.v1")
        self.assertEqual(plan.input_bindings, {
            "actual_et": "actual_et-1", "ecosystem_area": "ecosystem_area-1",
            "precipitation": "precipitation-1", "surface_runoff": "surface_runoff-1",
        })
        self.assertEqual(plan.planner, "deterministic")
        self.assertIn("版本化方法", plan.explanation)
        result = execute_plan(plan, self.r1_observations())
        self.assertEqual(result.result, {"value": 5000.0, "unit": "m3/a"})
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(result.input_manifest_sha256), 64)
        self.assertEqual(len(result.result_sha256), 64)

    def test_resolver_rejects_wrong_year_region_or_unit_and_missing_inputs(self):
        self.assertIsNone(resolve_plan(self.work_order(), self.r1_observations()[:-1]))
        wrong_year = [*self.r1_observations()[:-1], observation("ecosystem_area", 1, "hm2", year=2025)]
        wrong_region = [*self.r1_observations()[:-1], observation("ecosystem_area", 1, "hm2", region="110105")]
        wrong_unit = [*self.r1_observations()[:-1], observation("ecosystem_area", 1, "m2")]
        self.assertIsNone(resolve_plan(self.work_order(), wrong_year))
        self.assertIsNone(resolve_plan(self.work_order(), wrong_region))
        self.assertIsNone(resolve_plan(self.work_order(), wrong_unit))

    def test_executor_rejects_unknown_method_duplicate_binding_and_hostile_operations(self):
        base = resolve_plan(self.work_order(), self.r1_observations()).as_dict()
        for mutation, message in (
            ({"method_id": "unknown.v1"}, "unknown smart method"),
            ({"input_bindings": {**base["input_bindings"], "surface_runoff": "precipitation-1"}}, "duplicate observation binding"),
            ({"operations": [{"op": "calculate", "method_id": base["method_id"], "code": "import os"}]}, "operation schema"),
            ({"operations": [{"op": "fetch", "url": "https://evil.test"}]}, "operation schema"),
        ):
            payload = {**base, **mutation, "plan_id": f"hostile-{message}"}
            with self.assertRaisesRegex(ValueError, message):
                execute_plan(CalculationPlan.from_dict(payload), self.r1_observations())

    def test_executor_rejects_nonfinite_unbacked_or_changed_inputs(self):
        plan = resolve_plan(self.work_order(), self.r1_observations())
        changed = self.r1_observations(); changed[-1] = observation("ecosystem_area", 2, "hm2", suffix="new")
        with self.assertRaisesRegex(ValueError, "missing bound observation"):
            execute_plan(plan, changed)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            execute_plan(plan, [item.as_dict() if item.metric != "actual_et" else {**item.as_dict(), "value": float("inf")} for item in self.r1_observations()])


if __name__ == "__main__":
    unittest.main()

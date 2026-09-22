import unittest

from gep.methods import method_cards
from gep.runs import evaluate_frozen_graph


class FrozenRunTests(unittest.TestCase):
    """Break caught: a partial deterministic result could be presented as a full formal GEP total."""

    def test_evaluation_keeps_partial_material_result_and_withholds_formal_gep(self):
        graph = {
            "nodes": [
                {"node_key": "P1", "kind": "indicator", "category": "material", "applicability_status": "applicable"},
                {"node_key": "P1.maize.quantity", "kind": "input", "parent_key": "P1", "value": 10_000, "unit": "t/a"},
                {"node_key": "P1.maize.producer_price", "kind": "input", "parent_key": "P1", "value": 100, "unit": "元/t"},
                {"node_key": "P1.maize.intermediate_cost", "kind": "input", "parent_key": "P1", "value": 300_000, "unit": "元/a"},
                {"node_key": "P1.maize.labor", "kind": "input", "parent_key": "P1", "value": 200_000, "unit": "元/a"},
                {"node_key": "P1.maize.depreciation", "kind": "input", "parent_key": "P1", "value": 80_000, "unit": "元/a"},
                {"node_key": "P1.maize.tax_net", "kind": "input", "parent_key": "P1", "value": 20_000, "unit": "元/a"},
                {"node_key": "P1.maize.capital_return", "kind": "input", "parent_key": "P1", "value": 50_000, "unit": "元/a"},
                {"node_key": "P4", "kind": "indicator", "category": "material", "applicability_status": "applicable"},
                {"node_key": "P4.harvest_quantity", "kind": "input", "parent_key": "P4", "value": 60, "unit": "t/a"},
            ],
        }

        run = evaluate_frozen_graph(graph)

        self.assertIsNone(run.formal_gep_value_yuan)
        self.assertEqual(run.item_results["P1"]["value_yuan"], 350_000)
        self.assertEqual(run.partial_category_totals_yuan["material"], 350_000)
        self.assertIn("P4:producer_price", run.blocking_nodes)
        self.assertIn("P4:production_cost", run.blocking_nodes)
        self.assertIn("R1:missing_indicator", run.blocking_nodes)

    def test_non_applicable_indicator_is_not_an_execution_blocker_or_zero_estimate(self):
        graph = {"nodes": [
            {"node_key": "R4", "kind": "indicator", "category": "regulating", "applicability_status": "not_applicable"},
        ]}

        run = evaluate_frozen_graph(graph)

        self.assertIsNone(run.item_results["R4"]["value_yuan"])
        self.assertIsNone(run.formal_gep_value_yuan)
        self.assertIn("P1:missing_indicator", run.blocking_nodes)
        self.assertNotIn("R4:method_implementation_pending", run.blocking_nodes)

    def test_formal_total_requires_an_approved_adjustment_ledger_even_when_subjects_are_resolved(self):
        graph = {"nodes": [
            {"node_key": card.indicator_id, "kind": "indicator", "category": "material", "applicability_status": "not_applicable"}
            for card in method_cards()
        ]}

        run = evaluate_frozen_graph(graph)

        self.assertIsNone(run.formal_gep_value_yuan)
        self.assertIn("adjustment_ledger:missing_or_unapproved", run.blocking_nodes)


if __name__ == "__main__":
    unittest.main()

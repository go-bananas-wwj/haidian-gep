import unittest

from gep.admission import CORE_FIELDS, INDICATOR_IDS
from gep.methods import method_cards


class MethodCardTests(unittest.TestCase):
    """Break caught: an indicator could lose its specified method or input contract."""

    def test_all_22_indicators_have_a_standard_method_card_and_exact_field_contract(self):
        cards = {card.indicator_id: card for card in method_cards()}

        self.assertEqual(set(cards), set(INDICATOR_IDS))
        for indicator_id in INDICATOR_IDS:
            self.assertEqual(cards[indicator_id].required_fields, tuple(CORE_FIELDS[indicator_id].split("|")))
            self.assertTrue(cards[indicator_id].standard_clause.startswith("A."))
            self.assertEqual(cards[indicator_id].approval_status, "pending_human_approval")

        self.assertEqual(cards["P1"].standard_clause, "A.1")
        self.assertEqual(cards["R6"].standard_clause, "A.34--A.54")
        self.assertEqual(cards["C3"].standard_clause, "A.78--A.82")

    def test_coastal_protection_card_requires_inland_scope_evidence_for_non_applicability(self):
        card = next(card for card in method_cards() if card.indicator_id == "R4")

        self.assertIn("inland_boundary_evidence", card.required_fields)
        self.assertIn("not_applicable", card.applicability_rule)


if __name__ == "__main__":
    unittest.main()

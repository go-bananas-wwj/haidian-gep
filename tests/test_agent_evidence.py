import unittest


class EvidenceValidatorTests(unittest.TestCase):
    @staticmethod
    def target(**overrides):
        target = {"metric": "ecosystem_area", "region_code": "110108", "year": 2024, "unit": "hm2"}
        target.update(overrides)
        return target

    @staticmethod
    def item(**overrides):
        item = {
            "source_id": "source-1", "source_type": "official_dataset",
            "metric": "ecosystem_area", "value": 23044.15, "unit": "hm2",
            "region_code": "110108", "year": 2024,
            "locator": "表 2", "source_sha256": "a" * 64,
            "checked_utc": "2026-09-29T00:00:00Z", "reproducible": True,
        }
        item.update(overrides)
        return item

    def test_exact_admitted_observation_is_tier_a(self):
        """Break caught: an exact admitted local fact could be unnecessarily sent to manual review."""
        from gep.agent.evidence import EvidenceValidator

        item = self.item(source_type="derived_observation")
        result = EvidenceValidator().validate(self.target(), [item])
        self.assertEqual(result.risk_tier, "A")
        self.assertEqual(len(result.accepted_items), 1)
        self.assertIsNone(result.human_action)

    def test_reproducible_official_public_value_is_tier_b(self):
        """Break caught: a verified official public calculation could be mislabeled as an untrusted model estimate."""
        from gep.agent.evidence import EvidenceValidator

        result = EvidenceValidator().validate(self.target(), [self.item()])
        self.assertEqual(result.risk_tier, "B")
        self.assertEqual(result.accepted_items[0]["normalized_value"], 23044.15)

    def test_cross_region_literature_proxy_is_tier_c(self):
        """Break caught: a transferable literature parameter from another region could look locally observed."""
        from gep.agent.evidence import EvidenceValidator

        proxy = self.item(
            source_type="paper", region_code="320000", proxy_allowed=True,
            source_id="paper-1", reproducible=False,
        )
        result = EvidenceValidator().validate(self.target(), [proxy])
        self.assertEqual(result.risk_tier, "C")
        self.assertEqual(result.accepted_items[0]["region_match"], "proxy")

    def test_conflicting_values_are_tier_d_with_one_review_action(self):
        """Break caught: the agent could silently choose between two conflicting official values."""
        from gep.agent.evidence import EvidenceValidator

        second = self.item(source_id="source-2", value=21000.0, source_sha256="b" * 64)
        result = EvidenceValidator().validate(self.target(), [self.item(), second])
        self.assertEqual(result.risk_tier, "D")
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(result.human_action["reason_code"], "source_conflict")
        self.assertEqual(set(result.human_action["source_ids"]), {"source-1", "source-2"})

    def test_registered_linear_unit_conversion_is_audited(self):
        """Break caught: equivalent area values in square kilometres could be compared without conversion."""
        from gep.agent.evidence import EvidenceValidator

        square_km = self.item(value=230.4415, unit="km2")
        result = EvidenceValidator().validate(self.target(), [square_km])
        self.assertEqual(result.risk_tier, "B")
        self.assertAlmostEqual(result.accepted_items[0]["normalized_value"], 23044.15)
        self.assertEqual(result.unit_conversions[0]["formula"], "km2 × 100 = hm2")

    def test_old_price_evidence_is_downgraded(self):
        """Break caught: an old market price could be treated as a current official fact."""
        from gep.agent.evidence import EvidenceValidator

        target = self.target(metric="carbon_price", unit="CNY/t", value_kind="price", max_age_years=1)
        price = self.item(metric="carbon_price", unit="CNY/t", value=58.0, year=2021)
        result = EvidenceValidator().validate(target, [price])
        self.assertEqual(result.risk_tier, "C")
        self.assertIn("stale", result.accepted_items[0]["cautions"])

    def test_web_record_missing_locator_hash_or_timestamp_is_rejected(self):
        """Break caught: an unverifiable web snippet could enter the accepted evidence set."""
        from gep.agent.evidence import EvidenceValidator

        incomplete = self.item(locator="", source_sha256="", checked_utc="")
        result = EvidenceValidator().validate(self.target(), [incomplete])
        self.assertEqual(result.risk_tier, "D")
        self.assertEqual(len(result.accepted_items), 0)
        self.assertEqual(result.rejected_items[0]["reason"], "missing_provenance")
        self.assertEqual(result.human_action["reason_code"], "no_valid_evidence")

    def test_unregistered_unit_conversion_is_rejected(self):
        """Break caught: an unknown unit could be numerically adopted without a reviewed conversion."""
        from gep.agent.evidence import EvidenceValidator

        result = EvidenceValidator().validate(self.target(), [self.item(unit="acre")])
        self.assertEqual(result.risk_tier, "D")
        self.assertEqual(result.rejected_items[0]["reason"], "unit_mismatch")


if __name__ == "__main__":
    unittest.main()

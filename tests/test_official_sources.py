import unittest
from unittest.mock import patch


class Response:
    status = 200
    headers = {"Content-Type": "application/pdf", "ETag": "official-v1", "Last-Modified": "Mon, 30 Jun 2025 00:00:00 GMT"}

    def __init__(self, final_url):
        self.final_url = final_url

    def geturl(self):
        return self.final_url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class OfficialSourceRegistryTests(unittest.TestCase):
    def test_search_matches_exact_node_region_and_year(self):
        """Break caught: an official fact could be offered to the wrong field, place, or year."""
        from gep.official_sources import OfficialSourceRegistry

        registry = OfficialSourceRegistry()
        matches = registry.search({
            "node_key": "R6.ecosystem_area", "region_code": "110108", "year": 2024,
        })
        wrong_year = registry.search({
            "node_key": "R6.ecosystem_area", "region_code": "110108", "year": 2023,
        })

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source_id"], "beijing_greening_resources_2024")
        self.assertEqual(matches[0]["value"], 14069.69)
        self.assertEqual(matches[0]["unit"], "hm2")
        self.assertEqual(matches[0]["risk_tier"], "B")
        self.assertEqual(wrong_year, [])

    def test_registry_contains_water_and_green_official_facts(self):
        """Break caught: the initial Internet research could omit the two user-requested official source families."""
        from gep.official_sources import OfficialSourceRegistry

        registry = OfficialSourceRegistry()
        water = registry.search({"node_key": "P5.local_used_water", "region_code": "110108", "year": 2024})
        green = registry.search({"node_key": "R8.ecosystem_area", "region_code": "110108", "year": 2024})

        self.assertEqual(water[0]["publisher"], "北京市水务局")
        self.assertEqual(water[0]["value"], 27997.4)
        self.assertEqual(green[0]["publisher"], "北京市园林绿化局")

    def test_verify_rejects_non_official_domains_before_network_access(self):
        """Break caught: an arbitrary webpage could be promoted to an official source."""
        from gep.official_sources import OfficialSourceRegistry

        registry = OfficialSourceRegistry()
        with patch("gep.official_sources.urlopen") as urlopen, self.assertRaises(ValueError):
            registry.verify({"url": "https://example.com/value.pdf"})
        urlopen.assert_not_called()

    def test_verify_rejects_redirect_outside_official_allowlist(self):
        """Break caught: a trusted URL could redirect to an untrusted evidence host."""
        from gep.official_sources import OfficialSourceRegistry

        registry = OfficialSourceRegistry()
        record = registry.search({"node_key": "R6.ecosystem_area", "region_code": "110108", "year": 2024})[0]
        with patch("gep.official_sources.urlopen", return_value=Response("https://example.com/redirect.pdf")):
            with self.assertRaises(ValueError):
                registry.verify(record)

    def test_verify_records_sanitized_online_metadata(self):
        """Break caught: a fetched official source could lose when and what URL was actually verified."""
        from gep.official_sources import OfficialSourceRegistry

        registry = OfficialSourceRegistry()
        record = registry.search({"node_key": "R6.ecosystem_area", "region_code": "110108", "year": 2024})[0]
        with patch("gep.official_sources.urlopen", return_value=Response(record["url"])):
            verified = registry.verify(record)

        self.assertEqual(verified["online_status"], "verified")
        self.assertEqual(verified["http_status"], 200)
        self.assertEqual(verified["content_type"], "application/pdf")
        self.assertEqual(verified["etag"], "official-v1")
        self.assertTrue(verified["checked_utc"].endswith("+00:00"))
        self.assertNotIn("body", verified)


if __name__ == "__main__":
    unittest.main()

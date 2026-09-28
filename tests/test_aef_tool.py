import hashlib
import json
import tempfile
import unittest
from pathlib import Path


VRT = """<VRTDataset rasterXSize="8192" rasterYSize="8192" subClass="VRTWarpedDataset">
<SRS>PROJCS["WGS 84 / UTM zone 50N",AUTHORITY["EPSG","32650"]]</SRS>
<GeoTransform>418080,10,0,4423680,0,-10</GeoTransform>
{bands}
<GDALWarpOptions><SourceDataset relativeToVRT="0">{source}</SourceDataset></GDALWarpOptions>
</VRTDataset>"""


class AefSpatialToolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        folder = self.root / "01_raw" / "remote_sensing" / "alphaearth_2024"
        folder.mkdir(parents=True)
        bands = "".join(f'<VRTRasterBand dataType="Int8" band="{index}"><Description>A{index-1:02d}</Description></VRTRasterBand>' for index in range(1, 65))
        source = "/vsis3/us-west-2.opendata.source.coop/tge-labs/aef/v1/annual/2024/50N/tile.tiff"
        self.vrt = folder / "tile.vrt"
        self.vrt.write_text(VRT.format(bands=bands, source=source), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_inspects_2024_embedding_metadata_and_reports_exact_gaps(self):
        """Break caught: a VRT pointer could be presented as a completed green classification."""
        from gep.geo.aef_tool import AefSpatialTool

        result = AefSpatialTool(self.root).inspect({"node_key": "R6.ecosystem_area", "year": 2024})

        self.assertEqual(result["status"], "research_gap")
        self.assertEqual(result["year"], 2024)
        self.assertEqual(result["band_count"], 64)
        self.assertEqual(result["pixel_size_m"], 10.0)
        self.assertEqual(result["crs"], "EPSG:32650")
        self.assertEqual(result["source_scheme"], "source-cooperative-vsis3")
        self.assertEqual(len(result["vrt_sha256"]), 64)
        self.assertIn("confirmed_boundary", result["missing_prerequisites"])
        self.assertIn("training_labels", result["missing_prerequisites"])
        self.assertIn("validated_green_product", result["missing_prerequisites"])
        self.assertNotIn("green_area_hm2", result)

    def test_rejects_remote_dataset_outside_the_aef_open_bucket(self):
        """Break caught: a VRT could make the worker read an arbitrary remote object."""
        from gep.geo.aef_tool import AefSpatialTool

        text = self.vrt.read_text().replace("/vsis3/us-west-2.opendata.source.coop/tge-labs/aef/", "/vsis3/private-bucket/")
        self.vrt.write_text(text)

        with self.assertRaises(ValueError):
            AefSpatialTool(self.root).inspect({"node_key": "R6.ecosystem_area", "year": 2024})

    def test_rejects_unverified_classification_claim(self):
        """Break caught: a JSON claim without a matching raster hash could masquerade as an AEF result."""
        from gep.geo.aef_tool import AefSpatialTool

        features = self.root / "03_features"
        features.mkdir()
        (features / "aef_green_validation.json").write_text(json.dumps({
            "validated": True, "green_area_hm2": 14000, "output_sha256": "b" * 64,
            "overall_accuracy": 0.9,
        }))

        result = AefSpatialTool(self.root).inspect({"node_key": "R6.ecosystem_area", "year": 2024})

        self.assertEqual(result["status"], "research_gap")
        self.assertIn("validated_green_product", result["missing_prerequisites"])
        self.assertNotIn("green_area_hm2", result)

    def test_accepts_only_a_matching_validated_spatial_product(self):
        from gep.geo.aef_tool import AefSpatialTool

        catalog = self.root / "00_catalog"
        features = self.root / "03_features"
        catalog.mkdir(); features.mkdir()
        (catalog / "confirmed_boundary.geojson").write_text('{"type":"FeatureCollection","features":[]}')
        (features / "aef_green_labels.geojson").write_text('{"type":"FeatureCollection","features":[]}')
        output = features / "aef_green_2024.tif"
        output.write_bytes(b"validated-aef-product")
        output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        (features / "aef_green_validation.json").write_text(json.dumps({
            "validated": True, "green_area_hm2": 14021.5, "output_sha256": output_hash,
            "overall_accuracy": 0.87, "output_file": output.name,
        }))

        result = AefSpatialTool(self.root).inspect({"node_key": "R6.ecosystem_area", "year": 2024})

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["green_area_hm2"], 14021.5)
        self.assertEqual(result["overall_accuracy"], 0.87)
        self.assertEqual(result["output_sha256"], output_hash)

    def test_non_spatial_node_is_not_applicable(self):
        from gep.geo.aef_tool import AefSpatialTool

        result = AefSpatialTool(self.root).inspect({"node_key": "P1.maize.producer_price", "year": 2024})
        self.assertEqual(result, {"status": "not_applicable"})


if __name__ == "__main__":
    unittest.main()

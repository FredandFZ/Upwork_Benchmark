from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_model import ARTIFACT_MODEL
from artifact_runtime import build_artifacts, check_artifacts, parse_artifacts


class ArtifactContractTest(unittest.TestCase):
    def test_domain_model_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            checked = check_artifacts(directory)
            self.assertEqual(checked["domain_model"], ARTIFACT_MODEL["schema"])
            self.assertIsInstance(parsed, dict)

    def test_battery_connector_uses_smd_jst_ph_footprint(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        component = next(item for item in parsed["components"] if item["reference"] == "J_BAT")
        footprint = next(item for item in parsed["footprints"] if item["reference"] == "J_BAT")
        self.assertEqual(component["mounting_style"], "smd")
        self.assertIn("JST_PH", component["footprint"])
        self.assertEqual(component["side"], "B.Cu")
        self.assertTrue(all(pad["type"] == "smd" for pad in footprint["pads"]))
        self.assertEqual([pin["net"] for pin in component["pins"]], ["GND", "VCC_BAT", "BAT_NTC"])


if __name__ == "__main__":
    unittest.main()

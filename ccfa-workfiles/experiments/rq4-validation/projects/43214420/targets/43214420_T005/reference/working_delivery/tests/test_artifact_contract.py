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

    def test_jst_ph_pinout_is_present_in_schematic_and_pcb(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        component = next(item for item in parsed["components"] if item["reference"] == "J_BAT")
        footprint = next(item for item in parsed["footprints"] if item["reference"] == "J_BAT")
        self.assertIn("JST_PH", component["footprint"])
        self.assertEqual([(pin["number"], pin["name"], pin["net"]) for pin in component["pins"]],
                         [("1", "GND", "GND"), ("2", "VCC", "VCC_BAT"), ("3", "NTC", "BAT_NTC")])
        self.assertEqual([pad["net"] for pad in footprint["pads"]], ["GND", "VCC_BAT", "BAT_NTC"])


if __name__ == "__main__":
    unittest.main()

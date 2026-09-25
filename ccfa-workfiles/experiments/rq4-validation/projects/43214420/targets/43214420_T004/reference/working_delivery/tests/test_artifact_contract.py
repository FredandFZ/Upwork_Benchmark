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

    def test_back_side_battery_connector_opposes_usb_without_covering_holes(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        footprints = {item["reference"]: item for item in parsed["footprints"]}
        battery, usb = footprints["J_BAT"], footprints["J_USB"]
        self.assertEqual(battery["side"], "B.Cu")
        self.assertEqual(usb["side"], "F.Cu")
        self.assertGreater(battery["at_mm"][0], usb["at_mm"][0])
        self.assertEqual(len(parsed["geometry"]["holes"]), 8)
        for hole in parsed["geometry"]["holes"]:
            dx = abs(battery["at_mm"][0] - hole["at_mm"][0])
            dy = abs(battery["at_mm"][1] - hole["at_mm"][1])
            self.assertTrue(dx > battery["courtyard_mm"][0] / 2 + hole["diameter_mm"] / 2 or
                            dy > battery["courtyard_mm"][1] / 2 + hole["diameter_mm"] / 2)


if __name__ == "__main__":
    unittest.main()

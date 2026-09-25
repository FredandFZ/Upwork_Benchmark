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

    def test_connector_arrangement_and_mechanical_clearance(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        footprints = {item["reference"]: item for item in parsed["footprints"]}
        self.assertEqual(parsed["geometry"]["board_size"], {"width": 100.0, "height": 50.0})
        self.assertEqual(len(parsed["geometry"]["holes"]), 8)
        self.assertEqual({hole["fastener"] for hole in parsed["geometry"]["holes"]}, {"M2.5"})
        battery, board = footprints["J_BAT"], footprints["J_BOARD"]
        gap = abs(battery["at_mm"][0] - board["at_mm"][0]) - battery["courtyard_mm"][0] / 2 - board["courtyard_mm"][0] / 2
        self.assertGreater(gap, 0)
        for connector in (battery, board):
            for hole in parsed["geometry"]["holes"]:
                dx = abs(connector["at_mm"][0] - hole["at_mm"][0])
                dy = abs(connector["at_mm"][1] - hole["at_mm"][1])
                self.assertTrue(dx > connector["courtyard_mm"][0] / 2 + hole["diameter_mm"] / 2 or
                                dy > connector["courtyard_mm"][1] / 2 + hole["diameter_mm"] / 2)
        self.assertEqual(footprints["J_USB"]["at_mm"][0], 0.0)


if __name__ == "__main__":
    unittest.main()

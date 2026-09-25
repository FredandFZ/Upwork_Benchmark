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

    def test_panel_io_boot_button_and_slide_switch_are_physical(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        components = {item["reference"]: item for item in parsed["components"]}
        panel_nets = {pin["net"] for pin in components["J_PANEL"]["pins"]}
        self.assertTrue({"TOUCH1", "TOUCH2", "BUTTON1", "BUTTON2", "RESET"}.issubset(panel_nets))
        self.assertIn("SW_SPST", components["SW_BOOT"]["footprint"])
        self.assertEqual({pin["net"] for pin in components["SW_BOOT"]["pins"]}, {"BOOT", "GND"})
        self.assertIn("SW_SPDT", components["SW_MODE"]["footprint"])
        self.assertEqual(components["SW_MODE"]["properties"]["actuator"], "slide")


if __name__ == "__main__":
    unittest.main()

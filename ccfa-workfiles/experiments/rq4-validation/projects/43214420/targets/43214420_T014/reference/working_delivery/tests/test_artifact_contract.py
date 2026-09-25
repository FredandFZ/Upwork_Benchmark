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

    def test_boost_enable_and_led_level_shifter_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        components = {item["reference"]: item for item in parsed["components"]}
        pinmap = lambda ref: {(pin["name"], pin["net"]) for pin in components[ref]["pins"]}
        self.assertIn(("GPIO3", "5V_EN_GPIO3"), pinmap("U_MCU"))
        self.assertIn(("EN", "5V_EN_GPIO3"), pinmap("U_BOOST"))
        self.assertIn(("VOUT", "LED_5V"), pinmap("U_BOOST"))
        self.assertEqual(components["U_BOOST"]["properties"]["rated_output_ma"], 1200)
        self.assertEqual(components["R_EN"]["value"], "330kΩ")
        self.assertTrue({("A", "LED_DATA_3V3"), ("Y", "LED_DATA_5V"), ("VCC", "LED_5V")}.issubset(pinmap("U_LS")))
        self.assertTrue({("VDD", "LED_5V"), ("DIN", "LED_DATA_5V")}.issubset(pinmap("D_LED")))


if __name__ == "__main__":
    unittest.main()

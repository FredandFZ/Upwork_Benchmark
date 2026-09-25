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

    def test_required_gpio_assignments_and_level_shifting(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        components = {item["reference"]: item for item in parsed["components"]}
        mcu_pins = {(pin["name"], pin["net"]) for pin in components["U_MCU"]["pins"]}
        self.assertTrue({("GPIO5", "5V_EN"), ("GPIO38", "SCL0"), ("GPIO26", "SPI_MOSI")}.issubset(mcu_pins))
        self.assertFalse({"GPIO22", "GPIO23", "GPIO25", "GPIO27"} & {name for name, _ in mcu_pins})
        boost_pins = {(pin["name"], pin["net"]) for pin in components["U_BOOST"]["pins"]}
        self.assertIn(("EN", "5V_EN"), boost_pins)
        shifter_pins = {(pin["name"], pin["net"]) for pin in components["U_LS"]["pins"]}
        self.assertTrue({("A", "LED_DATA_3V3"), ("Y", "LED_DATA_5V"), ("VCC", "LED_5V")}.issubset(shifter_pins))


if __name__ == "__main__":
    unittest.main()

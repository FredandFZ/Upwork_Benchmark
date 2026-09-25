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

    def test_zero_ohm_i2c_series_resistors_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
        components = {item["reference"]: item for item in parsed["components"]}
        nets = {item["name"]: set(item["members"]) for item in parsed["nets"]}
        for reference, controller_net, bus_net in (("R_SDA", "SDA0_CTRL", "SDA0"), ("R_SCL", "SCL0_CTRL", "SCL0")):
            self.assertEqual(components[reference]["value"], "0Ω")
            self.assertEqual(components[reference]["properties"]["installation_policy"], "retain")
            self.assertIn(f"{reference}.1", nets[controller_net])
            self.assertIn(f"{reference}.2", nets[bus_net])


if __name__ == "__main__":
    unittest.main()

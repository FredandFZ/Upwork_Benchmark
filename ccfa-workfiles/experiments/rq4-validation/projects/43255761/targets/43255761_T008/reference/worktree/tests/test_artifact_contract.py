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


if __name__ == "__main__":
    unittest.main()

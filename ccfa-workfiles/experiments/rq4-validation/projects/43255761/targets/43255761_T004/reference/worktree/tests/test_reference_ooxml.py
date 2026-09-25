from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_each_control_alias_matches_initial_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            self.assertTrue(parsed["has_glossary"])
            self.assertGreaterEqual(len(parsed["control_details"]), 5)
            for control in parsed["control_details"]:
                self.assertEqual(control["label"], control["text"])
                self.assertTrue(control["placeholder_part"])
                self.assertTrue(control["showing_placeholder"])


if __name__ == "__main__":
    unittest.main()


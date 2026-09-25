from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_help_is_in_label_and_field(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            for control in parsed["control_details"]:
                self.assertEqual(control["label"], control["text"])
            values = [item["text"] for item in parsed["help"]]
            self.assertEqual(values.count("CONTROL_LABEL"), len(parsed["control_details"]))
            self.assertEqual(values.count("IN_FIELD"), len(parsed["control_details"]))


if __name__ == "__main__":
    unittest.main()


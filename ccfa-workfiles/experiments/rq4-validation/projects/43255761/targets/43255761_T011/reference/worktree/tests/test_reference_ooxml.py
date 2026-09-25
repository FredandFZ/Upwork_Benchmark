from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_headline_accepts_regular_enter(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            headline = next(item for item in parsed["control_details"] if item["tag"] == "seminar-headline")
            self.assertTrue(headline["multiline"])
            self.assertTrue(headline["showing_placeholder"])
            self.assertEqual(headline["text"], "[Tilføj overskrift]")


if __name__ == "__main__":
    unittest.main()


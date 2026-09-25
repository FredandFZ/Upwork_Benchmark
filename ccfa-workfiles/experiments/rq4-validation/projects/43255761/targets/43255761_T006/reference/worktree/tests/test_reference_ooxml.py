from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_empty_controls_have_persistent_placeholder_source(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            self.assertTrue(parsed["has_glossary"])
            for control in parsed["control_details"]:
                self.assertTrue(control["placeholder_part"])
                self.assertTrue(control["showing_placeholder"])
            with zipfile.ZipFile(Path(directory) / "template.docx") as archive:
                glossary = archive.read("word/glossary/document.xml").decode("utf-8")
            for control in parsed["control_details"]:
                self.assertIn(control["placeholder_part"], glossary)


if __name__ == "__main__":
    unittest.main()


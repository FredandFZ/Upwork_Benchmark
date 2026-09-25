from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_editable_fields_keep_visible_duplicate_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            for control in parsed["control_details"]:
                self.assertTrue(control["text"])
                self.assertEqual(control["label"], control["text"])
            with zipfile.ZipFile(Path(directory) / "template.docx") as archive:
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertGreaterEqual(document.count('w:color w:val="808080"'), len(parsed["control_details"]))


if __name__ == "__main__":
    unittest.main()


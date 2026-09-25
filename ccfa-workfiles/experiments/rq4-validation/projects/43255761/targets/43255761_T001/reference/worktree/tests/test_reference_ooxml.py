from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_caption_text_style_is_real_and_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            style = next(item for item in parsed["style_details"] if item["name"] == "caption text")
            self.assertEqual(style["font"], "Century Gothic")
            self.assertTrue(style["italic"])
            self.assertEqual(style["line"], "300")
            with zipfile.ZipFile(Path(directory) / "template.docx") as archive:
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertGreaterEqual(document.count('w:pStyle w:val="captiontext"'), 2)


if __name__ == "__main__":
    unittest.main()


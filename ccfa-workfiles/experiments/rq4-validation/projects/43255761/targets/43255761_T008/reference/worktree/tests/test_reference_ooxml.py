from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import build_artifacts, parse_artifacts


class ReferenceOOXMLTest(unittest.TestCase):
    def test_feedback_controls_layout_dates_and_theme_are_ooxml(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            by_tag = {item["tag"]: item for item in parsed["control_details"]}
            expected = {
                "proposal-headline", "proposal-advantages", "proposal-settings",
                "proposal-attachments", "guidance-reflections", "seminar-agenda",
                "seminar-item-title", "proposal-date", "board-meeting-date",
            }
            self.assertTrue(expected.issubset(by_tag))
            for tag in expected - {"proposal-date", "board-meeting-date"}:
                self.assertTrue(by_tag[tag]["multiline"])
            self.assertTrue(by_tag["proposal-date"]["date"])
            self.assertTrue(by_tag["board-meeting-date"]["date"])
            self.assertEqual(parsed["fixed_layout_tables"], 3)
            self.assertEqual(len(parsed["theme_colors"]), 12)
            with zipfile.ZipFile(Path(directory) / "template.docx") as archive:
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertIn('w:tblLayout w:type="fixed"', document)
            self.assertIn('<w:bottom w:val="nil"/>', document)


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from Code.rq4_repository_scaffolds_artifacts import augment_artifact_repository


PROFILES = {
    "43214420": {
        "renderer": "kicad",
        "primary_artifacts": [
            "dist/design.kicad_sch",
            "dist/design.kicad_pcb",
            "dist/design-summary.txt",
        ],
    },
    "43255761": {
        "renderer": "docx",
        "primary_artifacts": ["dist/template.docx", "dist/template-preview.html"],
    },
    "44036410": {
        "renderer": "report",
        "primary_artifacts": [
            "dist/security-report.docx",
            "dist/security-report.pdf",
            "dist/report-preview.html",
        ],
    },
}


class ArtifactRepositoryScaffoldTest(unittest.TestCase):
    def _repository(
        self,
        root: Path,
        project_id: str,
        features: list[dict],
    ) -> Path:
        repository = root / project_id
        (repository / "src").mkdir(parents=True)
        profile = PROFILES[project_id]
        project = {
            "project_id": project_id,
            "title": f"Project {project_id}",
            "renderer": profile["renderer"],
            "primary_artifacts": profile["primary_artifacts"],
        }
        (repository / "src" / "current_state.py").write_text(
            f"PROJECT = {project!r}\nFEATURES = {features!r}\n",
            encoding="utf-8",
        )
        (repository / "src" / "runtime.py").write_text(
            "def build(output='dist'):\n    raise AssertionError('base build used')\n\n"
            "def check(output='dist'):\n    raise AssertionError('base check used')\n",
            encoding="utf-8",
        )
        augment_artifact_repository(repository, project_id, features, profile)
        return repository

    def _build_and_parse(self, repository: Path) -> dict:
        code = (
            "import json,sys;sys.path.insert(0,'src');"
            "from runtime import build,check;"
            "from artifact_runtime import parse_artifacts;"
            "build('dist');result=check('dist');"
            "print(json.dumps({'check':result,'parsed':parse_artifacts('dist')}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repository,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_kicad_model_round_trips_components_nets_footprints_and_geometry(self):
        features = [
            {
                "slug": "display-connector",
                "title": "Display Connector",
                "attributes": {
                    "connector_type": "JST-GH 1.25mm",
                    "signal_connector_pinout": {
                        "pin_1": "SDA0",
                        "pin_2": "SCL0",
                        "pin_3": "IRQ",
                    },
                    "board_dimensions_mm": {"width": 140, "height": 100},
                },
                "components": ["HARDWARE"],
                "contexts": ["MAIN_BOARD"],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory), "43214420", features)
            payload = self._build_and_parse(repository)
            parsed = payload["parsed"]
            self.assertEqual(parsed["components"], ["J1"])
            self.assertEqual(parsed["footprints"], ["JST-GH_1.25mm"])
            self.assertEqual(
                [item["name"] for item in parsed["nets"]],
                ["IRQ", "SCL0", "SDA0"],
            )
            self.assertEqual(len(parsed["geometry_lines"]), 4)
            self.assertTrue(parsed["balanced"])
            contract = json.loads(
                (repository / "behavior_contract.json").read_text(encoding="utf-8")
            )
            self.assertIn("nets.name/members", contract["observable_surfaces"])

    def test_docx_model_emits_parseable_styles_controls_fields_and_spacing(self):
        features = [
            {
                "slug": "template-fields",
                "title": "Template Fields",
                "attributes": {
                    "editable_fields": ["customer_name", "assessment_date"],
                    "assessment_date_field_format": "Assessment Date: [Assessment Date]",
                    "right_side_text_padding": "8 pt",
                    "default_document_language": "Danish",
                    "style_prefix": "NXQ -",
                    "title_font_size": "40pt",
                    "help_instruction": "Select a field and enter the customer value.",
                },
                "components": ["MICROSOFT_WORD"],
                "contexts": ["MASTER_TEMPLATE"],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory), "43255761", features)
            payload = self._build_and_parse(repository)
            parsed = payload["parsed"]
            self.assertIn("NXQ - Template Fields", parsed["styles"])
            self.assertEqual(
                parsed["content_controls"], ["customer-name", "assessment-date"]
            )
            self.assertIn("DOCPROPERTY assessment-date-field-format", parsed["fields"])
            self.assertTrue(parsed["spacing"])
            self.assertEqual(parsed["help"][0]["source"], "template-fields")
            self.assertEqual(
                parsed["spacing_contract"][0]["property"],
                "right_side_text_padding",
            )
            self.assertEqual(parsed["language"], "da-DK")
            with zipfile.ZipFile(repository / "dist" / "template.docx") as archive:
                self.assertIn("word/styles.xml", archive.namelist())
                self.assertIn("word/settings.xml", archive.namelist())
                self.assertIn("customXml/item1.xml", archive.namelist())

    def test_report_model_emits_sections_manifest_and_pdf_coordinates(self):
        features = [
            {
                "slug": "variant-set",
                "title": "Risk Variant Set",
                "attributes": {
                    "variant_codes": ["DX17", "DX18"],
                    "package_contents": ["fonts", "icons"],
                },
                "components": ["DOCUMENT_TEMPLATE"],
                "contexts": ["FRONT_PAGE"],
            },
            {
                "slug": "result-summary",
                "title": "Result Summary",
                "attributes": {"score_heading": "Vehicle Security Score"},
                "components": ["DOCUMENT_CONTENT"],
                "contexts": ["FRONT_PAGE"],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory), "44036410", features)
            payload = self._build_and_parse(repository)
            parsed = payload["parsed"]
            self.assertEqual(len(parsed["pdf_coordinates"]), 2)
            self.assertEqual(parsed["package_manifest"]["variants"], ["DX17", "DX18"])
            self.assertEqual(parsed["package_manifest"]["assets"], ["fonts", "icons"])
            self.assertTrue(
                (repository / "dist" / "security-report.pdf")
                .read_bytes()
                .startswith(b"%PDF-")
            )

    def test_private_construction_identifiers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "43255761"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "private construction identifier"):
                augment_artifact_repository(
                    root,
                    "43255761",
                    [{"slug": "REQ_PRIVATE", "title": "Leaking field"}],
                    PROFILES["43255761"],
                )

    def test_unsupported_project_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            augment_artifact_repository(root, "42204309", [], {"renderer": "web"})
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

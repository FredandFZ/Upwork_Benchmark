from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import zlib

from Code.audit_rq4_leakage import audit_leakage


def _write_work_item(path: Path, *, code_environment: dict | None = None) -> None:
    value = {
        "project_id": "project-public-name",
        "target_id": "target-public-name",
        "pre_task_observable_features": {
            "private-requirement": {
                "attributes": {"mode": "legacy-mode", "ticket_count": 2}
            }
        },
        "post_task_observable_features": {
            "private-requirement": {
                "attributes": {
                    "mode": "future-only-mode",
                    "ticket_count": 7,
                }
            }
        },
        "code_environment": code_environment or {},
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


class RQ4LeakageAuditTest(unittest.TestCase):
    def test_clean_agent_visible_repository_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("MODE = 'legacy-mode'\n", encoding="utf-8")
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(agent_visible=repo, work_item_path=work_item)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["rq4_eligibility_gate"], "PASS")
            self.assertEqual(report["unresolved_finding_count"], 0)

    def test_nested_docx_internal_id_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            docx = _zip_bytes(
                {"word/document.xml": b"<w:t>REQ_PRIVATE_FEATURE_S004</w:t>"}
            )
            outer = _zip_bytes({"assets/template.docx": docx})
            (repo / "bundle.zip").write_bytes(outer)
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(agent_visible=repo, work_item_path=work_item)

            self.assertEqual(report["overall"], "BLOCK")
            self.assertTrue(
                any(
                    finding["rule"] in {"INTERNAL_REQUIREMENT_ID", "INTERNAL_STATE_OR_EVENT_ID"}
                    and "template.docx!word/document.xml" in finding["artifact"]
                    for finding in report["findings"]
                )
            )

    def test_hidden_material_keyword_in_path_or_text_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "validator").mkdir(parents=True)
            (repo / "validator" / "notes.txt").write_text(
                "These are the hidden tests and acceptance criteria.", encoding="utf-8"
            )
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(agent_visible=repo, work_item_path=work_item)
            rules = {finding["rule"] for finding in report["findings"]}

            self.assertEqual(report["overall"], "BLOCK")
            self.assertIn("PRIVATE_EVALUATOR_PATH", rules)
            self.assertIn("HIDDEN_VALIDATOR_LEAK", rules)
            self.assertIn("ACCEPTANCE_CRITERIA_LEAK", rules)

    def test_future_only_exact_values_block_but_pre_values_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "state.json").write_text(
                '{"old": "legacy-mode", "mode": "future-only-mode", "ticket_count": 7}',
                encoding="utf-8",
            )
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(agent_visible=repo, work_item_path=work_item)
            future = [
                finding
                for finding in report["findings"]
                if finding["rule"] == "FUTURE_STATE_EXACT_VALUE"
            ]

            self.assertEqual(report["overall"], "BLOCK")
            self.assertEqual(len(future), 2)
            self.assertFalse(any("legacy-mode" in finding["evidence"] for finding in future))

    def test_flate_pdf_extractable_text_is_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            stream = zlib.compress(b"BT (reference delivery) Tj ET")
            pdf = (
                b"%PDF-1.4\n1 0 obj << /Filter /FlateDecode /Length "
                + str(len(stream)).encode("ascii")
                + b" >>\nstream\n"
                + stream
                + b"\nendstream\nendobj\n%%EOF"
            )
            (repo / "report.pdf").write_bytes(pdf)
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(agent_visible=repo, work_item_path=work_item)

            self.assertTrue(
                any(
                    finding["rule"] == "REFERENCE_DELIVERY_LEAK"
                    for finding in report["findings"]
                )
            )

    def test_private_package_exact_copy_and_boundary_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            private = repo / "researcher-private-validator"
            private.mkdir(parents=True)
            payload = b"private validator assertion material"
            (private / "validate.py").write_bytes(payload)
            (repo / "copied.py").write_bytes(payload)
            work_item = root / "work.json"
            _write_work_item(work_item)

            report = audit_leakage(
                agent_visible=repo,
                work_item_path=work_item,
                private_packages=[private],
            )
            rules = {finding["rule"] for finding in report["findings"]}

            self.assertEqual(report["overall"], "BLOCK")
            self.assertIn("PRIVATE_PACKAGE_INSIDE_AGENT_SURFACE", rules)
            self.assertIn("PRIVATE_PACKAGE_EXACT_COPY", rules)

    def test_stale_agent_surface_hash_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "pre_repo.zip"
            archive.write_bytes(_zip_bytes({"app.py": b"print('safe')\n"}))
            work_item = root / "work.json"
            _write_work_item(
                work_item,
                code_environment={"archive_sha256": "0" * 64},
            )

            report = audit_leakage(agent_visible=archive, work_item_path=work_item)

            self.assertTrue(
                any(
                    finding["rule"] == "AGENT_SURFACE_SOURCE_MISMATCH"
                    for finding in report["findings"]
                )
            )


if __name__ == "__main__":
    unittest.main()

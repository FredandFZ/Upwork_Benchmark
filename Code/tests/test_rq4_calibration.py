from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from Code.run_rq4_calibration import (
    RQ4CalibrationError,
    _tree_sha256,
    run_calibration,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_zip(path: Path, files: dict[str, str]) -> tuple[str, str]:
    source = path.parent / f"{path.stem}-source"
    source.mkdir()
    for relative, content in files.items():
        output = source / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(files):
            archive.write(source / relative, relative)
    return _sha256(path), _tree_sha256(source)


def _validator_source() -> str:
    return """from pathlib import Path
import sys
import time

check, repo = sys.argv[1], Path(sys.argv[2])
mode = (repo / "mode.txt").read_text(encoding="utf-8").strip()
if check == "target" and mode == "timeout":
    time.sleep(3)
if check == "build":
    raise SystemExit(0)
if check == "regression":
    raise SystemExit(1 if mode == "regression_fail" else 0)
if mode == "harness_fault":
    raise SystemExit(2)
raise SystemExit(0 if mode in {"reference", "regression_fail"} else 1)
"""


def _make_fixture(root: Path, *, reference_mode: str = "reference", timeout: int = 5):
    validator = root / "validator"
    validator.mkdir()
    script = validator / "validator.py"
    script.write_text(_validator_source(), encoding="utf-8")
    criteria = validator / "acceptance_criteria.json"
    criteria.write_text('{"criteria":["AC001"]}\n', encoding="utf-8")

    pre = root / "pre.zip"
    reference = root / "reference.zip"
    partial = root / "partial.zip"
    pre_sha, pre_tree = _write_zip(pre, {"mode.txt": "pre"})
    ref_sha, ref_tree = _write_zip(reference, {"mode.txt": reference_mode})
    partial_sha, partial_tree = _write_zip(partial, {"mode.txt": "partial"})
    spec = {
        "schema_version": "rq4-calibration-spec-v1",
        "status": "FROZEN",
        "project_id": "P1",
        "target_id": "P1_T001",
        "validator_id": "P1_T001_v1",
        "acceptance_criteria_sha256": _sha256(criteria),
        "validator_files": [
            {"path": "validator.py", "sha256": _sha256(script)},
            {"path": "acceptance_criteria.json", "sha256": _sha256(criteria)},
        ],
        "commands": {
            "build": ["{python}", "{validator_root}/validator.py", "build", "{repo}"],
            "target_test": [
                "{python}",
                "{validator_root}/validator.py",
                "target",
                "{repo}",
            ],
            "regression": [
                "{python}",
                "{validator_root}/validator.py",
                "regression",
                "{repo}",
            ],
        },
        "timeout_seconds": timeout,
        "network_policy": "DISABLED",
        "fresh_workspace_required": True,
        "environment_allowlist": [],
        "calibration_inputs": {
            "pre_repo": {"archive_sha256": pre_sha, "tree_sha256": pre_tree},
            "reference_delivery": {
                "archive_sha256": ref_sha,
                "tree_sha256": ref_tree,
            },
            "partial_deliveries": [
                {
                    "delivery_id": "partial_001",
                    "archive_sha256": partial_sha,
                    "tree_sha256": partial_tree,
                    "expected_result": "TARGET_TEST_FAIL",
                }
            ],
        },
    }
    spec_path = validator / "calibration_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path, pre, reference, partial


class RQ4CalibrationTests(unittest.TestCase):
    def test_expected_pre_reference_and_partial_results_pass_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(root)
            result = run_calibration(
                spec_path=spec,
                pre_repo_path=pre,
                reference_delivery_path=reference,
                partial_delivery_paths={"partial_001": partial},
                temporary_parent=root / "temp",
            )

            self.assertEqual(result["overall"], "PASS")
            self.assertTrue(result["calibration_complete"])
            self.assertTrue(result["eligible_for_freezing"])
            by_role = {row["role"]: row for row in result["deliveries"]}
            self.assertEqual(
                by_role["PRE_REPO"]["checks"]["target_test"]["outcome"],
                "CANDIDATE_FAIL",
            )
            self.assertEqual(
                by_role["REFERENCE_DELIVERY"]["checks"]["target_test"]["outcome"],
                "PASS",
            )
            self.assertEqual(result["identity"]["calibration_spec_sha256"], _sha256(spec))
            self.assertFalse((root / "temp").joinpath("pre_repo").exists())

    def test_exit_one_is_calibration_failure_not_harness_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(
                root, reference_mode="partial"
            )
            result = run_calibration(
                spec_path=spec,
                pre_repo_path=pre,
                reference_delivery_path=reference,
                partial_delivery_paths={"partial_001": partial},
            )

            self.assertEqual(result["overall"], "FAIL")
            self.assertTrue(result["calibration_complete"])
            self.assertFalse(result["eligible_for_freezing"])
            reference_row = result["deliveries"][1]
            self.assertEqual(
                reference_row["checks"]["target_test"]["outcome"],
                "CANDIDATE_FAIL",
            )
            self.assertEqual(reference_row["expectation"]["status"], "FAIL")

    def test_exit_two_is_harness_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(
                root, reference_mode="harness_fault"
            )
            result = run_calibration(
                spec_path=spec,
                pre_repo_path=pre,
                reference_delivery_path=reference,
                partial_delivery_paths={"partial_001": partial},
            )

            self.assertEqual(result["overall"], "HARNESS_ERROR")
            self.assertFalse(result["calibration_complete"])
            record = result["deliveries"][1]["checks"]["target_test"]
            self.assertEqual(record["outcome"], "HARNESS_FAULT")
            self.assertEqual(record["fault_kind"], "UNSUPPORTED_EXIT_CODE")

    def test_timeout_is_harness_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(
                root, reference_mode="timeout", timeout=1
            )
            result = run_calibration(
                spec_path=spec,
                pre_repo_path=pre,
                reference_delivery_path=reference,
                partial_delivery_paths={"partial_001": partial},
            )

            self.assertEqual(result["overall"], "HARNESS_ERROR")
            record = result["deliveries"][1]["checks"]["target_test"]
            self.assertEqual(record["fault_kind"], "TIMEOUT")

    def test_archive_hash_mismatch_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(root)
            with reference.open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaisesRegex(RQ4CalibrationError, "archive SHA-256"):
                run_calibration(
                    spec_path=spec,
                    pre_repo_path=pre,
                    reference_delivery_path=reference,
                    partial_delivery_paths={"partial_001": partial},
                )

    def test_unsafe_archive_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, partial = _make_fixture(root)
            with zipfile.ZipFile(reference, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            value = json.loads(spec.read_text(encoding="utf-8"))
            value["calibration_inputs"]["reference_delivery"]["archive_sha256"] = _sha256(reference)
            value["calibration_inputs"]["reference_delivery"].pop("tree_sha256")
            spec.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(RQ4CalibrationError, "unsafe path"):
                run_calibration(
                    spec_path=spec,
                    pre_repo_path=pre,
                    reference_delivery_path=reference,
                    partial_delivery_paths={"partial_001": partial},
                )

    def test_unsafe_partial_delivery_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, _, _, _ = _make_fixture(root)
            value = json.loads(spec.read_text(encoding="utf-8"))
            value["calibration_inputs"]["partial_deliveries"][0][
                "delivery_id"
            ] = "../escape"
            spec.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(RQ4CalibrationError, "safe unique name"):
                run_calibration(
                    spec_path=spec,
                    pre_repo_path=root / "pre.zip",
                    reference_delivery_path=root / "reference.zip",
                    partial_delivery_paths={"../escape": root / "partial.zip"},
                )

    def test_empty_partial_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, pre, reference, _ = _make_fixture(root)
            value = json.loads(spec.read_text(encoding="utf-8"))
            value["calibration_inputs"]["partial_deliveries"] = []
            spec.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(RQ4CalibrationError, "non-empty array"):
                run_calibration(
                    spec_path=spec,
                    pre_repo_path=pre,
                    reference_delivery_path=reference,
                    partial_delivery_paths={},
                )


if __name__ == "__main__":
    unittest.main()

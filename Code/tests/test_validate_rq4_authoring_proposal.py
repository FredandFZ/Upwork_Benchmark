from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from Code.validate_rq4_authoring_proposal import (
    ProposalValidationError,
    validate_proposal,
)


PROJECT_ID = "project-test"
TARGET_ID = "project-test_T001"
MESSAGE_ID = 42
PRE_REPO_SHA256 = "a" * 64
MANIFEST_SHA256 = "b" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RQ4AuthoringProposalValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.artifact_root = self.root / "artifacts"
        self.artifact_root.mkdir()
        self.work_item_path = self.root / "work_item.json"
        self.proposal_path = self.root / "proposal.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_work_item(self, status: str) -> dict:
        work_item = {
            "schema_version": "rq4-validator-work-item-v1",
            "project_id": PROJECT_ID,
            "target_id": TARGET_ID,
            "target_message_id": MESSAGE_ID,
            "code_environment": {
                "archive_sha256": PRE_REPO_SHA256,
                "manifest_sha256": MANIFEST_SHA256,
            },
            "observability_triage": {"status": status},
        }
        self._write_json(self.work_item_path, work_item)
        return work_item

    def _upstream(self, role: str, filename: str) -> dict:
        path = self.artifact_root / filename
        self._write_json(path, {"role": role, "proposal_status": "PROPOSED"})
        return {"role": role, "path": filename, "sha256": _sha256(path)}

    def _base_proposal(self, role: str, upstream: list[dict] | None = None) -> dict:
        return {
            "schema_version": "rq4-validator-authoring-proposal-v1",
            "project_id": PROJECT_ID,
            "target_id": TARGET_ID,
            "before_message_id": MESSAGE_ID,
            "author_role": role,
            "proposal_status": "PROPOSED",
            "source_identity": {
                "work_item_sha256": _sha256(self.work_item_path),
                "pre_repo_sha256": PRE_REPO_SHA256,
                "target_manifest_sha256": MANIFEST_SHA256,
                "upstream_proposals": upstream or [],
            },
            "produced_files": [],
            "review_status": {
                "independent_review_state": "NOT_REVIEWED",
                "calibration_status": "NOT_RUN_BY_AUTHOR",
                "eligibility_status": "NOT_DETERMINED_BY_AUTHOR",
            },
            "payload": {},
            "author_declaration": {
                "no_fabricated_execution_results": True,
                "no_calibration_claim": True,
                "no_eligibility_claim": True,
                "no_agent_visible_leakage_written": True,
            },
        }

    def _criteria_payload(self, determination: str) -> dict:
        if determination == "DETERMINISTIC_OBSERVABLE":
            return {
                "observability_triage": {
                    "determination": determination,
                    "rationale": "The local API exposes the requested behavior.",
                    "interfaces_inspected": ["POST /api/items"],
                    "subjective_only": False,
                    "repair_requirements": [],
                },
                "downstream_disposition": "PROCEED_TO_VALIDATOR_AUTHORING",
                "blocker_or_exclusion": None,
                "acceptance_criteria": [
                    {
                        "criterion_id": "AC001",
                        "scope": "TARGET_BEHAVIOR",
                        "statement": "The public API returns the created item.",
                        "gold_requirement_refs": ["REQ_ITEM"],
                        "gold_state_paths": ["attributes.item_creation"],
                        "evidence_message_ids": [MESSAGE_ID],
                        "observables": [
                            {
                                "observable_id": "OBS001",
                                "type": "API",
                                "surface": "POST /api/items",
                                "setup": ["Start the local application."],
                                "actions": [
                                    {
                                        "operation": "HTTP_REQUEST",
                                        "target": "/api/items",
                                        "parameters": {"method": "POST"},
                                    }
                                ],
                                "expected_observations": [
                                    {
                                        "subject": "response.status",
                                        "operator": "EQUALS",
                                        "expected": 201,
                                    }
                                ],
                                "determinism_controls": ["Use an in-memory fixture."],
                            }
                        ],
                        "negative_cases": [],
                    }
                ],
                "coverage_summary": {
                    "affected_gold_state_paths": ["attributes.item_creation"],
                    "covered_affected_gold_state_paths": ["attributes.item_creation"],
                    "preserved_requirement_refs": ["REQ_EXISTING"],
                    "uncovered_items": [],
                },
            }
        if determination != "ENVIRONMENT_REPAIR_REQUIRED":
            raise AssertionError(f"unsupported test determination {determination}")
        return {
            "observability_triage": {
                "determination": determination,
                "rationale": "The snapshot exposes configuration but no behavior API.",
                "interfaces_inspected": ["src/current_state.py"],
                "subjective_only": False,
                "repair_requirements": ["Add a local behavior API."],
            },
            "downstream_disposition": "BLOCK_FOR_ENVIRONMENT_REPAIR",
            "blocker_or_exclusion": {
                "kind": "ENVIRONMENT_REPAIR_BLOCKER",
                "reason_code": "NO_EXECUTABLE_BEHAVIOR_INTERFACE",
                "evidence": ["No callable surface changes repository state."],
                "missing_observables": ["Create-item behavior."],
                "minimum_environment_repairs": ["Expose a deterministic local API."],
                "reentry_condition": "Re-run triage after the API and tests are frozen.",
            },
            "acceptance_criteria": [],
            "coverage_summary": {
                "affected_gold_state_paths": ["attributes.item_creation"],
                "covered_affected_gold_state_paths": [],
                "preserved_requirement_refs": ["REQ_EXISTING"],
                "uncovered_items": [],
            },
        }

    def _validator_payload(self) -> dict:
        return {
            "acceptance_criteria_sha256": "c" * 64,
            "harness": {
                "language": "python",
                "entrypoint": "validate.py",
                "build_command": ["python", "scripts/build.py"],
                "target_test_command": ["python", "validate.py", "target"],
                "regression_command": ["python", "validate.py", "regression"],
                "timeout_seconds": 60,
                "network_policy": "DISABLED",
                "fresh_workspace_required": True,
                "machine_readable_result_path": "result.json",
            },
            "criterion_coverage": [
                {
                    "criterion_id": "AC001",
                    "test_ids": ["test_target_001"],
                    "observable_ids": ["OBS001"],
                }
            ],
            "result_contract": {
                "components": ["BUILD_PASS", "TARGET_TEST_PASS", "REGRESSION_PASS"],
                "final_rule": "BUILD_PASS AND TARGET_TEST_PASS AND REGRESSION_PASS",
                "harness_error_is_agent_failure": False,
            },
            "calibration_contract": {
                "pre_repo_expected": {
                    "build": "PASS",
                    "regression": "PASS",
                    "target_test": "FAIL",
                },
                "reference_expected": {
                    "build": "PASS",
                    "regression": "PASS",
                    "target_test": "PASS",
                },
                "adversarial_expected": "EVERY_PARTIAL_OR_MUTANT_FAILS_TARGET_OR_REGRESSION",
                "actual_results_may_be_written_by_author": False,
            },
            "implementation_independence": {
                "no_llm_judge": True,
                "no_network": True,
                "no_reference_patch_comparison": True,
                "no_gold_mapping_direct_score": True,
                "no_unrequired_internal_structure_assertion": True,
            },
        }

    def _reference_payload(self) -> dict:
        return {
            "isolation": {
                "fresh_pre_repo": True,
                "acceptance_criteria_accessed": False,
                "validator_source_accessed": False,
            },
            "delivery": {
                "archive_path": "reference.zip",
                "archive_sha256": "d" * 64,
                "tree_sha256": "e" * 64,
            },
            "implemented_gold_requirements": ["REQ_ITEM"],
            "expected_calibration_behavior": "EXPECTED_TO_PASS_LATER_MECHANICAL_CALIBRATION",
        }

    def _adversarial_delivery(self, delivery_id: str, kind: str) -> dict:
        return {
            "delivery_id": delivery_id,
            "kind": kind,
            "archive_path": f"{delivery_id}.zip",
            "archive_sha256": "f" * 64,
            "intentionally_satisfied_criteria": [],
            "intentionally_violated_criteria": ["AC001"],
            "fault_model": "The target behavior is intentionally omitted.",
            "expected_later_result": "TARGET_TEST_FAIL",
        }

    def _red_team_payload(self) -> dict:
        return {
            "acceptance_criteria_sha256": "c" * 64,
            "validator_proposal_sha256": "d" * 64,
            "partial_deliveries": [self._adversarial_delivery("partial-001", "PARTIAL")],
            "mutant_deliveries": [self._adversarial_delivery("mutant-001", "MUTANT")],
            "leakage_review": {
                "scopes": ["PRE_REPO_FUTURE_STATE"],
                "required_static_scans": ["FUTURE_STATE_VALUES"],
                "preliminary_outcome": "NO_FINDINGS_PROPOSED",
                "findings": [],
            },
        }

    def _write_and_validate(self, proposal: dict) -> dict:
        self._write_json(self.proposal_path, proposal)
        return validate_proposal(
            self.proposal_path,
            self.work_item_path,
            self.artifact_root,
        )

    def test_accepts_eligible_criteria_proposal(self):
        self._write_work_item("ELIGIBLE_FOR_VALIDATOR_AUTHORING")
        proposal = self._base_proposal("CRITERIA_AUTHOR")
        proposal["payload"] = self._criteria_payload("DETERMINISTIC_OBSERVABLE")

        result = self._write_and_validate(proposal)

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["author_role"], "CRITERIA_AUTHOR")

    def test_accepts_environment_repair_criteria_proposal_without_validator(self):
        self._write_work_item("ENVIRONMENT_REPAIR_REQUIRED")
        proposal = self._base_proposal("CRITERIA_AUTHOR")
        proposal["payload"] = self._criteria_payload("ENVIRONMENT_REPAIR_REQUIRED")

        result = self._write_and_validate(proposal)

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(proposal["payload"]["acceptance_criteria"], [])

    def test_rejects_stale_work_item_hash(self):
        self._write_work_item("ELIGIBLE_FOR_VALIDATOR_AUTHORING")
        proposal = self._base_proposal("CRITERIA_AUTHOR")
        proposal["payload"] = self._criteria_payload("DETERMINISTIC_OBSERVABLE")
        proposal["source_identity"]["work_item_sha256"] = "0" * 64

        with self.assertRaisesRegex(ProposalValidationError, "work item hash is stale"):
            self._write_and_validate(proposal)

    def test_rejects_unsafe_produced_file_path(self):
        self._write_work_item("ELIGIBLE_FOR_VALIDATOR_AUTHORING")
        proposal = self._base_proposal("CRITERIA_AUTHOR")
        proposal["payload"] = self._criteria_payload("DETERMINISTIC_OBSERVABLE")
        proposal["produced_files"] = [
            {
                "path": "../escape.txt",
                "sha256": "0" * 64,
                "purpose": "escape attempt",
                "researcher_only": True,
            }
        ]

        with self.assertRaisesRegex(ProposalValidationError, "unsafe produced file path"):
            self._write_and_validate(proposal)

    def test_rejects_role_attempting_to_read_forbidden_upstream(self):
        self._write_work_item("ELIGIBLE_FOR_VALIDATOR_AUTHORING")
        forbidden = self._upstream("VALIDATOR_AUTHOR", "validator-proposal.json")
        proposal = self._base_proposal("REFERENCE_AUTHOR", [forbidden])
        proposal["payload"] = self._reference_payload()

        with self.assertRaisesRegex(ProposalValidationError, "array is too long"):
            self._write_and_validate(proposal)

    def test_blocked_work_items_cannot_run_downstream_roles(self):
        blocked_statuses = (
            "ENVIRONMENT_REPAIR_REQUIRED",
            "NO_DETERMINISTIC_OBSERVABLE",
            "SUBJECTIVE_REVIEW_REQUIRED",
        )
        for status in blocked_statuses:
            for role in (
                "VALIDATOR_AUTHOR",
                "REFERENCE_AUTHOR",
                "RED_TEAM_LEAKAGE_AUDITOR",
            ):
                with self.subTest(status=status, role=role):
                    self._write_work_item(status)
                    if role == "VALIDATOR_AUTHOR":
                        upstream = [self._upstream("CRITERIA_AUTHOR", "criteria.json")]
                        payload = self._validator_payload()
                    elif role == "REFERENCE_AUTHOR":
                        upstream = []
                        payload = self._reference_payload()
                    else:
                        upstream = [
                            self._upstream("CRITERIA_AUTHOR", "criteria.json"),
                            self._upstream("VALIDATOR_AUTHOR", "validator.json"),
                        ]
                        payload = self._red_team_payload()
                    proposal = self._base_proposal(role, upstream)
                    proposal["payload"] = payload

                    with self.assertRaisesRegex(
                        ProposalValidationError,
                        rf"{role} cannot run while work item status is {status}",
                    ):
                        self._write_and_validate(proposal)

    def test_rejects_stale_upstream_proposal_hash(self):
        self._write_work_item("ELIGIBLE_FOR_VALIDATOR_AUTHORING")
        upstream = self._upstream("CRITERIA_AUTHOR", "criteria.json")
        stale = copy.deepcopy(upstream)
        stale["sha256"] = "0" * 64
        proposal = self._base_proposal("VALIDATOR_AUTHOR", [stale])
        proposal["payload"] = self._validator_payload()

        with self.assertRaisesRegex(ProposalValidationError, "upstream proposal is missing or stale"):
            self._write_and_validate(proposal)


if __name__ == "__main__":
    unittest.main()

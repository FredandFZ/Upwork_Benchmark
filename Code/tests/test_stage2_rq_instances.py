from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from Code.stage2.rq_instances import (
    RQInstanceError,
    build_project_manifest,
    build_rq_indexes,
    build_rq_instances,
    difficulty_from_turns,
    validate_rq_instance,
)


def _messages() -> dict:
    return {
        "project_id": "P1",
        "project_title": "Synthetic project",
        "messages": [
            {
                "message_id": 10,
                "created_ts": "2026-01-01 00:00:00",
                "speaker": "client",
                "text": "Use blue buttons.",
                "milestone": None,
                "original_index": 0,
                "sender_id": "must-not-leak",
            },
            {
                "message_id": 20,
                "created_ts": "2026-01-01 00:01:00",
                "speaker": "freelancer",
                "text": "Implemented something unrelated.",
                "milestone": None,
                "original_index": 1,
            },
            {
                "message_id": 30,
                "created_ts": "2026-01-01 00:02:00",
                "speaker": "client",
                "text": "Unrelated project discussion.",
                "milestone": None,
                "original_index": 2,
            },
            {
                "message_id": 40,
                "created_ts": "2026-01-01 00:03:00",
                "speaker": "client",
                "text": "Maybe make the button green, and add a report.",
                "milestone": None,
                "original_index": 3,
            },
        ],
    }


def _state_graph() -> dict:
    return {
        "schema_version": "requirement-state-graph-v1",
        "project_id": "P1",
        "requirement_graphs": [
            {
                "graph_id": "REQ_BUTTON_GRAPH",
                "requirement_id": "REQ_BUTTON",
                "title": "Button colour",
                "family_id": "UI",
                "nodes": [
                    {
                        "state_id": "REQ_BUTTON_S001",
                        "attributes": {"colour": "blue"},
                        "scope": {
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["FRONTEND"],
                            "contexts": ["BUTTON"],
                        },
                        "lifecycle_status": "ACTIVE",
                        "ambiguity": None,
                        "execution": None,
                        "supporting_event_ids": ["REQ_BUTTON_E001"],
                    },
                    {
                        "state_id": "REQ_BUTTON_S002",
                        "attributes": {"colour": "blue"},
                        "scope": {
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["FRONTEND"],
                            "contexts": ["BUTTON"],
                        },
                        "lifecycle_status": "ACTIVE",
                        "ambiguity": {
                            "REQ_BUTTON_E002": {
                                "status": "OPEN",
                                "dimension": "VALUE",
                                "description": "Maybe does not establish a final colour.",
                                "source_event_id": "REQ_BUTTON_E002",
                            }
                        },
                        "execution": None,
                        "supporting_event_ids": [
                            "REQ_BUTTON_E001",
                            "REQ_BUTTON_E002",
                        ],
                    },
                ],
                "edges": [
                    {
                        "from_state_id": None,
                        "to_state_id": "REQ_BUTTON_S001",
                        "event_id": "REQ_BUTTON_E001",
                        "event_type": "INTRODUCE",
                        "source_message_id": 10,
                        "value_removals": None,
                    },
                    {
                        "from_state_id": "REQ_BUTTON_S001",
                        "to_state_id": "REQ_BUTTON_S002",
                        "event_id": "REQ_BUTTON_E002",
                        "event_type": "AMBIGUOUS",
                        "source_message_id": 40,
                        "value_removals": None,
                    },
                ],
            },
            {
                "graph_id": "REQ_REPORT_GRAPH",
                "requirement_id": "REQ_REPORT",
                "title": "Report",
                "family_id": None,
                "nodes": [
                    {
                        "state_id": "REQ_REPORT_S001",
                        "attributes": {"enabled": True},
                        "scope": {
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["BACKEND"],
                            "contexts": ["REPORTING"],
                        },
                        "lifecycle_status": "ACTIVE",
                        "ambiguity": None,
                        "execution": None,
                        "supporting_event_ids": ["REQ_REPORT_E001"],
                    }
                ],
                "edges": [
                    {
                        "from_state_id": None,
                        "to_state_id": "REQ_REPORT_S001",
                        "event_id": "REQ_REPORT_E001",
                        "event_type": "INTRODUCE",
                        "source_message_id": 40,
                        "value_removals": None,
                    }
                ],
            },
        ],
    }


def _gold(*, turns: int = 3, rq_targets=None) -> dict:
    return {
        "schema_version": "task-gold-v2",
        "project_id": "P1",
        "task_gold_states": [
            {
                "task_gold_id": "P1_T001_GOLD",
                "target_id": "P1_T001",
                "candidate_id": "P1_CANDIDATE_MSG_40",
                "conversation_turn_index": 4,
                "history_turn_count": turns,
                "selection_source": "TEST",
                "primary_rq_targets": rq_targets
                or ["RQ1", "RQ2", "RQ3", "RQ4"],
                "target_task": {
                    "source_message_id": 40,
                    "speaker": "client",
                    "text": "Maybe make the button green, and add a report.",
                },
                "task_event_ids": ["REQ_BUTTON_E002", "REQ_REPORT_E001"],
                "affected_requirement_ids": ["REQ_BUTTON", "REQ_REPORT"],
                "preserved_requirement_ids": [],
                "pre_task_gold_state": {
                    "boundary": {"before_message_id": 40},
                    "requirement_states": [
                        {
                            "requirement_id": "REQ_BUTTON",
                            "state_id": "REQ_BUTTON_S001",
                        }
                    ],
                },
                "post_task_gold_state": {
                    "boundary": {"through_message_id": 40},
                    "requirement_states": [
                        {
                            "requirement_id": "REQ_BUTTON",
                            "state_id": "REQ_BUTTON_S002",
                        },
                        {
                            "requirement_id": "REQ_REPORT",
                            "state_id": "REQ_REPORT_S001",
                        },
                    ],
                },
            }
        ],
    }


def _write_code_environment(root: Path, *, unsafe: bool = False) -> Path:
    target_dir = root / "targets" / "T001_before_40"
    target_dir.mkdir(parents=True)
    archive_path = target_dir / "pre_repo.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../escape.txt" if unsafe else "src/app.js", "export {};")
    manifest = {
        "target_id": "P1_T001",
        "before_message_id": 40,
        "repository_classification": "simulated-executable-pre-state",
        "contract_layer": "simulated-state-model",
        "web_api_layer": "simulated",
        "active_code_feature_count": 1,
        "tracked_requirement_count": 1,
        "temporal_fixture": None,
        "requirements_to_code": [
            {
                "requirement_id": "REQ_BUTTON",
                "state_id": "REQ_BUTTON_S001",
                "implementation_mode": "simulated_executable",
                "code_paths": ["src/app.js"],
            }
        ],
        "target_event_ids": ["REQ_BUTTON_E002", "REQ_REPORT_E001"],
        "target_event_types": ["AMBIGUOUS", "INTRODUCE"],
        "target_summary": "Maybe make the button green, and add a report.",
        "pre_state_verified_against_gold": True,
        "post_state_verified_against_gold": True,
        "repo_sha256": "a" * 64,
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "target_index.json").write_text(
        json.dumps([manifest]), encoding="utf-8"
    )
    (reports_dir / "validation_report.json").write_text(
        json.dumps({"overall": "pass"}), encoding="utf-8"
    )
    return root


class RQInstanceTests(unittest.TestCase):
    def test_builds_all_four_views_and_preserves_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            code_environment = _write_code_environment(Path(directory))
            collections = build_rq_instances(
                _gold(),
                _state_graph(),
                _messages(),
                code_environment_dir=code_environment,
            )

        self.assertEqual({rq: len(rows) for rq, rows in collections.items()}, {
            "RQ1": 1,
            "RQ2": 1,
            "RQ3": 1,
            "RQ4": 1,
        })
        for rq_id, rows in collections.items():
            instance = rows[0]
            self.assertEqual(instance["turns"], 3)
            self.assertEqual(instance["history_turn_count"], 3)
            self.assertEqual(instance["difficulty"], "SHORT")
            self.assertEqual(validate_rq_instance(instance), [], rq_id)
            self.assertEqual(
                [row["message_id"] for row in instance["history_pool"]["messages"]],
                [10, 20, 30],
            )
            self.assertNotIn("sender_id", instance["history_pool"]["messages"][0])

        rq1 = collections["RQ1"][0]
        self.assertEqual(
            rq1["construction_gold"]["relevant_requirement_ids"], ["REQ_BUTTON"]
        )
        self.assertEqual(
            rq1["construction_gold"]["new_requirement_ids"], ["REQ_REPORT"]
        )
        self.assertEqual(
            rq1["construction_gold"]["evidence"]["REQ_BUTTON"][
                "trajectory_event_ids"
            ],
            ["REQ_BUTTON_E001"],
        )
        self.assertEqual(
            rq1["condition_inputs"]["C3"]["history_message_ids"], [10]
        )
        self.assertFalse(rq1["condition_inputs"]["C3"]["available"])

        rq2 = collections["RQ2"][0]
        self.assertEqual(
            rq2["construction_gold"]["states"]["REQ_BUTTON"]["attributes"],
            {"colour": "blue"},
        )
        rq3 = collections["RQ3"][0]
        self.assertEqual(
            rq3["construction_gold"]["project_decision_candidate"]["value"],
            "CLARIFY",
        )
        self.assertEqual(
            rq3["construction_gold"]["blocking_ambiguity_candidates"][0][
                "ambiguity_event_id"
            ],
            "REQ_BUTTON_E002",
        )
        rq4 = collections["RQ4"][0]
        self.assertFalse(
            rq4["code_environment"]["extracted_during_instance_construction"]
        )
        self.assertEqual(
            rq4["construction_gold"]["requirement_action_candidates"]["REQ_REPORT"][
                "action_candidate"
            ],
            "IMPLEMENT",
        )
        self.assertEqual(len(rq4["code_environment"]["archive_sha256"]), 64)

    def test_primary_rq_targets_control_materialization(self):
        collections = build_rq_instances(
            _gold(rq_targets=["RQ2"]), _state_graph(), _messages()
        )
        counts = [len(collections[rq]) for rq in ("RQ1", "RQ2", "RQ3", "RQ4")]
        self.assertEqual(counts, [0, 1, 0, 0])

    def test_turn_mismatch_is_rejected(self):
        with self.assertRaisesRegex(RQInstanceError, "history_turn_count"):
            build_rq_instances(
                _gold(turns=2, rq_targets=["RQ2"]), _state_graph(), _messages()
            )

    def test_unsafe_archive_member_is_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            code_environment = _write_code_environment(Path(directory), unsafe=True)
            with self.assertRaisesRegex(RQInstanceError, "unsafe path"):
                build_rq_instances(
                    _gold(rq_targets=["RQ4"]),
                    _state_graph(),
                    _messages(),
                    code_environment_dir=code_environment,
                )
            self.assertFalse((Path(directory).parent / "escape.txt").exists())

    def test_failed_code_environment_validation_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            code_environment = _write_code_environment(Path(directory))
            validation_path = code_environment / "reports" / "validation_report.json"
            validation_path.write_text(
                json.dumps({"overall": "fail"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(RQInstanceError, "did not pass"):
                build_rq_instances(
                    _gold(rq_targets=["RQ4"]),
                    _state_graph(),
                    _messages(),
                    code_environment_dir=code_environment,
                )

    def test_indexes_manifest_and_difficulty_boundaries(self):
        self.assertEqual(difficulty_from_turns(0), "SHORT")
        self.assertEqual(difficulty_from_turns(25), "SHORT")
        self.assertEqual(difficulty_from_turns(26), "MEDIUM")
        self.assertEqual(difficulty_from_turns(50), "MEDIUM")
        self.assertEqual(difficulty_from_turns(51), "LONG")
        collections = build_rq_instances(
            _gold(rq_targets=["RQ2"]), _state_graph(), _messages()
        )
        indexes = build_rq_indexes(collections)
        manifest = build_project_manifest(
            collections, indexes, project_id="P1"
        )
        self.assertEqual(indexes["RQ2"]["instance_count"], 1)
        self.assertEqual(indexes["RQ2"]["instances"][0]["turns"], 3)
        self.assertEqual(manifest["rq_counts"]["RQ2"], 1)
        self.assertEqual(manifest["total_instance_count"], 1)


if __name__ == "__main__":
    unittest.main()

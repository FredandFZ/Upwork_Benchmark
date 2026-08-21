from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from Code.stage1.assembler import assemble_stage1_annotation
from Code.stage1.config import PipelineConfig, ProjectSource
from Code.stage1.context import requirement_context
from Code.stage1.filtering import filter_short_requirements
from Code.stage1.pipeline import Stage1Pipeline
from Code.stage1.patching import apply_audit_patches, apply_verification, has_valid_requirement_ids
from Code.stage1.preprocessing import preprocess_project
from Code.stage1.storage import sha256_text
from Code.stage1.validation import (
    Stage1ValidationError,
    canonicalize_event_source_texts,
    validate_intermediate_events,
    validate_stage1_annotation,
)


def normalized_fixture() -> dict[str, Any]:
    return {
        "project_id": "P1",
        "project_title": "Test",
        "project_metadata": {},
        "source_chat_path": "chat_messages.json",
        "messages": [
            {
                "message_id": 1,
                "created_ts": "2026-01-01 10:00:00",
                "speaker": "client",
                "text": "Make the button blue.",
                "milestone": None,
                "original_index": 0,
                "sender_id": "c1",
            }
        ],
    }


def valid_annotation() -> dict[str, Any]:
    normalized = normalized_fixture()
    inventory = {
        "sessions": [{"session_id": "S1", "start": "2026-01-01", "end": "2026-01-01", "milestone": None}],
        "requirement_families": [],
        "requirements": [{"requirement_id": "REQ_BUTTON_COLOR", "title": "Button color", "family_id": None}],
    }
    events = {
        "REQ_BUTTON_COLOR": [
            {
                "source_message": {"message_id": 1, "speaker": "client", "text": "Make the button blue."},
                "event_type": "INTRODUCE",
                "value_updates": {"color": "blue"},
                "scope_updates": {
                    "persistence": "PROJECT_PERSISTENT",
                    "components": ["FRONTEND"],
                    "contexts": ["BUTTON_UI"],
                },
                "ambiguity": None,
                "execution": None,
            }
        ]
    }
    return assemble_stage1_annotation(normalized, inventory, events)


class PreprocessingTests(unittest.TestCase):
    def _project(self, root: Path, messages: list[dict[str, Any]]) -> ProjectSource:
        project_dir = root / "P1"
        project_dir.mkdir()
        chat = project_dir / "chat_messages.json"
        chat.write_text(json.dumps(messages), encoding="utf-8")
        return ProjectSource("P1", project_dir, chat, root / "out.json", root / "run")

    def test_missing_ids_are_deterministic_and_sort_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self._project(
                Path(temp),
                [
                    {"created_ts": "2026-01-02", "message": "later", "message_user_type": "client"},
                    {"created_ts": "2026-01-01", "message": "first tie", "message_user_type": "freelancer"},
                    {"created_ts": "2026-01-01", "message": "second tie", "message_user_type": "client"},
                ],
            )
            first = preprocess_project(project)
            second = preprocess_project(project)
        self.assertEqual(first, second)
        self.assertEqual([item["message_id"] for item in first["messages"]], [1, 2, 3])
        self.assertEqual([item["text"] for item in first["messages"]], ["first tie", "second tie", "later"])

    def test_existing_ids_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self._project(
                Path(temp),
                [
                    {
                        "message_id": "stable-b",
                        "created_ts": "2026-01-02",
                        "message": "b",
                        "message_user_type": "client",
                    },
                    {
                        "message_id": "stable-a",
                        "created_ts": "2026-01-01",
                        "message": "a",
                        "message_user_type": "freelancer",
                    },
                ],
            )
            normalized = preprocess_project(project)
        self.assertEqual([item["message_id"] for item in normalized["messages"]], ["stable-a", "stable-b"])


class AssemblyAndValidationTests(unittest.TestCase):
    def test_event_ids_are_generated_contiguously(self) -> None:
        normalized = normalized_fixture()
        inventory = {
            "sessions": [],
            "requirement_families": [],
            "requirements": [{"requirement_id": "REQ_X", "title": "X", "family_id": None}],
        }
        event = {
            "source_message": {"message_id": 1, "speaker": "client", "text": "Make the button blue."},
            "event_type": "MODIFY",
            "value_updates": {"x": 1},
            "scope_updates": None,
            "ambiguity": None,
            "execution": None,
        }
        annotation = assemble_stage1_annotation(normalized, inventory, {"REQ_X": [event, event, event]})
        self.assertEqual(
            [item["event_id"] for item in annotation["requirements"][0]["events"]],
            ["REQ_X_E001", "REQ_X_E002", "REQ_X_E003"],
        )

    def test_paraphrased_source_text_fails(self) -> None:
        annotation = valid_annotation()
        annotation["requirements"][0]["events"][0]["source_message"]["text"] = "Make it blue."
        with self.assertRaisesRegex(Stage1ValidationError, "source text"):
            validate_stage1_annotation(annotation, normalized_fixture())

    def test_source_text_is_restored_when_id_and_speaker_match(self) -> None:
        normalized = normalized_fixture()
        normalized["messages"][0]["text"] = "I&#39;m ready."
        events = [
            {
                "source_message": {"message_id": 1, "speaker": "client", "text": "I'm ready."},
                "event_type": "MODIFY",
                "value_updates": {"ready": True},
                "scope_updates": None,
                "ambiguity": None,
                "execution": None,
            }
        ]
        self.assertEqual(canonicalize_event_source_texts(events, normalized), 1)
        self.assertEqual(events[0]["source_message"]["text"], "I&#39;m ready.")
        validate_intermediate_events(events, normalized)

    def test_invalid_family_fails(self) -> None:
        annotation = valid_annotation()
        annotation["requirements"][0]["family_id"] = "UNKNOWN_FAMILY"
        with self.assertRaisesRegex(Stage1ValidationError, "unknown family"):
            validate_stage1_annotation(annotation, normalized_fixture())

    def test_invalid_event_type_fails(self) -> None:
        annotation = valid_annotation()
        annotation["requirements"][0]["events"][0]["event_type"] = "FIX"
        with self.assertRaisesRegex(Stage1ValidationError, "invalid event_type"):
            validate_stage1_annotation(annotation, normalized_fixture())

    def test_runtime_status_mismatch_fails(self) -> None:
        annotation = valid_annotation()
        event = annotation["requirements"][0]["events"][0]
        event.update(
            {
                "event_type": "RUNTIME_FAILURE",
                "value_updates": None,
                "scope_updates": None,
                "ambiguity": None,
                "execution": {"status": "CLAIMED_WORKING", "observed_behavior": "wrong"},
            }
        )
        with self.assertRaisesRegex(Stage1ValidationError, "execution.status"):
            validate_stage1_annotation(annotation, normalized_fixture())


class CostControlTests(unittest.TestCase):
    def test_target_only_verification_reuses_non_target_legacy_hash(self) -> None:
        self.assertFalse(
            Stage1Pipeline._verification_hash_requires_refresh(
                meta_matches=False,
                target_only=True,
                requirement_id="REQ_OTHER",
                force_ids={"REQ_AAVE_PRIZE_POOL_YIELD"},
            )
        )
        self.assertTrue(
            Stage1Pipeline._verification_hash_requires_refresh(
                meta_matches=False,
                target_only=False,
                requirement_id="REQ_OTHER",
                force_ids={"REQ_AAVE_PRIZE_POOL_YIELD"},
            )
        )

    def test_short_requirements_are_removed_before_downstream_stages(self) -> None:
        inventory = {
            "sessions": [],
            "requirement_families": [{"family_id": "F", "title": "Family"}],
            "requirements": [
                {"requirement_id": "REQ_SHORT", "title": "Short", "family_id": "F"},
                {"requirement_id": "REQ_LONG", "title": "Long", "family_id": "F"},
            ],
        }
        events = {"REQ_SHORT": [{}, {}], "REQ_LONG": [{}, {}, {}]}
        filtered_inventory, filtered_events, discarded = filter_short_requirements(
            inventory, events, 3, "EVENT_EXTRACTION"
        )
        self.assertEqual([item["requirement_id"] for item in filtered_inventory["requirements"]], ["REQ_LONG"])
        self.assertEqual(set(filtered_events), {"REQ_LONG"})
        self.assertEqual(discarded[0]["event_count"], 2)
        self.assertIsNone(filtered_inventory["requirements"][0]["family_id"])
        self.assertEqual(filtered_inventory["requirement_families"], [])

    def test_requirement_context_is_bounded_and_keeps_lifecycle_ends(self) -> None:
        messages = [
            {
                "message_id": number,
                "speaker": "client",
                "text": f"Button color evidence {number}",
            }
            for number in range(1, 301)
        ]
        normalized = {"messages": messages}
        requirement = {
            "requirement_id": "REQ_BUTTON_COLOR",
            "title": "Button Color",
            "definition": "The button color changes over time.",
            "anchor_message_ids": [1, 300],
            "scope_hypothesis": {},
        }
        evidence = {
            "candidates": [
                {
                    "message_id": number,
                    "topic_hints": ["button color"],
                    "context_message_ids": [],
                    "confidence": "HIGH",
                }
                for number in range(1, 301)
            ]
        }
        selected, candidates = requirement_context(
            normalized, evidence, {"requirements": [requirement]}, requirement, "filtered", 2, 20
        )
        selected_ids = {item["message_id"] for item in selected}
        self.assertLessEqual(len(selected), 20)
        self.assertIn(1, selected_ids)
        self.assertIn(300, selected_ids)
        self.assertLessEqual(len(candidates), 80)


class PatchingTests(unittest.TestCase):
    def test_only_high_confidence_audit_patch_is_applied(self) -> None:
        inventory = {
            "requirements": [{"requirement_id": "REQ_A", "title": "A", "family_id": None}],
            "requirement_families": [],
            "sessions": [],
        }
        patches = [
            {
                "operation": "ADD_REQUIREMENT",
                "targets": {},
                "replacement": {"requirement_id": "REQ_B", "title": "B", "family_id": None},
                "evidence_message_ids": [1],
                "decision_note": "Supported.",
                "confidence": "HIGH",
            },
            {
                "operation": "DELETE_REQUIREMENT",
                "targets": {"requirement_id": "REQ_A"},
                "replacement": None,
                "evidence_message_ids": [1],
                "decision_note": "Uncertain.",
                "confidence": "LOW",
            },
        ]
        result = apply_audit_patches(inventory, {"REQ_A": []}, patches)
        self.assertEqual(
            {item["requirement_id"] for item in result.inventory["requirements"]},
            {"REQ_A", "REQ_B"},
        )
        self.assertEqual(len(result.human_review), 1)

    def test_split_reuses_existing_requirement_ids_without_duplicates(self) -> None:
        inventory = {
            "requirements": [
                {
                    "requirement_id": "REQ_BROAD",
                    "title": "Broad",
                    "family_id": None,
                    "definition": "Broad behavior.",
                },
                {
                    "requirement_id": "REQ_EXISTING",
                    "title": "Existing",
                    "family_id": None,
                    "definition": "Existing canonical behavior.",
                },
            ],
            "requirement_families": [],
            "sessions": [],
        }
        patches = [
            {
                "operation": "SPLIT_REQUIREMENT",
                "targets": {"requirement_id": "REQ_BROAD"},
                "replacement": {
                    "requirements": [
                        {"requirement_id": "REQ_BROAD", "title": "Narrowed broad", "family_id": None},
                        {"requirement_id": "REQ_EXISTING", "title": "Existing", "family_id": None},
                        {"requirement_id": "REQ_NEW", "title": "New", "family_id": None},
                    ]
                },
                "evidence_message_ids": [1],
                "decision_note": "Split into independently evolving behaviors.",
                "confidence": "HIGH",
            }
        ]

        result = apply_audit_patches(
            inventory,
            {"REQ_BROAD": [{"event_type": "INTRODUCE"}], "REQ_EXISTING": [{"event_type": "MODIFY"}]},
            patches,
        )

        requirement_ids = [item["requirement_id"] for item in result.inventory["requirements"]]
        self.assertEqual(set(requirement_ids), {"REQ_BROAD", "REQ_EXISTING", "REQ_NEW"})
        self.assertEqual(len(requirement_ids), len(set(requirement_ids)))
        existing = next(
            item for item in result.inventory["requirements"] if item["requirement_id"] == "REQ_EXISTING"
        )
        self.assertEqual(existing["definition"], "Existing canonical behavior.")
        self.assertEqual(result.events, {"REQ_BROAD": [], "REQ_EXISTING": [], "REQ_NEW": []})
        self.assertEqual(result.affected_requirements, {"REQ_BROAD", "REQ_EXISTING", "REQ_NEW"})
        self.assertEqual(result.applied_count, 1)
        self.assertTrue(has_valid_requirement_ids(result.inventory))

    def test_split_with_duplicate_part_ids_is_rejected_atomically(self) -> None:
        inventory = {
            "requirements": [{"requirement_id": "REQ_A", "title": "A", "family_id": None}],
            "requirement_families": [],
            "sessions": [],
        }
        events = {"REQ_A": [{"event_type": "INTRODUCE"}]}
        patches = [
            {
                "operation": "SPLIT_REQUIREMENT",
                "targets": {"requirement_id": "REQ_A"},
                "replacement": {
                    "requirements": [
                        {"requirement_id": "REQ_PART", "title": "Part 1", "family_id": None},
                        {"requirement_id": "REQ_PART", "title": "Part 2", "family_id": None},
                    ]
                },
                "evidence_message_ids": [1],
                "decision_note": "Invalid duplicate split.",
                "confidence": "HIGH",
            }
        ]

        result = apply_audit_patches(inventory, events, patches)

        self.assertEqual(result.inventory, inventory)
        self.assertEqual(result.events, events)
        self.assertEqual(result.applied_count, 0)
        self.assertEqual(len(result.human_review), 1)
        self.assertIn("part IDs must be unique", result.human_review[0]["application_error"])

    def test_merge_into_existing_requirement_id_does_not_duplicate_destination(self) -> None:
        inventory = {
            "requirements": [
                {"requirement_id": "REQ_A", "title": "A", "family_id": None},
                {"requirement_id": "REQ_B", "title": "B", "family_id": None},
                {
                    "requirement_id": "REQ_CANONICAL",
                    "title": "Canonical",
                    "family_id": None,
                    "definition": "Preserved definition.",
                },
            ],
            "requirement_families": [],
            "sessions": [],
        }
        patches = [
            {
                "operation": "MERGE_REQUIREMENTS",
                "targets": {"requirement_ids": ["REQ_A", "REQ_B"]},
                "replacement": {
                    "requirement_id": "REQ_CANONICAL",
                    "title": "Canonical merged behavior",
                    "family_id": None,
                },
                "evidence_message_ids": [1],
                "decision_note": "Merge duplicates into the stable canonical Requirement.",
                "confidence": "HIGH",
            }
        ]

        result = apply_audit_patches(
            inventory,
            {"REQ_A": [], "REQ_B": [], "REQ_CANONICAL": [{"event_type": "INTRODUCE"}]},
            patches,
        )

        self.assertEqual(len(result.inventory["requirements"]), 1)
        merged = result.inventory["requirements"][0]
        self.assertEqual(merged["requirement_id"], "REQ_CANONICAL")
        self.assertEqual(merged["definition"], "Preserved definition.")
        self.assertEqual(result.events, {"REQ_CANONICAL": []})
        self.assertTrue(has_valid_requirement_ids(result.inventory))

    def test_verifier_can_delete_first_duplicate_occurrence(self) -> None:
        event = {
            "source_message": {"message_id": 1, "speaker": "client", "text": "Make the button blue."},
            "supporting_message_ids": [],
            "event_type": "MODIFY",
            "value_updates": {"color": "blue"},
            "scope_updates": None,
            "ambiguity": None,
            "execution": None,
        }
        verification = {
            "requirement_id": "REQ_X",
            "verdicts": [
                {
                    "event_locator": {"message_id": 1, "event_type": "MODIFY", "occurrence": 1},
                    "verdict": "DELETE",
                },
                {
                    "event_locator": {"message_id": 1, "event_type": "MODIFY", "occurrence": 2},
                    "verdict": "KEEP",
                },
            ],
            "missing_event_candidates": [],
        }
        updated, counts, _ = apply_verification([event, event], verification)
        self.assertEqual(len(updated), 1)
        self.assertEqual(counts["deletions"], 1)

    def test_aave_message_192_delete_verdict_is_applied(self) -> None:
        events = [
            {
                "source_message": {"message_id": 156, "speaker": "client", "text": "Use Aave."},
                "supporting_message_ids": [],
                "event_type": "INTRODUCE",
                "value_updates": {"provider": "Aave"},
                "scope_updates": None,
                "ambiguity": None,
                "execution": None,
            },
            {
                "source_message": {"message_id": 192, "speaker": "client", "text": "cool. Other work follows."},
                "supporting_message_ids": [190, 191],
                "event_type": "REMOVE",
                "value_updates": None,
                "scope_updates": None,
                "ambiguity": None,
                "execution": None,
            },
        ]
        verification = {
            "requirement_id": "REQ_AAVE_PRIZE_POOL_YIELD",
            "verdicts": [
                {
                    "event_locator": {"message_id": 156, "event_type": "INTRODUCE", "occurrence": 1},
                    "verdict": "KEEP",
                },
                {
                    "event_locator": {"message_id": 192, "event_type": "REMOVE", "occurrence": 1},
                    "verdict": "DELETE",
                    "replacement": None,
                },
            ],
            "missing_event_candidates": [],
        }
        updated, counts, _ = apply_verification(events, verification)
        self.assertEqual([event["source_message"]["message_id"] for event in updated], [156])
        self.assertEqual(counts, {"edits": 0, "deletions": 1})


class FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.audit_user_messages: list[str] = []
        self.verification_user_messages: list[str] = []

    async def call(self, **kwargs: Any) -> dict[str, Any]:
        mode = kwargs["run_mode"]
        target = kwargs.get("target_requirement")
        self.calls.append((mode, target))
        if mode == "EVIDENCE_SCAN":
            result = {
                "run_mode": mode,
                "candidates": [
                    {
                        "message_id": 1,
                        "evidence_tags": ["REQUIREMENT_INTRODUCTION"],
                        "topic_hints": ["button color"],
                        "context_message_ids": [],
                        "confidence": "HIGH",
                    }
                ],
            }
        elif mode == "REQUIREMENT_DISCOVERY":
            result = {
                "run_mode": mode,
                "sessions": [
                    {
                        "session_id": "S1",
                        "start": "2026-01-01",
                        "end": "2026-01-01",
                        "milestone": None,
                        "phase_label": "UI work",
                    }
                ],
                "requirement_families": [],
                "requirements": [
                    {
                        "requirement_id": "REQ_BUTTON_COLOR",
                        "title": "Button color",
                        "family_id": None,
                        "definition": "The requested button color.",
                        "anchor_message_ids": [1],
                        "scope_hypothesis": {
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["FRONTEND"],
                            "contexts": ["BUTTON_UI"],
                        },
                        "boundary_note": "Independent UI behavior.",
                        "confidence": "HIGH",
                    }
                ],
                "unresolved_candidates": [],
            }
        elif mode == "EVENT_EXTRACTION":
            result = {
                "run_mode": mode,
                "requirement_id": target,
                "events": [
                    {
                        "source_message": {
                            "message_id": 1,
                            "speaker": "client",
                            "text": "Make the button blue.",
                        },
                        "supporting_message_ids": [],
                        "event_type": "INTRODUCE",
                        "value_updates": {"color": "blue"},
                        "scope_updates": {
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["FRONTEND"],
                            "contexts": ["BUTTON_UI"],
                        },
                        "ambiguity": None,
                        "execution": None,
                    }
                ],
                "routing_warnings": [],
                "missing_requirement_candidates": [],
            }
        elif mode == "CONSISTENCY_AUDIT":
            self.audit_user_messages.append(kwargs["messages"][1]["content"])
            result = {
                "run_mode": mode,
                "patches": [
                    {
                        "operation": "HUMAN_REVIEW",
                        "targets": {
                            "requirement_id": "REQ_BUTTON_COLOR",
                            "event_locator": {
                                "message_id": 1,
                                "event_type": "INTRODUCE",
                                "occurrence": 1,
                            },
                        },
                        "replacement": None,
                        "evidence_message_ids": [1],
                        "decision_note": "Confirm that the source entails this target.",
                        "confidence": "LOW",
                    }
                ],
            }
        elif mode == "EVENT_VERIFICATION":
            self.verification_user_messages.append(kwargs["messages"][1]["content"])
            result = {
                "run_mode": mode,
                "requirement_id": target,
                "verdicts": [
                    {
                        "event_locator": {"message_id": 1, "event_type": "INTRODUCE", "occurrence": 1},
                        "verdict": "KEEP",
                        "replacement": None,
                        "evidence_message_ids": [1],
                        "decision_note": "Supported by the source.",
                        "confidence": "HIGH",
                    }
                ],
                "missing_event_candidates": [],
            }
        else:
            raise AssertionError(mode)
        validator = kwargs.get("validator")
        if validator:
            validator(result)
        await asyncio.sleep(0)
        return result


class ResumePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_mock_pipeline_resumes_without_new_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_dir = root / "P1"
            project_dir.mkdir()
            chat = project_dir / "chat_messages.json"
            chat.write_text(
                json.dumps(
                    [
                        {
                            "created_ts": "2026-01-01 10:00:00",
                            "message": "Make the button blue.",
                            "message_user_type": "client",
                            "sender_id": "c1",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output_dir = root / "outputs"
            run_root = root / "runs"
            project = ProjectSource("P1", project_dir, chat, output_dir / "P1_stage1_annotation.json", run_root / "P1")
            config = PipelineConfig(
                prompt_path=root / "prompt.md",
                output_dir=output_dir,
                run_root=run_root,
                model="fake-model",
                resume=True,
                evidence_chunk_size=10,
                evidence_chunk_overlap=0,
                min_requirement_events=1,
            )
            api = FakeApiClient()
            pipeline = Stage1Pipeline(
                api,
                config,
                "test prompt",
                root / "calls.jsonl",
                verification_addendum="verifier calibration v1",
            )
            first = await pipeline.run(project)
            calls_after_first = list(api.calls)
            second = await pipeline.run(project)
            changed_verifier_pipeline = Stage1Pipeline(
                api,
                config,
                "test prompt",
                root / "calls.jsonl",
                verification_addendum="verifier calibration v2",
            )
            third = await changed_verifier_pipeline.run(project)
            config.force_stages = {"event_verification"}
            config.force_requirements = {"REQ_BUTTON_COLOR"}
            targeted_verifier_pipeline = Stage1Pipeline(
                api,
                config,
                "test prompt",
                root / "calls.jsonl",
                verification_addendum="verifier calibration v2",
            )
            fourth = await targeted_verifier_pipeline.run(project)
            run_metadata = json.loads((project.run_dir / "run_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(third, fourth)
        self.assertEqual(len(calls_after_first), 5)
        self.assertEqual(api.calls[:5], calls_after_first)
        self.assertEqual(
            api.calls[5:],
            [
                ("EVENT_VERIFICATION", "REQ_BUTTON_COLOR"),
                ("EVENT_VERIFICATION", "REQ_BUTTON_COLOR"),
            ],
        )
        self.assertEqual(first["requirements"][0]["events"][0]["event_id"], "REQ_BUTTON_COLOR_E001")
        self.assertEqual(len(first["requirements"]), 1)
        self.assertEqual(run_metadata["prompt_sha256"], sha256_text("test prompt"))
        self.assertEqual(
            run_metadata["verification_addendum_sha256"],
            sha256_text("verifier calibration v2"),
        )
        self.assertEqual(len(api.audit_user_messages), 1)
        self.assertIn("<EVIDENCE_INDEX>", api.audit_user_messages[0])
        self.assertIn("event_extraction_findings", api.audit_user_messages[0])
        self.assertEqual(len(api.verification_user_messages), 3)
        self.assertIn("<STAGE_INSTRUCTIONS>", api.verification_user_messages[-1])
        self.assertIn("verifier calibration v2", api.verification_user_messages[-1])
        self.assertIn("audit_review_items", api.verification_user_messages[-1])
        self.assertIn("Confirm that the source entails this target.", api.verification_user_messages[-1])


if __name__ == "__main__":
    unittest.main()

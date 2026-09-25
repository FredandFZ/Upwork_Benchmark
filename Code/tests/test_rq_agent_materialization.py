from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Code.rq_agent_input import (
    RQMaterializationError,
    load_target_views,
    materialize_reasoning_input,
    stage_phase_a_workspace,
    write_materialized_input,
)
from Code.rq_phase_a import RQPhaseAError, freeze_phase_a_response
from Code.rq_run_identity import (
    build_run_manifest,
    file_sha256,
    normalize_agent_config,
)
from Code.stage2.rq_instances import (
    build_project_manifest,
    build_rq_indexes,
    build_rq_instances,
)
from Code.tests.test_stage2_rq_instances import (
    _act_state_graph,
    _gold,
    _messages,
    _state_graph,
    _write_code_environment,
)


ROOT = Path(__file__).resolve().parents[2]
INSTRUCTIONS = ROOT / "prompt" / "rq_agent_instructions.md"
RESPONSE_SCHEMA = ROOT / "schema" / "rq_agent_response.schema.json"
RUN_PROMPT = ROOT / "prompt" / "rq_agent_run_prompt.md"
SELECTED_RQS = ("RQ1", "RQ2", "RQ3")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_project(project_dir: Path) -> None:
    collections = build_rq_instances(
        _gold(),
        _state_graph(),
        _messages(),
        rq_ids=SELECTED_RQS,
        input_release="P1-test-release",
    )
    indexes = build_rq_indexes(collections)
    manifest = build_project_manifest(
        collections,
        indexes,
        project_id="P1",
        rq_ids=SELECTED_RQS,
        input_release="P1-test-release",
        output_dir=project_dir,
    )
    for rq_id in SELECTED_RQS:
        for instance in collections[rq_id]:
            _write_json(
                project_dir / rq_id / f"{instance['instance_id']}.json",
                instance,
            )
        _write_json(project_dir / rq_id / "index.json", indexes[rq_id])
    _write_json(project_dir / "rq_instance_manifest.json", manifest)


def _clarify_response(evidence_message_ids: list[int]) -> dict:
    state = {
        "attributes": {"colour": "blue"},
        "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["FRONTEND"],
            "contexts": ["BUTTON"],
        },
        "lifecycle_status": "ACTIVE",
        "ambiguity": None,
        "execution": None,
    }
    return {
        "requirements": [
            {
                "requirement_ref": "agent-local-1",
                "requirement_summary": "Button colour",
                "evidence_message_ids": evidence_message_ids,
                "pre_task_state": state,
            }
        ],
        "decision": "CLARIFY",
        "post_task_states": None,
        "clarifications": [
            {
                "requirement_ref": "agent-local-1",
                "requirement_summary": "Button colour",
                "dimension": "VALUE",
                "field": "colour",
                "missing_information": "The requested final colour is not definite.",
                "question": "Should the final button colour be green?",
            }
        ],
    }


def _write_run_manifest(
    root: Path, package: dict, *, repetition: int = 1
) -> Path:
    normalized = normalize_agent_config(
        {
            "provider": "test",
            "runtime_version": "test-runtime",
            "model": "fake-agent",
            "model_version": "test-version",
            "reasoning_effort": "test",
            "tool_policy": "NO_TOOLS",
            "command": ["fake-agent"],
        },
        run_prompt_sha256=file_sha256(RUN_PROMPT),
        instructions_sha256=package["private_manifest"]["public_files"][
            "instructions.md"
        ],
        response_schema_sha256=package["private_manifest"]["public_files"][
            "response.schema.json"
        ],
    )
    manifest = build_run_manifest(
        package["private_manifest"],
        normalized_agent_config=normalized,
        repetition=repetition,
    )
    path = root / "private" / "run_manifest.json"
    _write_json(path, manifest)
    return path


class RQAgentMaterializationTests(unittest.TestCase):
    def test_one_target_materializes_both_reasoning_conditions_without_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "stage2" / "P1"
            _write_project(project_dir)

            c1 = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C1",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )
            c2 = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C2",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )

            self.assertEqual(
                c1["private_manifest"]["reasoning_active_rqs"],
                ["RQ1", "RQ2", "RQ3"],
            )
            self.assertEqual(
                c2["private_manifest"]["reasoning_active_rqs"],
                ["RQ2", "RQ3"],
            )
            c1_history = [
                json.loads(line)
                for line in c1["public_files"]["history.jsonl"].splitlines()
            ]
            c2_history = [
                json.loads(line)
                for line in c2["public_files"]["history.jsonl"].splitlines()
            ]
            self.assertEqual([row["message_id"] for row in c1_history], [10, 20, 30])
            self.assertEqual([row["message_id"] for row in c2_history], [10])
            for package in (c1, c2):
                public_text = "\n".join(package["public_files"].values())
                self.assertNotIn("construction_gold", public_text)
                self.assertNotIn("REQ_BUTTON", public_text)
                self.assertNotIn("P1_T001", public_text)
                task = json.loads(package["public_files"]["task.json"])
                self.assertNotIn("condition", task)
                self.assertNotIn("target_id", task)

            public_dir, private_path = write_materialized_input(
                c1, root / "agent_inputs"
            )
            self.assertTrue((public_dir / "task.json").is_file())
            self.assertTrue(private_path.is_file())
            self.assertNotEqual(private_path.parent, public_dir)
            self.assertNotIn("source_instances", (public_dir / "task.json").read_text())
            workspace = stage_phase_a_workspace(c1, root / "workspaces")
            self.assertEqual(workspace.name, c1["package_id"])
            self.assertEqual(
                {path.name for path in workspace.iterdir()},
                {
                    "task.json",
                    "history.jsonl",
                    "instructions.md",
                    "response.schema.json",
                },
            )
            self.assertNotIn("P1_T001", str(workspace))
            self.assertNotIn("C1", str(workspace))
            with self.assertRaisesRegex(
                RQMaterializationError, "will not be reused"
            ):
                stage_phase_a_workspace(c1, root / "workspaces")

    def test_formal_mode_blocks_unreviewed_rq2_and_rq3_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "P1"
            _write_project(project_dir)
            with self.assertRaisesRegex(
                RQMaterializationError, "formal reasoning is blocked"
            ):
                materialize_reasoning_input(
                    project_dir,
                    "P1_T001",
                    "C1",
                    instructions_path=INSTRUCTIONS,
                    response_schema_path=RESPONSE_SCHEMA,
                    mode="formal",
                )

    def test_rq4_candidate_metadata_stays_private_and_gate_stays_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "P1"
            code_environment = _write_code_environment(
                root / "code_environment",
                event_types=["MODIFY", "INTRODUCE"],
            )
            collections = build_rq_instances(
                _gold(),
                _act_state_graph(),
                _messages(),
                input_release="P1-rq4-test",
                code_environment_dir=code_environment,
            )
            indexes = build_rq_indexes(collections)
            manifest = build_project_manifest(
                collections,
                indexes,
                project_id="P1",
                input_release="P1-rq4-test",
                output_dir=project_dir,
            )
            for rq_id in ("RQ1", "RQ2", "RQ3", "RQ4"):
                for instance in collections[rq_id]:
                    _write_json(
                        project_dir / rq_id / f"{instance['instance_id']}.json",
                        instance,
                    )
                _write_json(project_dir / rq_id / "index.json", indexes[rq_id])
            _write_json(project_dir / "rq_instance_manifest.json", manifest)

            package = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C1",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )

            private = package["private_manifest"]
            public_text = "\n".join(package["public_files"].values())
            self.assertEqual(private["execution_rq"], "RQ4")
            self.assertFalse(private["rq4"]["eligible"])
            self.assertFalse(private["rq4"]["execution_ready"])
            self.assertEqual(private["repository"]["available_to_phase"], "B_ONLY")
            self.assertIsNotNone(private["repository"]["archive_sha256"])
            self.assertNotIn("archive_path", public_text)
            self.assertNotIn("pre_repo.zip", public_text)
            self.assertNotIn(
                "RQ4", manifest["targets"][0]["conditions"]["C1"]["active_rqs"]
            )

    def test_manifest_hash_detects_tampered_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "P1"
            _write_project(project_dir)
            manifest = json.loads(
                (project_dir / "rq_instance_manifest.json").read_text()
            )
            relative = manifest["targets"][0]["instances"]["RQ2"]["file"]
            instance_path = project_dir / relative
            instance = json.loads(instance_path.read_text())
            instance["target_task"]["text"] = "tampered"
            _write_json(instance_path, instance)

            with self.assertRaisesRegex(RQMaterializationError, "content hash"):
                load_target_views(project_dir, "P1_T001")

    def test_phase_a_response_is_frozen_once_and_keeps_package_manifest_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "P1"
            _write_project(project_dir)
            package = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C1",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )
            public_dir, package_path = write_materialized_input(
                package, root / "inputs"
            )
            package_hash = file_sha256(package_path)
            private_path = _write_run_manifest(root / "run", package)
            response_path = root / "agent_response.json"
            _write_json(response_path, _clarify_response([10]))

            result = freeze_phase_a_response(
                private_manifest_path=private_path,
                public_dir=public_dir,
                response_path=response_path,
                freeze_root=root / "runs",
            )

            self.assertEqual(result["freeze_record"]["decision"], "CLARIFY")
            self.assertEqual(result["freeze_record"]["phase_b_gate"], "CLOSED")
            self.assertEqual(
                result["freeze_record"]["phase_b_gate_reason"],
                "AGENT_DECISION_NOT_ACT",
            )
            frozen = result["freeze_dir"] / "agent_response.json"
            self.assertTrue(frozen.is_file())
            self.assertEqual(
                result["freeze_record"]["response_sha256"],
                (result["freeze_dir"] / "agent_response.sha256")
                .read_text()
                .strip(),
            )
            updated_private = json.loads(private_path.read_text())
            self.assertEqual(
                updated_private["phase_gate"]["phase_a_response_sha256"],
                result["freeze_record"]["response_sha256"],
            )
            self.assertEqual(file_sha256(package_path), package_hash)
            with self.assertRaisesRegex(RQPhaseAError, "already frozen"):
                freeze_phase_a_response(
                    private_manifest_path=private_path,
                    public_dir=public_dir,
                    response_path=response_path,
                    freeze_root=root / "runs",
                )

    def test_phase_a_freeze_rejects_evidence_hidden_by_condition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "P1"
            _write_project(project_dir)
            package = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C2",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )
            public_dir, _ = write_materialized_input(
                package, root / "inputs"
            )
            private_path = _write_run_manifest(root / "run", package)
            response_path = root / "agent_response.json"
            _write_json(response_path, _clarify_response([20]))

            with self.assertRaisesRegex(RQPhaseAError, "outside visible history"):
                freeze_phase_a_response(
                    private_manifest_path=private_path,
                    public_dir=public_dir,
                    response_path=response_path,
                    freeze_root=root / "runs",
                )


if __name__ == "__main__":
    unittest.main()

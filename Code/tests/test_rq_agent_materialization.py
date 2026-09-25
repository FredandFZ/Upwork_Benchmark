from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Code.rq_agent_input import (
    RQMaterializationError,
    load_target_views,
    materialize_reasoning_input,
    write_materialized_input,
)
from Code.stage2.rq_instances import (
    build_project_manifest,
    build_rq_indexes,
    build_rq_instances,
)
from Code.tests.test_stage2_rq_instances import _gold, _messages, _state_graph


ROOT = Path(__file__).resolve().parents[2]
INSTRUCTIONS = ROOT / "prompt" / "rq_agent_instructions.md"
RESPONSE_SCHEMA = ROOT / "schema" / "rq_agent_response.schema.json"
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


if __name__ == "__main__":
    unittest.main()

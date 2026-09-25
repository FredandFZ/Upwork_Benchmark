from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

from Code.build_rq4_agent_judge_registry import build_registry
from Code.rq_agent_input import materialize_reasoning_input, write_materialized_input
from Code.rq_phase_a import freeze_phase_a_response
from Code.rq_run_identity import build_run_manifest, file_sha256, normalize_agent_config
from Code.rq4_agent_judge import (
    finalize_rq4_result,
    validate_agent_judge_result,
)
from Code.rq4_phase_b import freeze_phase_b_repository, stage_phase_b_workspace
from Code.run_rq4_agent_judges import evaluate_run
from Code.aggregate_rq4_results import aggregate


ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class RQ4AgentJudgePipelineTests(unittest.TestCase):
    def test_current_registry_selects_exactly_40_deterministic_targets(self):
        registry = build_registry(expected_count=40)
        self.assertEqual(registry["selection"]["raw_target_count"], 99)
        self.assertEqual(registry["selection"]["included_target_count"], 40)
        self.assertEqual(len(registry["targets"]), 40)
        self.assertEqual(
            len({row["target_id"] for row in registry["targets"]}), 40
        )
        for row in registry["targets"]:
            self.assertTrue(row["acceptance_criteria"])
            self.assertNotIn("gold_requirement_refs", json.dumps(row["acceptance_criteria"]))
            self.assertNotIn("gold_state_paths", json.dumps(row["acceptance_criteria"]))
            self.assertTrue(
                all(
                    row["condition_eligibility"][condition]["rq4_eligible"]
                    for condition in ("C1", "C2")
                )
            )

    def test_registry_target_links_to_formal_phase_a_without_public_leakage(self):
        registry = build_registry(expected_count=40)
        row = registry["targets"][0]
        package = materialize_reasoning_input(
            ROOT / "outputs_new" / "stage2" / row["project_id"],
            row["target_id"],
            "C1",
            instructions_path=ROOT / "prompt" / "rq_agent_instructions.md",
            response_schema_path=ROOT / "schema" / "rq_agent_response.schema.json",
            mode="formal",
            rq4_evaluation_record=row,
            rq4_judge_contract=registry["judge_contract"],
            rq4_registry_sha256="0" * 64,
        )
        private = package["private_manifest"]
        self.assertTrue(private["rq4"]["eligible"])
        self.assertTrue(private["rq4"]["execution_ready"])
        self.assertEqual(private["execution_rq"], "RQ4")
        self.assertTrue(private["rq4"]["acceptance_criteria"])
        public = "\n".join(package["public_files"].values())
        self.assertNotIn("acceptance_criteria", public)
        self.assertNotIn("judge_contract", public)

        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            public_dir, _ = write_materialized_input(package, temporary_root / "inputs")
            agent_config = normalize_agent_config(
                {
                    "provider": "test",
                    "runtime_version": "test",
                    "model": "test-agent",
                    "model_version": "test",
                    "reasoning_effort": "test",
                    "tool_policy": "NO_TOOLS",
                    "command": ["fake-agent"],
                },
                run_prompt_sha256="1" * 64,
                instructions_sha256=file_sha256(public_dir / "instructions.md"),
                response_schema_sha256=file_sha256(public_dir / "response.schema.json"),
            )
            run_manifest = build_run_manifest(
                package["private_manifest"],
                normalized_agent_config=agent_config,
                repetition=1,
            )
            manifest_path = temporary_root / "private" / "run_manifest.json"
            _write_json(manifest_path, run_manifest)
            state = {
                "attributes": {},
                "scope": {},
                "lifecycle_status": "ACTIVE",
                "ambiguity": None,
                "execution": None,
            }
            response = {
                "requirements": [],
                "decision": "ACT",
                "post_task_states": [
                    {
                        "requirement_ref": "agent-local-1",
                        "requirement_summary": "Requested change",
                        "change_type": "MODIFIED",
                        "removed_attribute_keys": [],
                        "state": state,
                    }
                ],
                "clarifications": [],
            }
            response_path = temporary_root / "agent_response.json"
            _write_json(response_path, response)
            frozen = freeze_phase_a_response(
                private_manifest_path=manifest_path,
                public_dir=public_dir,
                response_path=response_path,
                freeze_root=temporary_root / "runs",
            )
            self.assertEqual(frozen["freeze_record"]["phase_b_gate"], "OPEN")

    def test_phase_b_stages_only_after_open_gate_and_freezes_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = root / "repository_root"
            source = root / "source"
            (source / "scripts").mkdir(parents=True)
            (source / "README.md").write_text("before\n", encoding="utf-8")
            (source / "scripts" / "build.py").write_text("print('ok')\n", encoding="utf-8")
            (source / "scripts" / "check.py").write_text("print('ok')\n", encoding="utf-8")
            archive = repository_root / "pre_repo.zip"
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        output.write(path, path.relative_to(source).as_posix())

            run_id = "run_" + "a" * 20
            run_dir = root / "runs" / run_id
            phase_a_input = run_dir / "private" / "phase_a_input"
            task_path = phase_a_input / "task.json"
            history_path = phase_a_input / "history.jsonl"
            _write_json(task_path, {"schema_version": "rq-agent-task-v1", "task": {"message_id": 2, "speaker": "client", "text": "Change it"}})
            history_path.write_text("", encoding="utf-8")
            response_path = run_dir / "phase_a" / "agent_response.json"
            _write_json(response_path, {"decision": "ACT"})
            response_hash = _sha256(response_path)
            manifest = {
                "schema_version": "rq-private-run-manifest-v2",
                "run_id": run_id,
                "project_id": "P1",
                "target_id": "P1_T001",
                "condition": "C1",
                "agent_config_id": "agentcfg_test",
                "repetition": 1,
                "rq4": {
                    "eligible": True,
                    "execution_ready": True,
                    "acceptance_criteria": [
                        {
                            "criterion_id": "AC001",
                            "scope": "TARGET_BEHAVIOR",
                            "statement": "README contains the implemented value.",
                            "observables": [],
                            "negative_cases": [],
                        }
                    ],
                    "judge_contract": {
                        "prompt_sha256": _sha256(ROOT / "prompt" / "rq4_agent_judge.md"),
                        "response_schema_sha256": _sha256(ROOT / "schema" / "rq4_agent_judge_result.schema.json"),
                    },
                    "evaluation_commands": {
                        "build": ["{python}", "scripts/build.py"],
                        "regression": ["{python}", "scripts/check.py"],
                    },
                },
                "phase_gate": {
                    "phase_a_decision": "ACT",
                    "phase_b_gate": "OPEN",
                    "phase_a_response_sha256": response_hash,
                },
                "repository": {
                    "archive_path": "pre_repo.zip",
                    "archive_sha256": _sha256(archive),
                    "tree_sha256": _tree_sha256(source),
                },
                "phase_a_input_files": {
                    "task.json": {"path": "private/phase_a_input/task.json", "sha256": _sha256(task_path)},
                    "history.jsonl": {"path": "private/phase_a_input/history.jsonl", "sha256": _sha256(history_path)},
                },
            }
            _write_json(run_dir / "private" / "run_manifest.json", manifest)
            _write_json(run_dir / "run_status.json", {"schema_version": "rq-run-status-v1", "run_id": run_id})
            instructions = root / "instructions.md"
            instructions.write_text("Implement the task.\n", encoding="utf-8")

            workspace = stage_phase_b_workspace(
                run_dir=run_dir,
                workspace_root=root / "workspaces",
                repository_root=repository_root,
                instructions_path=instructions,
            )
            self.assertTrue((workspace / "repository" / "README.md").is_file())
            (workspace / "repository" / "README.md").write_text("after\n", encoding="utf-8")
            frozen = freeze_phase_b_repository(run_dir=run_dir, workspace=workspace)
            self.assertEqual(frozen["evaluation_status"], "PENDING_AGENT_JUDGE")
            self.assertTrue((run_dir / "phase_b" / "final_repository.zip").is_file())
            (workspace / "frozen" / "agent_response.json").chmod(stat.S_IWRITE | stat.S_IREAD)

            fake_judge = (
                "import json,sys;"
                "d=json.load(open('judge_input.json',encoding='utf-8'));"
                "r={'schema_version':'rq4-agent-judge-result-v1','target_id':d['target_id'],"
                "'criteria':[{'criterion_id':x['criterion_id'],'verdict':'PASS',"
                "'evidence':[{'operation':'READ_FILE','observation':'README contains after.','artifact':None}]}"
                " for x in d['acceptance_criteria']], 'judge_summary':'All criteria passed.'};"
                "open(sys.argv[1],'w',encoding='utf-8').write(json.dumps(r))"
            )
            result = evaluate_run(
                run_dir=run_dir,
                judge_config={
                    "provider": "test-command",
                    "runtime_version": "test",
                    "model": "fake-judge",
                    "model_version": "test",
                    "reasoning_effort": "test",
                    "tool_policy": "LOCAL_READ_ONLY",
                    "command": [sys.executable, "-c", fake_judge, "{output_path}"],
                    "output_mode": "workspace_file",
                    "output_filename": "judge_result.json",
                    "timeout_seconds": 30,
                },
                prompt_path=ROOT / "prompt" / "rq4_agent_judge.md",
                response_schema_path=ROOT / "schema" / "rq4_agent_judge_result.schema.json",
                workspace_root=root / "judge_workspaces",
            )
            self.assertEqual(result["score_status"], "SCORED")
            self.assertEqual(result["result"], "PASS")

    def test_judge_validation_and_finalizer_keep_unsure_out_of_formal_score(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            evidence = workspace / "evidence" / "ac001.json"
            evidence.parent.mkdir()
            evidence.write_text("{}\n", encoding="utf-8")
            raw = {
                "schema_version": "rq4-agent-judge-result-v1",
                "target_id": "P1_T001",
                "criteria": [
                    {
                        "criterion_id": "AC001",
                        "verdict": "UNSURE",
                        "evidence": [
                            {
                                "operation": "RUN_TEST",
                                "observation": "The required renderer was unavailable.",
                                "artifact": "evidence/ac001.json",
                            }
                        ],
                    }
                ],
                "judge_summary": "The criterion could not be decided.",
            }
            judged = validate_agent_judge_result(
                raw,
                target_id="P1_T001",
                criterion_ids=["AC001"],
                workspace=workspace,
            )
            final = finalize_rq4_result(
                run_identity={"run_id": "run_x", "project_id": "P1", "target_id": "P1_T001", "condition": "C1"},
                build={"status": "PASS"},
                regression={"status": "PASS"},
                judge_result=judged,
                judge_config_id="rq4judge_test",
            )
            self.assertEqual(final["score_status"], "REVIEW_REQUIRED")
            self.assertIsNone(final["result"])

            judged["criteria"][0]["verdict"] = "PASS"
            passed = finalize_rq4_result(
                run_identity={"run_id": "run_x", "project_id": "P1", "target_id": "P1_T001", "condition": "C1"},
                build={"status": "PASS"},
                regression={"status": "PASS"},
                judge_result=judged,
                judge_config_id="rq4judge_test",
            )
            self.assertEqual(passed["result"], "PASS")

    def test_aggregator_counts_phase_a_no_code_submission_as_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            closed = root / ("run_" + "1" * 20)
            passed = root / ("run_" + "2" * 20)
            common = {
                "rq4": {"eligible": True},
                "project_id": "P1",
                "target_id": "P1_T001",
                "condition": "C1",
                "agent_config_id": "agentcfg_test",
                "repetition": 1,
            }
            _write_json(
                closed / "private" / "run_manifest.json",
                {
                    **common,
                    "run_id": closed.name,
                    "phase_gate": {
                        "phase_b_gate": "CLOSED",
                        "phase_b_gate_reason": "AGENT_DECISION_NOT_ACT",
                    },
                },
            )
            _write_json(
                passed / "private" / "run_manifest.json",
                {
                    **common,
                    "run_id": passed.name,
                    "target_id": "P1_T002",
                    "phase_gate": {"phase_b_gate": "OPEN"},
                },
            )
            _write_json(
                passed / "rq4_evaluation" / "result.json",
                {
                    "score_status": "SCORED",
                    "result": "PASS",
                    "decision_reason": "ALL_GATES_PASS",
                },
            )
            summary = aggregate(root)
            self.assertEqual(summary["eligible_run_count"], 2)
            self.assertEqual(summary["scored_run_count"], 2)
            self.assertEqual(summary["pass_count"], 1)
            self.assertEqual(summary["fail_count"], 1)
            self.assertEqual(summary["success_rate"], 0.5)
            self.assertEqual(summary["project_macro_success_rate"], 0.5)

    def test_aggregator_compares_only_fully_scored_c1_c2_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outcomes = [
                ("P1_T001", "C1", "PASS"),
                ("P1_T001", "C2", "FAIL"),
                ("P1_T002", "C1", "FAIL"),
                ("P1_T002", "C2", "PASS"),
                ("P1_T003", "C1", "PASS"),
            ]
            for index, (target_id, condition, outcome) in enumerate(outcomes, start=1):
                run_dir = root / ("run_" + str(index) * 20)
                _write_json(
                    run_dir / "private" / "run_manifest.json",
                    {
                        "run_id": run_dir.name,
                        "rq4": {"eligible": True},
                        "project_id": "P1",
                        "target_id": target_id,
                        "condition": condition,
                        "agent_config_id": "agentcfg_test",
                        "repetition": 1,
                        "phase_gate": {"phase_b_gate": "OPEN"},
                    },
                )
                _write_json(
                    run_dir / "rq4_evaluation" / "result.json",
                    {
                        "score_status": "SCORED",
                        "result": outcome,
                        "decision_reason": "TEST_OUTCOME",
                    },
                )
            paired = aggregate(root)["paired_comparison"]
            self.assertEqual(paired["eligible_pair_count"], 2)
            self.assertEqual(paired["scored_pair_count"], 2)
            self.assertEqual(paired["success_rate"], {"C1": 0.5, "C2": 0.5})
            self.assertEqual(paired["success_rate_delta_c2_minus_c1"], 0.0)
            self.assertEqual(
                paired["project_macro_success_rate"],
                {"C1": 0.5, "C2": 0.5},
            )
            self.assertEqual(
                paired["discordant_pairs"],
                {"c1_pass_c2_fail": 1, "c1_fail_c2_pass": 1},
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from Code.rq_agent_input import materialize_reasoning_input, write_materialized_input
from Code.rq_agent_runtime import run_isolated_agent_case
from Code.aggregate_rq123_results import aggregate_run_tree
from Code.rq_batch_evaluation import evaluate_frozen_run
from Code.rq_judge_provider import JudgeCallResult
from Code.rq_run_identity import file_sha256
from Code.tests.test_rq_agent_materialization import (
    INSTRUCTIONS,
    RESPONSE_SCHEMA,
    ROOT,
    RUN_PROMPT,
    _clarify_response,
    _write_project,
)


class _FakeJudgeProvider:
    config_id = "judgecfg_00000000000000000000"

    async def call(self, request, *, response_schema, metadata):
        del response_schema, metadata
        version = request["schema_version"]
        response_version = request["required_response"]["schema_version"]
        if version in {
            "rq1-alignment-request-v1",
            "requirement-alignment-request-v1",
        }:
            relations = [
                {
                    "prediction_ref": row["prediction_ref"],
                    "gold_ref": row["gold_ref"],
                    "relation": "UNRELATED",
                }
                for row in request["candidate_pairs"]
            ]
        elif version == "state-semantic-request-v1":
            relations = [
                {"fact_id": row["fact_id"], "relation": "NOT_EQUIVALENT"}
                for row in request["facts"]
            ]
        elif version == "rq3-clarification-semantic-request-v1":
            relations = [
                {
                    "candidate_id": row["candidate_id"],
                    "issue_relation": "NOT_EQUIVALENT",
                    "question_validity": "INVALID",
                }
                for row in request["candidates"]
            ]
        else:  # pragma: no cover - protects future request additions
            raise AssertionError(version)
        return JudgeCallResult(
            response={"schema_version": response_version, "relations": relations},
            provider="fake",
            model="fake-judge",
            model_version="test",
            reasoning_effort="test",
            request_id="fake-request",
            input_tokens=1,
            output_tokens=1,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
        )

    async def aclose(self):
        return None


class RQExecutionRuntimeTests(unittest.TestCase):
    def test_new_process_run_freezes_output_and_purges_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "stage2" / "P1"
            _write_project(project_dir)
            package = materialize_reasoning_input(
                project_dir,
                "P1_T001",
                "C1",
                instructions_path=INSTRUCTIONS,
                response_schema_path=RESPONSE_SCHEMA,
            )
            # This synthetic fixture intentionally leaves RQ3 Gold pending;
            # existing RQ3 evaluator tests cover its frozen branches.
            package["private_manifest"]["reasoning_active_rqs"] = ["RQ1", "RQ2"]
            _, package_path = write_materialized_input(package, root / "inputs")
            original_package_hash = file_sha256(package_path)
            response_text = json.dumps(_clarify_response([10]), ensure_ascii=False)
            agent_config = {
                "provider": "test-command",
                "runtime_version": "test-runtime",
                "model": "fake-agent",
                "model_version": "test",
                "reasoning_effort": "test",
                "tool_policy": "NO_TOOLS",
                "command": [
                    sys.executable,
                    "-c",
                    f"import sys; sys.stdout.write({response_text!r})",
                ],
                "output_mode": "stdout_json",
                "timeout_seconds": 30,
                "environment_allowlist": [],
            }
            result = run_isolated_agent_case(
                package_manifest_path=package_path,
                agent_config=agent_config,
                repetition=1,
                run_prompt_path=RUN_PROMPT,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )
            self.assertEqual(result["status"], "FROZEN")
            self.assertFalse((root / "workspaces" / result["run_id"]).exists())
            self.assertEqual(file_sha256(package_path), original_package_hash)
            manifest = json.loads(
                (result["run_dir"] / "private" / "run_manifest.json").read_text()
            )
            self.assertEqual(manifest["repetition"], 1)
            self.assertFalse(manifest["agent_config"]["persistent_conversation"])

            repeated = run_isolated_agent_case(
                package_manifest_path=package_path,
                agent_config=agent_config,
                repetition=1,
                run_prompt_path=RUN_PROMPT,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )
            self.assertEqual(repeated["status"], "SKIPPED_FROZEN")

            second = run_isolated_agent_case(
                package_manifest_path=package_path,
                agent_config=agent_config,
                repetition=2,
                run_prompt_path=RUN_PROMPT,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )
            self.assertNotEqual(second["run_id"], result["run_id"])

            summary = asyncio.run(
                evaluate_frozen_run(result["run_dir"], provider=_FakeJudgeProvider())
            )
            self.assertEqual(summary["scored_rqs"], ["RQ1", "RQ2"])
            for rq_id in summary["scored_rqs"]:
                self.assertTrue(
                    (
                        result["run_dir"]
                        / "scores"
                        / _FakeJudgeProvider.config_id
                        / f"{rq_id}.json"
                    ).is_file()
                )
            aggregate = aggregate_run_tree(root / "runs")
            self.assertEqual(aggregate["scored_record_count"], 2)
            self.assertIn("RQ2", aggregate["baselines"])


if __name__ == "__main__":
    unittest.main()

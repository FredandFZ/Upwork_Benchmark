#!/usr/bin/env python3
"""Run the universal tool-using RQ4 Judge and deterministically finalize scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

try:  # Package import in tests; script import in CLI use.
    from .rq4_agent_judge import (
        RQ4JudgeValidationError,
        finalize_rq4_result,
        validate_agent_judge_result,
    )
    from .rq4_phase_b import RQ4PhaseBError, _extract_repository
    from .rq_agent_runtime import (
        RQAgentRuntimeError,
        _execute_process,
        _expanded_command,
        _minimal_environment,
        _parse_claude_structured_json,
        _parse_stdout_json,
    )
    from .rq_run_identity import file_sha256, normalize_agent_config, read_json_object
except ImportError:  # pragma: no cover
    from rq4_agent_judge import (
        RQ4JudgeValidationError,
        finalize_rq4_result,
        validate_agent_judge_result,
    )
    from rq4_phase_b import RQ4PhaseBError, _extract_repository
    from rq_agent_runtime import (
        RQAgentRuntimeError,
        _execute_process,
        _expanded_command,
        _minimal_environment,
        _parse_claude_structured_json,
        _parse_stdout_json,
    )
    from rq_run_identity import file_sha256, normalize_agent_config, read_json_object


ROOT = Path(__file__).resolve().parents[1]


class RQ4JudgeRunnerError(ValueError):
    pass


def _tree_sha256(root: Path) -> str:
    ignored_parts = {"__pycache__", ".git", ".rq4-results"}
    digest = hashlib.sha256()
    files = (
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix != ".pyc"
        and not any(
            part in ignored_parts for part in path.relative_to(root).parts
        )
    )
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _run_component(name: str, command: list[str], repository: Path, timeout: int) -> dict[str, Any]:
    expanded = [sys.executable if part == "{python}" else part for part in command]
    try:
        result = subprocess.run(
            expanded,
            cwd=repository,
            env=_minimal_environment([]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return {
            "status": "HARNESS_ERROR",
            "command": command,
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }
    status = "PASS" if result.returncode == 0 else ("FAIL" if result.returncode == 1 else "HARNESS_ERROR")
    return {
        "status": status,
        "command": command,
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-8000:],
        "stderr_tail": result.stderr[-8000:],
    }


def evaluate_run(
    *,
    run_dir: Path,
    judge_config: Mapping[str, Any],
    prompt_path: Path,
    response_schema_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    manifest = read_json_object(run_dir / "private" / "run_manifest.json")
    phase_b = read_json_object(run_dir / "phase_b" / "freeze_record.json")
    archive = run_dir / phase_b["final_repository_archive"]
    if not archive.is_file() or file_sha256(archive) != phase_b.get("final_repository_archive_sha256"):
        raise RQ4JudgeRunnerError("frozen Phase B repository is missing or stale")
    rq4 = manifest.get("rq4")
    if not isinstance(rq4, Mapping) or rq4.get("eligible") is not True:
        raise RQ4JudgeRunnerError("run is not RQ4 eligible")
    contract = rq4.get("judge_contract")
    if not isinstance(contract, Mapping):
        raise RQ4JudgeRunnerError("run has no frozen Judge contract")
    if file_sha256(prompt_path) != contract.get("prompt_sha256"):
        raise RQ4JudgeRunnerError("universal Judge prompt hash mismatch")
    if file_sha256(response_schema_path) != contract.get("response_schema_sha256"):
        raise RQ4JudgeRunnerError("Judge response schema hash mismatch")
    normalized = normalize_agent_config(
        judge_config,
        run_prompt_sha256=file_sha256(prompt_path),
        instructions_sha256=file_sha256(prompt_path),
        response_schema_sha256=file_sha256(response_schema_path),
    )
    judge_config_id = "rq4judge_" + hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    workspace = workspace_root.resolve() / manifest["run_id"]
    if workspace.exists():
        raise RQ4JudgeRunnerError(f"Judge workspace already exists: {workspace}")
    workspace.mkdir(parents=True)
    repository = workspace / "repository"
    repository.mkdir()
    try:
        actual_tree = _extract_repository(archive, repository)
        if actual_tree != phase_b.get("final_repository_tree_sha256"):
            raise RQ4JudgeRunnerError("frozen Phase B repository tree hash mismatch")
        before_judge_tree = _tree_sha256(repository)
        commands = rq4.get("evaluation_commands")
        if not isinstance(commands, Mapping):
            raise RQ4JudgeRunnerError("run has no RQ4 evaluation commands")
        timeout = int(normalized["timeout_seconds"])
        build = _run_component("build", list(commands.get("build", [])), repository, timeout)
        regression = _run_component("regression", list(commands.get("regression", [])), repository, timeout)
        judge_result: dict[str, Any] | None = None
        evaluation_dir = run_dir / "rq4_evaluation"
        if build["status"] == "PASS" and regression["status"] == "PASS":
            retained_task = run_dir / "private" / "phase_a_input" / "task.json"
            task = read_json_object(retained_task).get("task")
            judge_input = {
                "schema_version": "rq4-agent-judge-input-v1",
                "target_id": manifest.get("target_id"),
                "task": task,
                "acceptance_criteria": rq4.get("acceptance_criteria"),
                "deterministic_checks": {"build": build, "regression": regression},
                "repository_path": "repository",
                "network_policy": "DISABLED",
            }
            _write_json(workspace / "judge_input.json", judge_input)
            shutil.copyfile(prompt_path, workspace / "judge_instructions.md")
            shutil.copyfile(response_schema_path, workspace / "response.schema.json")
            output_path = workspace / normalized["output_filename"]
            command = _expanded_command(
                normalized["command"],
                workspace=workspace,
                output_path=output_path,
                run_id=manifest["run_id"],
                model=normalized["model"],
                model_version=normalized["model_version"],
                reasoning_effort=normalized["reasoning_effort"],
                response_schema_json=json.dumps(read_json_object(response_schema_path), separators=(",", ":")),
            )
            prompt = prompt_path.read_text(encoding="utf-8-sig") + "\nRead judge_input.json and response.schema.json from this workspace.\n"
            returncode, stdout, stderr = _execute_process(
                command,
                workspace=workspace,
                prompt=prompt,
                timeout_seconds=timeout,
                environment=_minimal_environment(normalized["environment_allowlist"]),
            )
            evaluation_dir.mkdir(parents=True, exist_ok=True)
            (evaluation_dir / "judge_stdout.txt").write_text(stdout, encoding="utf-8")
            (evaluation_dir / "judge_stderr.txt").write_text(stderr, encoding="utf-8")
            if returncode != 0:
                raise RQ4JudgeRunnerError(f"Agent Judge exited with status {returncode}")
            if normalized["output_mode"] == "stdout_json":
                raw = _parse_stdout_json(stdout)
            elif normalized["output_mode"] == "claude_structured_json":
                raw, metadata = _parse_claude_structured_json(stdout)
                _write_json(evaluation_dir / "judge_provider_metadata.json", metadata)
            else:
                if not output_path.is_file():
                    raise RQ4JudgeRunnerError("Agent Judge did not write its result file")
                raw = read_json_object(output_path)
            criterion_ids = [row["criterion_id"] for row in rq4["acceptance_criteria"]]
            judge_result = validate_agent_judge_result(
                raw,
                target_id=manifest["target_id"],
                criterion_ids=criterion_ids,
                workspace=workspace,
            )
            if _tree_sha256(repository) != before_judge_tree:
                raise RQ4JudgeRunnerError("Agent Judge modified the candidate repository")
            _write_json(evaluation_dir / "agent_judge_result.json", judge_result)
        final = finalize_rq4_result(
            run_identity=manifest,
            build=build,
            regression=regression,
            judge_result=judge_result,
            judge_config_id=judge_config_id,
        )
        _write_json(run_dir / "rq4_evaluation" / "result.json", final)
        status_path = run_dir / "run_status.json"
        status = read_json_object(status_path)
        status.update({"rq4_evaluation": final["score_status"], "rq4_result": final["result"]})
        _write_json(status_path, status)
        return final
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, default=ROOT / "outputs_new" / "rq4_runs")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompt" / "rq4_agent_judge.md")
    parser.add_argument("--response-schema", type=Path, default=ROOT / "schema" / "rq4_agent_judge_result.schema.json")
    parser.add_argument("--workspace-root", type=Path, default=Path(tempfile.gettempdir()) / "reqmembench_rq4_judge")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        config = read_json_object(args.config)
        judge_config = config.get("rq4_judge_agent")
        if not isinstance(judge_config, Mapping):
            raise RQ4JudgeRunnerError("config requires rq4_judge_agent")
        discovered_runs = sorted(
            path.parent.parent
            for path in args.run_root.rglob("phase_b/freeze_record.json")
        )
        skipped_evaluated = [
            run
            for run in discovered_runs
            if (run / "rq4_evaluation" / "result.json").is_file()
        ]
        runs = [run for run in discovered_runs if run not in skipped_evaluated]
        if args.limit is not None:
            runs = runs[: args.limit]
        if not runs:
            if skipped_evaluated:
                print(
                    json.dumps(
                        {
                            "requested": 0,
                            "evaluated": 0,
                            "skipped_evaluated": len(skipped_evaluated),
                            "scored": 0,
                            "review_required": 0,
                            "failed": 0,
                            "failures": [],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            raise RQ4JudgeRunnerError("no frozen Phase B runs found")
        results = []
        failures = []
        for run in runs:
            try:
                result = evaluate_run(
                    run_dir=run,
                    judge_config=judge_config,
                    prompt_path=args.prompt.resolve(),
                    response_schema_path=args.response_schema.resolve(),
                    workspace_root=args.workspace_root,
                )
                results.append(result)
                print(
                    f"{run.name}: {result['score_status']}"
                    + (f"/{result['result']}" if result["result"] else "")
                )
            except Exception as exc:
                failures.append(
                    {"run_id": run.name, "error": f"{type(exc).__name__}: {exc}"}
                )
                print(f"FAILED {run.name}: {exc}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "requested": len(runs),
                    "evaluated": len(results),
                    "skipped_evaluated": len(skipped_evaluated),
                    "scored": sum(r["score_status"] == "SCORED" for r in results),
                    "review_required": sum(
                        r["score_status"] == "REVIEW_REQUIRED" for r in results
                    ),
                    "failed": len(failures),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2 if failures else 0
    except (OSError, KeyError, TypeError, RQ4JudgeRunnerError, RQ4JudgeValidationError, RQ4PhaseBError, RQAgentRuntimeError) as exc:
        print(f"RQ4 Agent Judge failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

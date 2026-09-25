#!/usr/bin/env python3
"""Run RQ4 Phase B coding agents after the frozen Phase A ACT gate opens."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping

try:  # Package import in tests; script import in CLI use.
    from .rq4_phase_b import RQ4PhaseBError, freeze_phase_b_repository, stage_phase_b_workspace
    from .rq_agent_runtime import (
        RQAgentRuntimeError,
        _execute_process,
        _expanded_command,
        _minimal_environment,
    )
    from .rq_run_identity import (
        agent_config_id,
        file_sha256,
        normalize_agent_config,
        read_json_object,
    )
except ImportError:  # pragma: no cover
    from rq4_phase_b import RQ4PhaseBError, freeze_phase_b_repository, stage_phase_b_workspace
    from rq_agent_runtime import (
        RQAgentRuntimeError,
        _execute_process,
        _expanded_command,
        _minimal_environment,
    )
    from rq_run_identity import (
        agent_config_id,
        file_sha256,
        normalize_agent_config,
        read_json_object,
    )


ROOT = Path(__file__).resolve().parents[1]


class RQ4PhaseBRunnerError(ValueError):
    pass


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_phase_b_case(
    *,
    run_dir: Path,
    agent_config: Mapping[str, Any],
    prompt_path: Path,
    workspace_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    manifest_path = run_dir / "private" / "run_manifest.json"
    manifest = read_json_object(manifest_path)
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or run_dir.name != run_id:
        raise RQ4PhaseBRunnerError("run identity mismatch")
    existing = run_dir / "phase_b" / "freeze_record.json"
    if existing.is_file():
        return {"status": "SKIPPED_FROZEN", "run_id": run_id}
    normalized = normalize_agent_config(
        agent_config,
        run_prompt_sha256=file_sha256(prompt_path),
        instructions_sha256=file_sha256(prompt_path),
        response_schema_sha256=file_sha256(prompt_path),
    )
    phase_b_config_id = agent_config_id(normalized)
    prior = manifest.get("phase_b_agent_config_id")
    if prior is not None and prior != phase_b_config_id:
        raise RQ4PhaseBRunnerError("run already binds a different Phase B Agent config")
    manifest["phase_b_agent_config_id"] = phase_b_config_id
    manifest["phase_b_agent_config"] = deepcopy(normalized)
    _write_json(manifest_path, manifest)
    workspace = stage_phase_b_workspace(
        run_dir=run_dir,
        workspace_root=workspace_root,
        repository_root=repository_root,
        instructions_path=prompt_path,
    )
    agent_dir = run_dir / "phase_b_agent"
    output_path = workspace / normalized["output_filename"]
    command = _expanded_command(
        normalized["command"],
        workspace=workspace,
        output_path=output_path,
        run_id=run_id,
        model=normalized["model"],
        model_version=normalized["model_version"],
        reasoning_effort=normalized["reasoning_effort"],
        response_schema_json="{}",
    )
    prompt = prompt_path.read_text(encoding="utf-8-sig") + "\nRead the staged files and complete the coding task now.\n"
    record = {
        "schema_version": "rq4-phase-b-agent-process-v1",
        "run_id": run_id,
        "phase_b_agent_config_id": phase_b_config_id,
        "command": command,
        "status": "RUNNING",
    }
    try:
        returncode, stdout, stderr = _execute_process(
            command,
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=normalized["timeout_seconds"],
            environment=_minimal_environment(normalized["environment_allowlist"]),
        )
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (agent_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        record["returncode"] = returncode
        if returncode != 0:
            record["status"] = "FAILED"
            _write_json(agent_dir / "process_record.json", record)
            status = read_json_object(run_dir / "run_status.json")
            status.update({"phase_b": "FAILED", "rq4_evaluation": "SCORED", "rq4_result": "FAIL"})
            _write_json(run_dir / "run_status.json", status)
            raise RQ4PhaseBRunnerError(f"Phase B Agent exited with status {returncode}")
        freeze = freeze_phase_b_repository(run_dir=run_dir, workspace=workspace)
        record["status"] = "FROZEN"
        record["final_repository_tree_sha256"] = freeze["final_repository_tree_sha256"]
        _write_json(agent_dir / "process_record.json", record)
        return {"status": "FROZEN", "run_id": run_id, "freeze_record": freeze}
    finally:
        if workspace.exists():
            expected = workspace_root.resolve() / run_id
            if workspace.resolve() == expected.resolve():
                shutil.rmtree(workspace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, default=ROOT / "outputs_new" / "rq4_runs")
    parser.add_argument("--workspace-root", type=Path, default=Path(tempfile.gettempdir()) / "reqmembench_rq4_phase_b")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompt" / "rq4_phase_b_instructions.md")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        config = read_json_object(args.config)
        phase_b_config = config.get("phase_b_agent")
        if not isinstance(phase_b_config, Mapping):
            raise RQ4PhaseBRunnerError("config requires phase_b_agent")
        candidates: list[Path] = []
        for freeze_path in sorted(args.run_root.rglob("phase_a/freeze_record.json")):
            record = read_json_object(freeze_path)
            if record.get("phase_b_gate") == "OPEN":
                candidates.append(freeze_path.parent.parent)
        if args.limit is not None:
            if args.limit < 1:
                raise RQ4PhaseBRunnerError("--limit must be positive")
            candidates = candidates[: args.limit]
        if not candidates:
            raise RQ4PhaseBRunnerError("no Phase A runs have an OPEN Phase B gate")
        results = []
        failures = []
        for run_dir in candidates:
            try:
                result = run_phase_b_case(
                    run_dir=run_dir,
                    agent_config=phase_b_config,
                    prompt_path=args.prompt.resolve(),
                    workspace_root=args.workspace_root,
                    repository_root=args.repository_root,
                )
                results.append(result)
                print(f"{result['run_id']}: {result['status']}")
            except Exception as exc:
                failures.append({"run_id": run_dir.name, "error": f"{type(exc).__name__}: {exc}"})
                print(f"FAILED {run_dir.name}: {exc}", file=sys.stderr)
        print(json.dumps({"requested": len(candidates), "completed": len(results), "failed": len(failures), "failures": failures}, ensure_ascii=False, indent=2))
        return 2 if failures else 0
    except (OSError, RQ4PhaseBError, RQ4PhaseBRunnerError, RQAgentRuntimeError) as exc:
        print(f"RQ4 Phase B batch failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

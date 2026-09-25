"""Fresh-process execution for ReqMemBench Phase A Agent cases."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json
import os
import re
import shutil
import signal
import subprocess

try:  # Package import in tests; script import in CLIs.
    from .rq_phase_a import freeze_phase_a_response
    from .rq_run_identity import (
        RQRunConfigError,
        build_run_manifest,
        canonical_sha256,
        file_sha256,
        normalize_agent_config,
        read_json_object,
        validate_package_manifest,
    )
except ImportError:  # pragma: no cover - exercised by script entry points
    from rq_phase_a import freeze_phase_a_response
    from rq_run_identity import (
        RQRunConfigError,
        build_run_manifest,
        canonical_sha256,
        file_sha256,
        normalize_agent_config,
        read_json_object,
        validate_package_manifest,
    )


RUN_PROMPT_FILENAME = "rq_agent_run_prompt.md"
EMBEDDED_INPUT_FILENAMES = (
    "task.json",
    "history.jsonl",
    "instructions.md",
    "response.schema.json",
)


class RQAgentRuntimeError(RuntimeError):
    """Raised when one isolated Agent process cannot produce a frozen result."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _safe_workspace_path(workspace_root: Path, run_id: str) -> Path:
    root = workspace_root.resolve()
    candidate = (root / run_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RQAgentRuntimeError("workspace path escapes workspace root") from exc
    return candidate


def _stage_workspace(public_dir: Path, workspace: Path) -> None:
    if workspace.exists():
        raise RQAgentRuntimeError(f"workspace already exists: {workspace}")
    workspace.mkdir(parents=True)
    expected = {
        "task.json",
        "history.jsonl",
        "instructions.md",
        "response.schema.json",
    }
    actual = {path.name for path in public_dir.iterdir() if path.is_file()}
    if actual != expected:
        raise RQAgentRuntimeError(
            f"public package file set changed: expected={sorted(expected)}, actual={sorted(actual)}"
        )
    for name in sorted(expected):
        shutil.copyfile(public_dir / name, workspace / name)


def _minimal_environment(allowlist: list[str]) -> dict[str, str]:
    baseline = {
        "PATH",
        "Path",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    allowed = baseline | set(allowlist)
    return {key: value for key, value in os.environ.items() if key in allowed}


def _embedded_case_prompt(template: str, workspace: Path) -> str:
    sections = [template.rstrip()]
    for name in EMBEDDED_INPUT_FILENAMES:
        content = (workspace / name).read_text(encoding="utf-8-sig").rstrip()
        sections.extend(
            [
                "",
                f"<benchmark_file name={json.dumps(name)}>",
                content,
                "</benchmark_file>",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _expanded_command(
    command: list[str],
    *,
    workspace: Path,
    output_path: Path,
    run_id: str,
    model: str,
    model_version: str,
    reasoning_effort: str,
) -> list[str]:
    replacements = {
        "{workspace}": str(workspace),
        "{output_path}": str(output_path),
        "{run_id}": run_id,
        "{model}": model,
        "{model_version}": model_version,
        "{reasoning_effort}": reasoning_effort,
    }
    expanded: list[str] = []
    for part in command:
        value = part
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        expanded.append(value)
    return expanded


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _execute_process(
    command: list[str],
    *,
    workspace: Path,
    prompt: str,
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> tuple[int, str, str]:
    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise RQAgentRuntimeError(
            f"Agent process timed out after {timeout_seconds}s"
        ) from exc
    return process.returncode, stdout, stderr


def _parse_stdout_json(stdout: str) -> dict[str, Any]:
    candidate = stdout.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RQAgentRuntimeError(
            "Agent stdout must contain exactly one JSON object"
        ) from exc
    if not isinstance(value, dict):
        raise RQAgentRuntimeError("Agent output must be a JSON object")
    return value


def run_isolated_agent_case(
    *,
    package_manifest_path: str | Path,
    agent_config: Mapping[str, Any],
    repetition: int,
    run_prompt_path: str | Path,
    run_root: str | Path,
    workspace_root: str | Path,
) -> dict[str, Any]:
    """Run one package in a fresh process and always purge its workspace."""

    package_path = Path(package_manifest_path).resolve()
    package = validate_package_manifest(read_json_object(package_path))
    public_dir = package_path.parent.parent / "public"
    prompt_path = Path(run_prompt_path).resolve()
    prompt_template = prompt_path.read_text(encoding="utf-8-sig").rstrip() + "\n"
    normalized = normalize_agent_config(
        agent_config,
        run_prompt_sha256=file_sha256(prompt_path),
        instructions_sha256=file_sha256(public_dir / "instructions.md"),
        response_schema_sha256=file_sha256(public_dir / "response.schema.json"),
    )
    manifest = build_run_manifest(
        package,
        normalized_agent_config=normalized,
        repetition=repetition,
    )
    run_id = manifest["run_id"]
    runs = Path(run_root).resolve()
    run_dir = runs / run_id
    freeze_record = run_dir / "phase_a" / "freeze_record.json"
    if freeze_record.is_file():
        existing = read_json_object(freeze_record)
        if (
            existing.get("run_id") == run_id
            and existing.get("agent_config_id") == manifest["agent_config_id"]
        ):
            return {
                "status": "SKIPPED_FROZEN",
                "run_id": run_id,
                "agent_config_id": manifest["agent_config_id"],
                "run_dir": run_dir,
            }
        raise RQAgentRuntimeError(f"conflicting frozen run exists at {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    private_path = run_dir / "private" / "run_manifest.json"
    if private_path.exists():
        existing_manifest = read_json_object(private_path)
        if canonical_sha256(existing_manifest) != canonical_sha256(manifest):
            raise RQAgentRuntimeError(f"conflicting run manifest exists at {private_path}")
    else:
        _atomic_json(private_path, manifest)

    workspace_base = Path(workspace_root).resolve()
    workspace = _safe_workspace_path(workspace_base, run_id)
    agent_dir = run_dir / "agent"
    output_path = workspace / normalized["output_filename"]
    command = _expanded_command(
        normalized["command"],
        workspace=workspace,
        output_path=output_path,
        run_id=run_id,
        model=normalized["model"],
        model_version=normalized["model_version"],
        reasoning_effort=normalized["reasoning_effort"],
    )
    record = {
        "schema_version": "rq-agent-process-record-v1",
        "run_id": run_id,
        "package_id": package["package_id"],
        "agent_config_id": manifest["agent_config_id"],
        "repetition": repetition,
        "started_at": _utc_now(),
        "command": command,
        "working_directory": "EPHEMERAL_ISOLATED_WORKSPACE",
        "environment_variable_names": normalized["environment_allowlist"],
        "status": "RUNNING",
    }
    try:
        _stage_workspace(public_dir, workspace)
        prompt = _embedded_case_prompt(prompt_template, workspace)
        returncode, stdout, stderr = _execute_process(
            command,
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=normalized["timeout_seconds"],
            environment=_minimal_environment(normalized["environment_allowlist"]),
        )
        _atomic_text(agent_dir / "stdout.txt", stdout)
        _atomic_text(agent_dir / "stderr.txt", stderr)
        record["returncode"] = returncode
        if returncode != 0:
            raise RQAgentRuntimeError(
                f"Agent process exited with status {returncode}"
            )
        if normalized["output_mode"] == "stdout_json":
            response = _parse_stdout_json(stdout)
        else:
            if not output_path.is_file():
                raise RQAgentRuntimeError(
                    f"Agent did not create {normalized['output_filename']}"
                )
            response = read_json_object(output_path)
        response_path = agent_dir / "agent_response.json"
        _atomic_json(response_path, response)
        frozen = freeze_phase_a_response(
            private_manifest_path=private_path,
            public_dir=public_dir,
            response_path=response_path,
            freeze_root=runs,
        )
        record.update(
            {
                "status": "FROZEN",
                "completed_at": _utc_now(),
                "response_sha256": frozen["freeze_record"]["response_sha256"],
            }
        )
        _atomic_json(agent_dir / "process_record.json", record)
        return {
            "status": "FROZEN",
            "run_id": run_id,
            "agent_config_id": manifest["agent_config_id"],
            "run_dir": run_dir,
            **frozen,
        }
    except Exception as exc:
        record.update(
            {
                "status": "FAILED",
                "completed_at": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        _atomic_json(agent_dir / "process_record.json", record)
        raise
    finally:
        if workspace.exists():
            checked = _safe_workspace_path(workspace_base, run_id)
            if checked == workspace:
                shutil.rmtree(checked)


def discover_package_manifests(package_root: str | Path) -> list[Path]:
    root = Path(package_root).resolve()
    return sorted(root.rglob("package_manifest.json"))


__all__ = [
    "RQAgentRuntimeError",
    "discover_package_manifests",
    "run_isolated_agent_case",
]

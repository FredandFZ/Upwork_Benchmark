"""Stable identities and manifests for isolated ReqMemBench Agent runs."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json
import re


PACKAGE_MANIFEST_SCHEMA_VERSION = "rq-private-package-manifest-v2"
RUN_MANIFEST_SCHEMA_VERSION = "rq-private-run-manifest-v2"
EXPERIMENT_CONFIG_SCHEMA_VERSION = "rq123-experiment-config-v1"


class RQRunConfigError(ValueError):
    """Raised when an experiment or run identity is incomplete."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQRunConfigError(f"cannot read JSON object {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQRunConfigError(f"{source} must contain a JSON object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQRunConfigError(f"{label} must be a non-empty string")
    return value.strip()


def validate_package_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    manifest = deepcopy(dict(value))
    if manifest.get("schema_version") != PACKAGE_MANIFEST_SCHEMA_VERSION:
        raise RQRunConfigError("unsupported package manifest schema")
    if manifest.get("manifest_kind") != "IMMUTABLE_INPUT_PACKAGE":
        raise RQRunConfigError("package manifest must be immutable input metadata")
    package_id = _text(manifest.get("package_id"), "package_id")
    if not re.fullmatch(r"pkg_[0-9a-f]{20}", package_id):
        raise RQRunConfigError("invalid package_id")
    if manifest.get("condition") not in {"C1", "C2"}:
        raise RQRunConfigError("package condition must be C1 or C2")
    public_files = manifest.get("public_files")
    if not isinstance(public_files, Mapping) or set(public_files) != {
        "task.json",
        "history.jsonl",
        "instructions.md",
        "response.schema.json",
    }:
        raise RQRunConfigError("package manifest has invalid public file hashes")
    return manifest


def normalize_agent_config(
    value: Mapping[str, Any],
    *,
    run_prompt_sha256: str,
    instructions_sha256: str,
    response_schema_sha256: str,
) -> dict[str, Any]:
    """Return the non-secret Agent configuration that defines a comparison."""

    provider = _text(value.get("provider"), "agent.provider")
    runtime_version = _text(
        value.get("runtime_version"), "agent.runtime_version"
    )
    model = _text(value.get("model"), "agent.model")
    model_version = _text(value.get("model_version"), "agent.model_version")
    reasoning_effort = _text(
        value.get("reasoning_effort"), "agent.reasoning_effort"
    )
    tool_policy = _text(value.get("tool_policy"), "agent.tool_policy")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part for part in command)
    ):
        raise RQRunConfigError("agent.command must be a non-empty string array")
    output_mode = value.get("output_mode", "stdout_json")
    if output_mode not in {"stdout_json", "workspace_file"}:
        raise RQRunConfigError(
            "agent.output_mode must be stdout_json or workspace_file"
        )
    output_filename = value.get("output_filename", "agent_response.json")
    if (
        not isinstance(output_filename, str)
        or Path(output_filename).name != output_filename
    ):
        raise RQRunConfigError("agent.output_filename must be a plain filename")
    timeout = value.get("timeout_seconds", 900)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise RQRunConfigError("agent.timeout_seconds must be a positive integer")
    env_allowlist = value.get("environment_allowlist", [])
    if not isinstance(env_allowlist, list) or any(
        not isinstance(name, str) or not name for name in env_allowlist
    ):
        raise RQRunConfigError("agent.environment_allowlist must be a string array")
    return {
        "provider": provider,
        "runtime_version": runtime_version,
        "model": model,
        "model_version": model_version,
        "reasoning_effort": reasoning_effort,
        "tool_policy": tool_policy,
        "session_isolation": "NEW_PROCESS_PER_TARGET_CONDITION",
        "persistent_conversation": False,
        "command": list(command),
        "output_mode": output_mode,
        "output_filename": output_filename,
        "timeout_seconds": timeout,
        "environment_allowlist": sorted(set(env_allowlist)),
        "run_prompt_sha256": run_prompt_sha256,
        "instructions_sha256": instructions_sha256,
        "response_schema_sha256": response_schema_sha256,
    }


def agent_config_id(config: Mapping[str, Any]) -> str:
    return "agentcfg_" + canonical_sha256(config)[:20]


def agent_run_id(
    package_id: str,
    config_id: str,
    repetition: int,
) -> str:
    if not re.fullmatch(r"pkg_[0-9a-f]{20}", package_id):
        raise RQRunConfigError("invalid package_id")
    if not re.fullmatch(r"agentcfg_[0-9a-f]{20}", config_id):
        raise RQRunConfigError("invalid agent_config_id")
    if isinstance(repetition, bool) or not isinstance(repetition, int) or repetition < 1:
        raise RQRunConfigError("repetition must be a positive integer")
    return "run_" + canonical_sha256(
        {
            "package_id": package_id,
            "agent_config_id": config_id,
            "repetition": repetition,
        }
    )[:20]


def build_run_manifest(
    package_manifest: Mapping[str, Any],
    *,
    normalized_agent_config: Mapping[str, Any],
    repetition: int,
) -> dict[str, Any]:
    package = validate_package_manifest(package_manifest)
    config = deepcopy(dict(normalized_agent_config))
    config_id = agent_config_id(config)
    run_id = agent_run_id(package["package_id"], config_id, repetition)
    inherited = {
        key: deepcopy(value)
        for key, value in package.items()
        if key
        not in {
            "schema_version",
            "manifest_kind",
            "phase_gate_policy",
        }
    }
    policy = package.get("phase_gate_policy")
    if not isinstance(policy, Mapping):
        raise RQRunConfigError("package manifest has no phase_gate_policy")
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "ISOLATED_AGENT_RUN",
        "run_id": run_id,
        **inherited,
        "package_manifest_sha256": canonical_sha256(package),
        "agent_config_id": config_id,
        "agent_config": config,
        "repetition": repetition,
        "phase_gate": {
            **deepcopy(dict(policy)),
            "phase_a_response_sha256": None,
            "phase_a_frozen_at": None,
        },
    }


def judge_config_id(value: Mapping[str, Any]) -> str:
    """Hash a secret-free, fully specified Judge configuration."""

    config = deepcopy(dict(value))
    for forbidden in ("api_key", "token", "password", "secret"):
        if forbidden in config:
            raise RQRunConfigError(
                f"judge config identity must not contain secret field {forbidden!r}"
            )
    required = ("provider", "model", "model_version", "reasoning_effort")
    for field in required:
        _text(config.get(field), f"judge.{field}")
    return "judgecfg_" + canonical_sha256(config)[:20]


__all__ = [
    "EXPERIMENT_CONFIG_SCHEMA_VERSION",
    "PACKAGE_MANIFEST_SCHEMA_VERSION",
    "RQRunConfigError",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "agent_config_id",
    "agent_run_id",
    "build_run_manifest",
    "canonical_sha256",
    "file_sha256",
    "judge_config_id",
    "normalize_agent_config",
    "read_json_object",
    "validate_package_manifest",
]

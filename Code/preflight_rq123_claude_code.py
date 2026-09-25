#!/usr/bin/env python3
"""Validate a Claude Code RQ1--RQ3 experiment without running the model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

try:  # Package import in tests; script import in CLI use.
    from .rq_agent_runtime import discover_package_manifests
    from .rq_run_identity import (
        EXPERIMENT_CONFIG_SCHEMA_VERSION,
        RQRunConfigError,
        file_sha256,
        read_json_object,
        validate_package_manifest,
    )
except ImportError:  # pragma: no cover
    from rq_agent_runtime import discover_package_manifests
    from rq_run_identity import (
        EXPERIMENT_CONFIG_SCHEMA_VERSION,
        RQRunConfigError,
        file_sha256,
        read_json_object,
        validate_package_manifest,
    )


MINIMUM_CLAUDE_CODE_VERSION = (2, 1, 259)
REQUIRED_FLAGS = {
    "-p",
    "--restricted",
    "--no-session-persistence",
    "--disable-slash-commands",
    "--no-chrome",
}
FORBIDDEN_SESSION_FLAGS = {"--continue", "-c", "--resume", "-r"}
REQUIRED_OPTIONS = {
    "--permission-mode": "dontAsk",
    "--permission-prompts": "none",
    "--tools": "",
    "--disallowedTools": "mcp__*",
    "--model": "{model_version}",
    "--effort": "{reasoning_effort}",
    "--output-format": "json",
    "--json-schema": "{response_schema_json}",
}


class ClaudePreflightError(RuntimeError):
    """Claude Code cannot safely run this benchmark configuration."""


def _option_value(command: list[str], flag: str) -> str | None:
    try:
        index = command.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return command[index + 1]


def validate_claude_agent_config(config: Mapping[str, Any]) -> list[str]:
    agent = config.get("agent")
    if not isinstance(agent, Mapping):
        raise ClaudePreflightError("experiment config has no agent object")
    if agent.get("provider") != "claude_code_cli":
        raise ClaudePreflightError("agent.provider must be claude_code_cli")
    if agent.get("output_mode") != "claude_structured_json":
        raise ClaudePreflightError(
            "Claude Code requires output_mode=claude_structured_json"
        )
    command = agent.get("command")
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        raise ClaudePreflightError("agent.command must be a string array")
    missing = sorted(REQUIRED_FLAGS.difference(command))
    if missing:
        raise ClaudePreflightError(f"Claude command is missing flags: {missing}")
    forbidden = sorted(FORBIDDEN_SESSION_FLAGS.intersection(command))
    if forbidden:
        raise ClaudePreflightError(
            f"Claude command must not resume prior sessions: {forbidden}"
        )
    for flag, expected in REQUIRED_OPTIONS.items():
        actual = _option_value(command, flag)
        if actual != expected:
            raise ClaudePreflightError(
                f"Claude command requires {flag} {expected!r}, got {actual!r}"
            )
    for field in ("runtime_version", "model", "model_version"):
        value = agent.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ClaudePreflightError(f"agent.{field} must be set")
        if "replace-with" in value:
            raise ClaudePreflightError(f"replace placeholder agent.{field} before running")
    return command


def _version_tuple(text: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", text)
    if match is None:
        raise ClaudePreflightError(f"cannot parse Claude Code version from {text!r}")
    return tuple(int(value) for value in match.groups())


def _run_check(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _validate_packages(package_root: Path) -> int:
    manifests = discover_package_manifests(package_root)
    if not manifests:
        raise ClaudePreflightError(f"no package manifests below {package_root}")
    for manifest_path in manifests:
        package = validate_package_manifest(read_json_object(manifest_path))
        for rq_id, source in package.get("source_instances", {}).items():
            if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
                raise ClaudePreflightError(
                    f"invalid {rq_id} source record in {manifest_path}"
                )
            path = Path(source["path"])
            if not path.is_file() or file_sha256(path) != source.get("file_sha256"):
                raise ClaudePreflightError(
                    f"stale cross-device source path in {manifest_path}; "
                    "rematerialize packages on this device"
                )
    return len(manifests)


def _args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=root / "outputs_new" / "rq_agent_inputs",
    )
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Validate files and flags without calling `claude auth status`.",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        config = read_json_object(args.config)
        if config.get("schema_version") != EXPERIMENT_CONFIG_SCHEMA_VERSION:
            raise ClaudePreflightError("unsupported experiment config schema")
        command = validate_claude_agent_config(config)
        executable = shutil.which(command[0])
        if executable is None:
            raise ClaudePreflightError(
                f"Claude Code executable is not on PATH: {command[0]!r}"
            )
        version_result = _run_check([executable, "--version"])
        version_text = (version_result.stdout or version_result.stderr).strip()
        if version_result.returncode != 0:
            raise ClaudePreflightError(f"`claude --version` failed: {version_text}")
        version = _version_tuple(version_text)
        if version < MINIMUM_CLAUDE_CODE_VERSION:
            required = ".".join(str(value) for value in MINIMUM_CLAUDE_CODE_VERSION)
            raise ClaudePreflightError(
                f"Claude Code {version_text} is too old; require >= {required}"
            )
        configured_version = _version_tuple(str(config["agent"]["runtime_version"]))
        if configured_version != version:
            raise ClaudePreflightError(
                "agent.runtime_version does not match `claude --version`: "
                f"configured={config['agent']['runtime_version']!r}, "
                f"installed={version_text!r}"
            )
        if not args.skip_auth_check:
            auth = _run_check([executable, "auth", "status"])
            if auth.returncode != 0:
                raise ClaudePreflightError(
                    "Claude Code is not authenticated; run `claude auth login` first"
                )
        package_count = _validate_packages(args.package_root.resolve())
        print(
            json.dumps(
                {
                    "status": "READY_NOT_RUN",
                    "claude_code_version": version_text,
                    "package_count": package_count,
                    "config": str(args.config.resolve()),
                    "package_root": str(args.package_root.resolve()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (
        OSError,
        subprocess.SubprocessError,
        RQRunConfigError,
        ClaudePreflightError,
    ) as exc:
        print(f"Claude Code RQ preflight failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

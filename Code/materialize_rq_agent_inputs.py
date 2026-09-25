#!/usr/bin/env python3
"""Materialize leakage-safe Phase A Agent workspaces from RQ instances."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rq_agent_input import (
    CONDITIONS,
    RQMaterializationError,
    materialize_reasoning_input,
    stage_phase_a_workspace,
    write_materialized_input,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQMaterializationError(f"cannot read project manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQMaterializationError(f"{path} must contain a JSON object")
    return value


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Create one public Phase A workspace per target/condition while "
            "keeping RQ Gold and run metadata in a separate private directory."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--project-dir",
        type=Path,
        help="Project RQ instance directory containing rq_instance_manifest.json.",
    )
    source.add_argument(
        "--project-id",
        help="Project ID resolved below --stage2-root.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--target-id", help="Materialize one target.")
    target.add_argument(
        "--all-targets",
        action="store_true",
        help="Materialize every target listed by the project manifest.",
    )
    parser.add_argument(
        "--condition",
        choices=CONDITIONS,
        action="append",
        help=(
            "Condition to materialize; repeat for both conditions. Defaults to "
            "all available conditions."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "formal"),
        default="smoke",
        help="Formal mode refuses instances whose reviewed Gold is not frozen.",
    )
    parser.add_argument(
        "--stage2-root",
        type=Path,
        default=root / "outputs" / "stage2",
        help="Stage 2 root used with --project-id.",
    )
    parser.add_argument(
        "--instructions",
        type=Path,
        default=root / "prompt" / "rq_agent_instructions.md",
        help="Public Phase A instructions.",
    )
    parser.add_argument(
        "--response-schema",
        type=Path,
        default=root / "schema" / "rq_agent_response.schema.json",
        help="Public unified response JSON Schema.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "outputs" / "rq_agent_inputs",
        help="Root for separated public/private run artifacts.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        help=(
            "Optionally copy each public package into a fresh opaque <package_id>/ "
            "workspace suitable for an isolated Agent launch."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and hash packages in memory without writing files.",
    )
    args = parser.parse_args()
    if args.validate_only and args.workspace_root is not None:
        parser.error("--workspace-root cannot be used with --validate-only")
    return args


def _target_ids(manifest: dict[str, Any], requested: str | None) -> list[str]:
    if requested is not None:
        return [requested]
    rows = manifest.get("targets")
    if not isinstance(rows, list):
        raise RQMaterializationError("project manifest.targets must be an array")
    target_ids = [
        row.get("target_id")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("target_id"), str)
    ]
    if len(target_ids) != len(rows) or len(target_ids) != len(set(target_ids)):
        raise RQMaterializationError("project manifest has invalid target IDs")
    return target_ids


def main() -> int:
    args = parse_args()
    project_dir = (
        args.project_dir
        if args.project_dir is not None
        else args.stage2_root / str(args.project_id)
    )
    try:
        manifest = _read_manifest(project_dir / "rq_instance_manifest.json")
        target_ids = _target_ids(manifest, args.target_id)
        conditions = tuple(dict.fromkeys(args.condition or CONDITIONS))
        completed: list[tuple[str, str, str, Path | None]] = []
        for target_id in target_ids:
            for condition in conditions:
                materialized = materialize_reasoning_input(
                    project_dir,
                    target_id,
                    condition,
                    instructions_path=args.instructions,
                    response_schema_path=args.response_schema,
                    mode=args.mode,
                )
                workspace = None
                if not args.validate_only:
                    write_materialized_input(materialized, args.output_root)
                    if args.workspace_root is not None:
                        workspace = stage_phase_a_workspace(
                            materialized, args.workspace_root
                        )
                completed.append(
                    (target_id, condition, materialized["package_id"], workspace)
                )
        action = "validated" if args.validate_only else "materialized"
        print(
            f"{manifest.get('project_id')}: {action} {len(completed)} "
            f"Phase A package(s) in {args.mode.upper()} mode"
        )
        for target_id, condition, package_id, workspace in completed:
            suffix = f" -> {workspace}" if workspace is not None else ""
            print(f"  {target_id}/{condition}: {package_id}{suffix}")
        return 0
    except (OSError, RQMaterializationError) as exc:
        print(f"RQ Agent input materialization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

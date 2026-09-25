#!/usr/bin/env python3
"""Materialize every formal RQ1--RQ3 target/condition input package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rq_agent_input import (
    RQMaterializationError,
    materialize_reasoning_input,
    write_materialized_input,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RQMaterializationError(f"{path} must contain a JSON object")
    return value


def _args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage2-root", type=Path, default=root / "outputs_new" / "stage2"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "outputs_new" / "rq_agent_inputs",
    )
    parser.add_argument(
        "--instructions",
        type=Path,
        default=root / "prompt" / "rq_agent_instructions.md",
    )
    parser.add_argument(
        "--response-schema",
        type=Path,
        default=root / "schema" / "rq_agent_response.schema.json",
    )
    parser.add_argument("--project-id", action="append")
    parser.add_argument(
        "--case",
        action="append",
        metavar="PROJECT_ID:TARGET_ID",
        help=(
            "Materialize only the named target, including both C1 and C2. "
            "May be repeated."
        ),
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def _parse_cases(values: list[str] | None) -> set[tuple[str, str]]:
    cases: set[tuple[str, str]] = set()
    for value in values or []:
        project_id, separator, target_id = value.partition(":")
        if not separator or not project_id or not target_id:
            raise RQMaterializationError(
                "--case must use PROJECT_ID:TARGET_ID"
            )
        cases.add((project_id, target_id))
    return cases


def main() -> int:
    args = _args()
    try:
        requested = set(args.project_id or [])
        requested_cases = _parse_cases(args.case)
        requested.update(project_id for project_id, _ in requested_cases)
        project_dirs = sorted(
            path
            for path in args.stage2_root.iterdir()
            if path.is_dir()
            and (path / "rq_instance_manifest.json").is_file()
            and (not requested or path.name in requested)
        )
        if requested.difference(path.name for path in project_dirs):
            missing = sorted(requested.difference(path.name for path in project_dirs))
            raise RQMaterializationError(f"unknown project IDs: {missing}")
        counts = {"projects": 0, "targets": 0, "packages": 0}
        found_cases: set[tuple[str, str]] = set()
        for project_dir in project_dirs:
            manifest = _read(project_dir / "rq_instance_manifest.json")
            targets = manifest.get("targets")
            if not isinstance(targets, list):
                raise RQMaterializationError(
                    f"{project_dir} manifest.targets must be an array"
                )
            if not targets:
                continue
            selected_target_count = 0
            for target in targets:
                target_id = target.get("target_id") if isinstance(target, dict) else None
                if not isinstance(target_id, str):
                    raise RQMaterializationError(
                        f"{project_dir} has a target without a valid target_id"
                    )
                case = (project_dir.name, target_id)
                if requested_cases and case not in requested_cases:
                    continue
                found_cases.add(case)
                for condition in ("C1", "C2"):
                    package = materialize_reasoning_input(
                        project_dir,
                        target_id,
                        condition,
                        instructions_path=args.instructions,
                        response_schema_path=args.response_schema,
                        mode="formal",
                    )
                    if not args.validate_only:
                        write_materialized_input(package, args.output_root)
                    counts["packages"] += 1
                counts["targets"] += 1
                selected_target_count += 1
            if selected_target_count:
                counts["projects"] += 1
        missing_cases = sorted(requested_cases.difference(found_cases))
        if missing_cases:
            raise RQMaterializationError(
                f"unknown target cases: {missing_cases}"
            )
        print(
            json.dumps(
                {
                    "mode": "VALIDATE_ONLY" if args.validate_only else "MATERIALIZED",
                    **counts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, json.JSONDecodeError, RQMaterializationError) as exc:
        print(f"RQ1--RQ3 release materialization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

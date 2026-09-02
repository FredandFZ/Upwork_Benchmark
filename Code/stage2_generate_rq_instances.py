#!/usr/bin/env python3
"""Generate researcher-side RQ1--RQ4 instances for one ReqMemBench project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stage2.rq_instances import (
    RQ_IDS,
    RQInstanceError,
    build_project_manifest,
    build_rq_indexes,
    build_rq_instances,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RQInstanceError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQInstanceError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    """Write JSON atomically so a failed run cannot leave a partial instance."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Construct RQ1--RQ4 instance JSON files from Task Gold, the "
            "Requirement State Graph, normalized history, and RQ4 Code Environment."
        )
    )
    parser.add_argument(
        "--project-id",
        help="Project ID used with the default input/output directory layout.",
    )
    parser.add_argument("--gold-states", type=Path, help="Path to gold_states.json.")
    parser.add_argument(
        "--state-graph", type=Path, help="Path to requirement_state_graph.json."
    )
    parser.add_argument(
        "--messages", type=Path, help="Path to Stage 1 normalized_project.json."
    )
    parser.add_argument(
        "--code-environment-dir",
        type=Path,
        help="Path to Code Environment/<project_id>.",
    )
    parser.add_argument(
        "--stage2-root",
        type=Path,
        default=root / "outputs" / "stage2",
        help="Default Stage 2 root (default: outputs/stage2).",
    )
    parser.add_argument(
        "--stage1-run-root",
        type=Path,
        default=root / "outputs" / "stage1_runs",
        help="Default normalized-history root (default: outputs/stage1_runs).",
    )
    parser.add_argument(
        "--code-environment-root",
        type=Path,
        default=root / "Code Environment",
        help="Default Code Environment root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Project output directory. Defaults to outputs/stage2/<project_id>; "
            "RQ1, RQ2, RQ3, and RQ4 are created directly inside it."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Build and validate entirely in memory without writing files.",
    )
    args = parser.parse_args()
    if args.project_id is None and args.gold_states is None:
        parser.error("provide --project-id or an explicit --gold-states path")
    return args


def _resolve_paths(
    args: argparse.Namespace,
) -> tuple[str, Path, Path, Path, Path, Path]:
    project_id = str(args.project_id) if args.project_id is not None else ""
    gold_path = args.gold_states
    if not project_id:
        gold_value = read_json(gold_path)
        project_value = gold_value.get("project_id")
        if not isinstance(project_value, str) or not project_value.strip():
            raise RQInstanceError("explicit Gold State has no valid project_id")
        project_id = project_value
    gold_path = gold_path or args.stage2_root / project_id / "gold_states.json"
    graph_path = (
        args.state_graph
        or args.stage2_root / project_id / "requirement_state_graph.json"
    )
    messages_path = (
        args.messages
        or args.stage1_run_root / project_id / "normalized_project.json"
    )
    code_environment_dir = (
        args.code_environment_dir or args.code_environment_root / project_id
    )
    output_dir = args.output_dir or args.stage2_root / project_id
    return (
        project_id,
        gold_path,
        graph_path,
        messages_path,
        code_environment_dir,
        output_dir,
    )


def _render_summary(
    project_id: str,
    indexes: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    validate_only: bool,
) -> str:
    counts = ", ".join(
        f"{rq_id}={indexes[rq_id]['instance_count']}" for rq_id in RQ_IDS
    )
    action = "validated" if validate_only else "generated"
    suffix = " (no files written)" if validate_only else f" -> {output_dir}"
    return f"{project_id}: {action} RQ instances ({counts}){suffix}"


def main() -> int:
    args = parse_args()
    try:
        (
            project_id,
            gold_path,
            graph_path,
            messages_path,
            code_environment_dir,
            output_dir,
        ) = _resolve_paths(args)
        gold_states = read_json(gold_path)
        state_graph = read_json(graph_path)
        normalized_project = read_json(messages_path)
        source_paths = {
            "gold_states": gold_path,
            "requirement_state_graph": graph_path,
            "normalized_project": messages_path,
            "code_environment": code_environment_dir,
        }
        collections = build_rq_instances(
            gold_states,
            state_graph,
            normalized_project,
            code_environment_dir=code_environment_dir,
            source_paths=source_paths,
            workspace_root=repo_root(),
        )
        indexes = build_rq_indexes(collections)
        manifest = build_project_manifest(
            collections,
            indexes,
            project_id=project_id,
            source_paths=source_paths,
            workspace_root=repo_root(),
            output_dir=output_dir,
        )
        if not args.validate_only:
            for rq_id in RQ_IDS:
                rq_dir = output_dir / rq_id
                for instance in collections[rq_id]:
                    write_json(rq_dir / f"{instance['instance_id']}.json", instance)
                write_json(rq_dir / "index.json", indexes[rq_id])
            write_json(output_dir / "rq_instance_manifest.json", manifest)
        print(
            _render_summary(
                project_id,
                indexes,
                output_dir,
                validate_only=args.validate_only,
            )
        )
        return 0
    except (OSError, RQInstanceError) as exc:
        print(f"RQ instance construction failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for deterministic task-centered Gold State construction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stage2.gold_state import (
    TaskGoldError,
    audit_event_provenance,
    build_gold_states,
    build_statistics,
    load_selection_config,
    validate_gold_states,
)


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON without importing the Stage 1 runtime."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    """Atomically write human-readable UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Build task-centered gold_states.json."
    )
    parser.add_argument(
        "--state-graph",
        type=Path,
        help="Explicit requirement_state_graph.json. With no path, --project-id is required.",
    )
    parser.add_argument(
        "--stage1-source",
        "--annotation",
        dest="stage1_source",
        type=Path,
        help=(
            "Stage 1 message/provenance source. Supports upgrade-run verified_events.json, "
            "normalized_project.json, or an assembled annotation."
        ),
    )
    parser.add_argument("--project-id", help="Project ID used with the default roots.")
    parser.add_argument(
        "--graph-root",
        type=Path,
        default=root / "outputs" / "stage2",
        help="Root containing <project_id>/requirement_state_graph.json.",
    )
    parser.add_argument(
        "--stage1-root",
        type=Path,
        default=root / "outputs" / "stage1_upgrade_runs",
        help="Root containing <project_id>/normalized_project.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory; defaults to the State Graph's directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "Code" / "config" / "stage2_gold_state.json",
        help="Task selection configuration JSON.",
    )
    parser.add_argument(
        "--include-execution-only-tasks",
        action="store_true",
        help="Override the config and select Client execution-only messages.",
    )
    parser.add_argument(
        "--audit-event-provenance",
        action="store_true",
        help="Require graph Event IDs/types/messages to match verified Stage 1 Events.",
    )
    parser.add_argument(
        "--event-provenance-source",
        type=Path,
        help=(
            "Event-bearing Stage 1 source for --audit-event-provenance; defaults to "
            "<stage1-root>/<project_id>/verified_events.json."
        ),
    )
    args = parser.parse_args()
    if args.state_graph is None and args.project_id is None:
        parser.error("provide --state-graph or --project-id")
    if args.state_graph is not None and args.project_id is not None:
        parser.error("--state-graph and --project-id are mutually exclusive")
    return args


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path]:
    if args.state_graph is not None:
        graph_path = args.state_graph
        graph = read_json(graph_path)
        project_id = str(graph.get("project_id"))
    else:
        project_id = str(args.project_id)
        graph_path = args.graph_root / project_id / "requirement_state_graph.json"
    stage1_path = (
        args.stage1_source
        if args.stage1_source is not None
        else args.stage1_root / project_id / "normalized_project.json"
    )
    output_dir = args.output_dir if args.output_dir is not None else graph_path.parent
    provenance_path = (
        args.event_provenance_source
        if args.event_provenance_source is not None
        else args.stage1_root / project_id / "verified_events.json"
    )
    return graph_path, stage1_path, provenance_path, output_dir, args.config


def main() -> int:
    args = parse_args()
    try:
        (
            graph_path,
            stage1_path,
            provenance_path,
            output_dir,
            config_path,
        ) = _paths(args)
        state_graph = read_json(graph_path)
        if args.stage1_source is not None:
            stage1_source = read_json(stage1_path)
        else:
            stage1_source = read_json(stage1_path) if stage1_path.is_file() else None
        selection_config = load_selection_config(config_path)
        gold_states = build_gold_states(
            stage1_source,
            state_graph,
            include_execution_only_tasks=(
                True if args.include_execution_only_tasks else None
            ),
            selection_config=selection_config,
        )
        gold_errors = validate_gold_states(gold_states, state_graph)
        provenance_errors = (
            audit_event_provenance(read_json(provenance_path), state_graph)
            if args.audit_event_provenance
            else []
        )
        statistics = build_statistics(
            state_graph,
            gold_states,
            provenance_issue_count=len(provenance_errors),
        )
        validation_report = {
            "project_id": gold_states["project_id"],
            "inputs": {
                "state_graph": str(graph_path),
                "task_message_source": (
                    str(stage1_path) if stage1_source is not None else None
                ),
                "task_selection_config": str(config_path),
                "event_provenance_source": (
                    str(provenance_path) if args.audit_event_provenance else None
                ),
            },
            "status": (
                "FAILED_ARTIFACT_VALIDATION"
                if gold_errors
                else "FAILED_PROVENANCE_VALIDATION"
                if provenance_errors
                else "PASSED"
            ),
            "artifact_validation": {
                "status": "PASSED" if not gold_errors else "FAILED",
                "gold_state_errors": gold_errors,
            },
            "provenance_validation": {
                "status": (
                    "NOT_RUN"
                    if not args.audit_event_provenance
                    else "PASSED"
                    if not provenance_errors
                    else "FAILED"
                ),
                "errors": provenance_errors,
            },
            "statistics": statistics,
        }
        validation_path = output_dir / "gold_state_validation.json"
        write_json(validation_path, validation_report)
        if gold_errors:
            raise TaskGoldError("generated Gold State failed internal validation")
        if provenance_errors:
            print(
                f"Task Gold generation stopped: {len(provenance_errors)} graph/Stage-1 "
                f"provenance error(s); see {validation_path}",
                file=sys.stderr,
            )
            return 2
        write_json(output_dir / "gold_states.json", gold_states)
        print(
            f"{gold_states['project_id']}: {statistics['task_candidates']} Task Gold States, "
            f"{statistics['multi_requirement_tasks']} multi-Requirement Tasks, "
            f"event-provenance audit={'on' if args.audit_event_provenance else 'off'} "
            f"-> {output_dir}"
        )
    except (OSError, ValueError, TaskGoldError) as exc:
        print(f"Task Gold generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

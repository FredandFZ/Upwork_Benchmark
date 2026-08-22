"""CLI for task-centered Gold State and RQ1--RQ4 construction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stage1.storage import read_json, write_json
from stage2.task_gold import (
    TaskGoldError,
    audit_event_provenance,
    build_evaluation_instances,
    build_gold_states,
    build_statistics,
    validate_evaluation_instances,
    validate_gold_states,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Build task-centered gold_states.json and RQ1--RQ4 instances."
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
        "--include-execution-only-tasks",
        action="store_true",
        help="Also select Client messages containing only execution Events.",
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


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
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
    return graph_path, stage1_path, provenance_path, output_dir


def main() -> int:
    args = parse_args()
    try:
        graph_path, stage1_path, provenance_path, output_dir = _paths(args)
        state_graph = read_json(graph_path)
        stage1_source = read_json(stage1_path)
        gold_states = build_gold_states(
            stage1_source,
            state_graph,
            include_execution_only_tasks=args.include_execution_only_tasks,
        )
        evaluation_instances = build_evaluation_instances(gold_states, state_graph)
        gold_errors = validate_gold_states(gold_states, state_graph)
        rq_errors = validate_evaluation_instances(
            evaluation_instances, gold_states, state_graph
        )
        provenance_errors = (
            audit_event_provenance(read_json(provenance_path), state_graph)
            if args.audit_event_provenance
            else []
        )
        statistics = build_statistics(
            state_graph,
            gold_states,
            evaluation_instances,
            provenance_issue_count=len(provenance_errors),
        )
        validation_report = {
            "project_id": gold_states["project_id"],
            "inputs": {
                "state_graph": str(graph_path),
                "task_message_source": str(stage1_path),
                "event_provenance_source": (
                    str(provenance_path) if args.audit_event_provenance else None
                ),
            },
            "status": (
                "FAILED_ARTIFACT_VALIDATION"
                if gold_errors or rq_errors
                else "FAILED_PROVENANCE_VALIDATION"
                if provenance_errors
                else "PASSED"
            ),
            "artifact_validation": {
                "status": "PASSED" if not gold_errors and not rq_errors else "FAILED",
                "gold_state_errors": gold_errors,
                "rq_instance_errors": rq_errors,
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
        write_json(output_dir / "task_gold_validation.json", validation_report)
        if gold_errors or rq_errors:
            raise TaskGoldError("generated artifacts failed internal validation")
        if provenance_errors:
            print(
                f"Task Gold generation stopped: {len(provenance_errors)} graph/Stage-1 "
                f"provenance error(s); see {output_dir / 'task_gold_validation.json'}",
                file=sys.stderr,
            )
            return 2
        write_json(output_dir / "gold_states.json", gold_states)
        write_json(
            output_dir / "evaluation_instances" / "rq1_rq4_instances.json",
            evaluation_instances,
        )
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

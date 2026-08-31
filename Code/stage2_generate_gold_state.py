"""CLI for LLM target-time selection and deterministic Gold State replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from stage1.api_client import Stage1ApiClient
from stage1.storage import append_jsonl, read_jsonl
from stage2.gold_state import (
    MAX_AI_SELECTION_SCORE,
    TargetSelectionConfig,
    TaskGoldError,
    apply_coverage_and_deduplication,
    build_candidate_contexts,
    build_candidate_packets,
    build_gold_states,
    build_statistics,
    evaluate_candidate_packets,
    finalize_ai_selected_targets,
    finalize_selected_targets,
    generate_candidate_tasks,
    load_selection_config,
    select_ai_candidates_by_score,
    select_recommended_candidates,
    validate_gold_states,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Generate target-time Candidates, evaluate them with the LLM API, "
            "and finalize deterministic Gold States through human review or "
            "explicit AI auto-acceptance."
        )
    )
    parser.add_argument("--project-id", help="Project ID used with default input roots.")
    parser.add_argument("--annotation", type=Path, help="Canonical Stage 1 annotation JSON.")
    parser.add_argument(
        "--messages", type=Path, help="Stage 1 normalized_project.json message catalog."
    )
    parser.add_argument(
        "--state-graph", type=Path, help="Requirement State Graph JSON."
    )
    parser.add_argument(
        "--annotation-root",
        type=Path,
        default=root / "outputs" / "stage1_annotations",
    )
    parser.add_argument(
        "--stage1-run-root",
        type=Path,
        default=root / "outputs" / "stage1_runs",
    )
    parser.add_argument(
        "--graph-root", type=Path, default=root / "outputs" / "stage2"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory; defaults to outputs/stage2/<project_id>.",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=root / "prompt" / "t_selection_prompt.md",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "Code" / "config" / "stage2_gold_state.json",
    )
    parser.add_argument("--model", help="Override config.model.")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        help="Override config.reasoning_effort.",
    )
    parser.add_argument(
        "--max-concurrent-requests", type=int, help="Override config concurrency."
    )
    parser.add_argument("--retries", type=int, help="Override config retries.")
    parser.add_argument("--timeout", type=float, help="Override request timeout seconds.")
    parser.add_argument(
        "--max-selected-targets", type=int, help="Override the automatic selection cap."
    )
    parser.add_argument(
        "--include-execution-only-tasks",
        action="store_true",
        help="Include messages whose Events only update execution state.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write Candidate/Context/Packet artifacts without calling the LLM API.",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Do not reuse matching validated LLM evaluations.",
    )
    parser.set_defaults(resume=True)
    parser.add_argument(
        "--force-evaluation",
        action="store_true",
        help="Re-evaluate every Candidate even when fingerprints match.",
    )
    parser.add_argument(
        "--human-review-file",
        type=Path,
        help="Completed target_time_human_review.json used by --finalize.",
    )
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Apply human review and write selected_target_times.json and Gold States.",
    )
    parser.add_argument(
        "--auto-accept-ai",
        action="store_true",
        help=(
            "Skip human ACCEPT/REJECT review and immediately finalize every valid, "
            "history-sensitive AI recommendation at or above --score-threshold."
        ),
    )
    parser.add_argument(
        "--score-threshold",
        type=int,
        default=7,
        metavar="0-10",
        help=(
            "AI auto-accept cutoff on the derived 0-10 score (default: 7; "
            "LOW=0, MEDIUM=1, HIGH=2 across five dimensions)."
        ),
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for the existing internal API client.",
    )
    args = parser.parse_args()
    explicit_inputs = (args.annotation, args.messages, args.state_graph)
    if args.project_id is None and not all(path is not None for path in explicit_inputs):
        parser.error(
            "provide --project-id, or provide --annotation, --messages, and --state-graph"
        )
    if args.prepare_only and (args.finalize or args.auto_accept_ai):
        parser.error(
            "--prepare-only cannot be combined with --finalize or --auto-accept-ai"
        )
    if args.finalize and args.auto_accept_ai:
        parser.error("--finalize and --auto-accept-ai are mutually exclusive")
    if args.finalize and args.human_review_file is None:
        parser.error("--finalize requires --human-review-file")
    if args.auto_accept_ai and args.human_review_file is not None:
        parser.error("--auto-accept-ai does not use --human-review-file")
    if not 0 <= args.score_threshold <= MAX_AI_SELECTION_SCORE:
        parser.error(
            f"--score-threshold must be from 0 to {MAX_AI_SELECTION_SCORE}"
        )
    return args


def _resolve_paths(args: argparse.Namespace) -> tuple[str, Path, Path, Path, Path]:
    project_id = str(args.project_id) if args.project_id is not None else ""
    graph_path = args.state_graph
    if not project_id:
        graph_value = read_json(graph_path)
        project_id = str(graph_value.get("project_id"))
        if not project_id or project_id == "None":
            raise TaskGoldError("State Graph has no valid project_id")
    annotation_path = (
        args.annotation
        if args.annotation is not None
        else args.annotation_root / f"{project_id}_stage1_annotation.json"
    )
    messages_path = (
        args.messages
        if args.messages is not None
        else args.stage1_run_root / project_id / "normalized_project.json"
    )
    graph_path = (
        graph_path
        if graph_path is not None
        else args.graph_root / project_id / "requirement_state_graph.json"
    )
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else args.graph_root / project_id
    )
    return project_id, annotation_path, messages_path, graph_path, output_dir


def _override_config(
    config: TargetSelectionConfig, args: argparse.Namespace
) -> TargetSelectionConfig:
    overrides: dict[str, Any] = {}
    for argument, field_name in (
        (args.model, "model"),
        (args.reasoning_effort, "reasoning_effort"),
        (args.max_concurrent_requests, "max_concurrent_requests"),
        (args.retries, "retries"),
        (args.timeout, "timeout_seconds"),
        (args.max_selected_targets, "max_selected_targets"),
    ):
        if argument is not None:
            overrides[field_name] = argument
    if args.include_execution_only_tasks:
        overrides["include_execution_only_tasks"] = True
    merged = replace(config, **overrides)
    # Re-run the same validation after CLI overrides.
    return TargetSelectionConfig.from_mapping(
        {
            "candidate_event_types": list(merged.candidate_event_types),
            "include_introduce_candidates": merged.include_introduce_candidates,
            "include_execution_only_tasks": merged.include_execution_only_tasks,
            "allowed_rq_targets": list(merged.allowed_rq_targets),
            "max_selected_targets": merged.max_selected_targets,
            "model": merged.model,
            "reasoning_effort": merged.reasoning_effort,
            "max_concurrent_requests": merged.max_concurrent_requests,
            "retries": merged.retries,
            "timeout_seconds": merged.timeout_seconds,
            "max_reason_length": merged.max_reason_length,
        }
    )


def _review_template(auto_selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "target-time-human-review-v1",
        "project_id": auto_selection["project_id"],
        "instructions": (
            "Replace each empty decision with ACCEPT or REJECT. To restore another "
            "evaluated Candidate, append a decision with ADD_BACK. Every decision needs a reason."
        ),
        "decisions": [
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "",
                "reviewer": "",
                "reason": "",
            }
            for candidate in auto_selection["selected_candidates"]
        ],
    }


class _UnavailableApiClient:
    """Permit an offline finalize only when every evaluation is reusable."""

    def __init__(self, missing_variables: list[str]) -> None:
        self.missing_variables = missing_variables

    async def call(self, **_: Any) -> dict[str, Any]:
        raise TaskGoldError(
            "no reusable evaluation exists and required API environment variable(s) "
            "are missing: " + ", ".join(self.missing_variables)
        )


async def async_main(args: argparse.Namespace) -> int:
    project_id, annotation_path, messages_path, graph_path, output_dir = _resolve_paths(
        args
    )
    annotation = read_json(annotation_path)
    normalized_project = read_json(messages_path)
    state_graph = read_json(graph_path)
    config = _override_config(load_selection_config(args.config), args)

    candidate_tasks = generate_candidate_tasks(
        annotation, normalized_project, state_graph, config
    )
    candidate_contexts = build_candidate_contexts(
        candidate_tasks, annotation, normalized_project, state_graph
    )
    packets = build_candidate_packets(candidate_tasks, candidate_contexts)
    write_json(output_dir / "candidate_tasks.json", candidate_tasks)
    write_json(output_dir / "candidate_contexts.json", candidate_contexts)
    write_jsonl(output_dir / "candidate_packets.jsonl", packets)

    run_report: dict[str, Any] = {
        "project_id": project_id,
        "inputs": {
            "annotation": str(annotation_path),
            "messages": str(messages_path),
            "state_graph": str(graph_path),
            "prompt": str(args.prompt),
            "config": str(args.config),
        },
        "candidate_count": len(packets),
        "status": "PREPARED",
    }
    if args.prepare_only:
        write_json(output_dir / "target_selection_run.json", run_report)
        print(f"{project_id}: prepared {len(packets)} Candidate packets -> {output_dir}")
        return 0

    prompt = args.prompt.read_text(encoding="utf-8-sig")
    api_key = os.environ.get("UPWORK_API_KEY", "").strip()
    budget_id = os.environ.get("UPWORK_BUDGET_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("UPWORK_API_KEY", api_key),
            ("UPWORK_BUDGET_ID", budget_id),
        )
        if not value
    ]
    evaluation_path = output_dir / "candidate_llm_evaluations.jsonl"
    existing = read_jsonl(evaluation_path) if args.resume else []
    if not args.resume:
        write_jsonl(evaluation_path, [])
    evaluation_args = {
        "packets": packets,
        "prompt": prompt,
        "config": config,
        "existing_evaluations": existing,
        "force": args.force_evaluation,
        "on_evaluation": lambda row: append_jsonl(evaluation_path, row),
    }
    if missing:
        evaluations = await evaluate_candidate_packets(
            api=_UnavailableApiClient(missing), **evaluation_args
        )
    else:
        log_root = repo_root() / "outputs" / "stage2_logs"
        timeout = httpx.Timeout(config.timeout_seconds)
        async with httpx.AsyncClient(
            verify=not args.insecure, trust_env=False, timeout=timeout
        ) as http_client:
            api = Stage1ApiClient(
                http_client=http_client,
                api_key=api_key,
                budget_id=budget_id,
                model=config.model,
                reasoning_effort=config.reasoning_effort,
                retries=config.retries,
                max_concurrent_requests=config.max_concurrent_requests,
                log_path=log_root / "api_calls.jsonl",
                failed_response_dir=log_root / "failed_responses",
            )
            evaluations = await evaluate_candidate_packets(
                api=api, **evaluation_args
            )
    # Compact duplicate/obsolete resume rows into the current packet order.
    write_jsonl(evaluation_path, evaluations)
    recommended = select_recommended_candidates(candidate_tasks, evaluations, config)
    if args.auto_accept_ai:
        auto_selection = select_ai_candidates_by_score(
            candidate_tasks,
            evaluations,
            config,
            args.score_threshold,
        )
    else:
        auto_selection = apply_coverage_and_deduplication(
            recommended, candidate_contexts, config
        )
    write_json(output_dir / "recommended_candidates.json", recommended)
    write_json(output_dir / "selected_candidates_auto.json", auto_selection)
    run_report.update(
        {
            "evaluated_candidate_count": len(evaluations),
            "recommended_candidate_count": len(
                recommended["recommended_candidates"]
            ),
            "auto_selected_candidate_count": len(
                auto_selection["selected_candidates"]
            ),
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "selection_mode": (
                "AI_SCORE_THRESHOLD"
                if args.auto_accept_ai
                else "LLM_PLUS_HUMAN_REVIEW"
            ),
        }
    )
    if args.auto_accept_ai:
        run_report["ai_score_threshold"] = args.score_threshold
        selected_targets = finalize_ai_selected_targets(
            auto_selection, candidate_tasks, evaluations, config
        )
    else:
        review_template_path = output_dir / "target_time_human_review.template.json"
        write_json(review_template_path, _review_template(auto_selection))
        if not args.finalize:
            run_report["status"] = "AWAITING_HUMAN_REVIEW"
            write_json(output_dir / "target_selection_run.json", run_report)
            print(
                f"{project_id}: {len(packets)} evaluated, "
                f"{len(auto_selection['selected_candidates'])} auto-selected; "
                f"complete {review_template_path} and rerun with "
                "--finalize --human-review-file"
            )
            return 0
        human_review = read_json(args.human_review_file)
        selected_targets = finalize_selected_targets(
            auto_selection, candidate_tasks, evaluations, human_review, config
        )
    gold_states = build_gold_states(
        selected_targets, normalized_project, state_graph
    )
    gold_errors = validate_gold_states(
        gold_states,
        state_graph,
        normalized_project=normalized_project,
        selected_targets=selected_targets,
    )
    if gold_errors:
        raise TaskGoldError("generated Gold State failed validation: " + "; ".join(gold_errors))
    statistics = build_statistics(state_graph, gold_states)
    validation_report = {
        "project_id": project_id,
        "status": "PASSED",
        "inputs": run_report["inputs"],
        "artifact_validation": {"status": "PASSED", "gold_state_errors": []},
        "statistics": statistics,
    }
    write_json(output_dir / "selected_target_times.json", selected_targets)
    write_json(output_dir / "gold_states.json", gold_states)
    write_json(output_dir / "gold_state_validation.json", validation_report)
    run_report.update(
        {
            "final_selected_target_count": len(
                selected_targets["selected_targets"]
            ),
            "status": "PASSED",
        }
    )
    write_json(output_dir / "target_selection_run.json", run_report)
    print(
        f"{project_id}: finalized {statistics['generated_task_gold_states']} "
        f"selected Task Gold States"
        + (
            f" with AI score threshold {args.score_threshold}"
            if args.auto_accept_ai
            else " after human review"
        )
        + f" -> {output_dir}"
    )
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(async_main(args))
    except (OSError, ValueError, TaskGoldError, httpx.HTTPError) as exc:
        print(f"Target-time selection failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

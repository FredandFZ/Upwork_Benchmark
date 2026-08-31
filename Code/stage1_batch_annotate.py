"""CLI for the resumable ReqMemBench Stage 1 annotation pipeline."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from stage1.api_client import Stage1ApiClient
from stage1.config import ANNOTATION_MODEL, FORCE_STAGES, REASONING_EFFORT, PipelineConfig
from stage1.pipeline import EXCLUDED_NO_REQUIREMENTS, Stage1Pipeline, remove_final_annotation_files
from stage1.preprocessing import discover_projects
from stage1.reporting import annotation_statistics, write_statistics
from stage1.storage import read_json, write_json


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Run ReqMemBench Stage 1 annotation.")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=root / "Datasets" / "PII_clean_project",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=root / "prompt" / "stage1_prompt.md",
    )
    parser.add_argument(
        "--verification-addendum-file",
        type=Path,
        default=root / "prompt" / "stage1_event_verification_addendum.md",
        help="Stage-specific EVENT_VERIFICATION instructions.",
    )
    parser.add_argument(
        "--impact-audit-addendum-file",
        type=Path,
        default=root / "prompt" / "stage1_cross_requirement_impact_audit.md",
        help="Stage-specific CROSS_REQUIREMENT_IMPACT_AUDIT instructions.",
    )
    parser.add_argument(
        "--value-removal-addendum-file",
        type=Path,
        default=root / "prompt" / "stage1_value_removal_audit.md",
        help="Migration-only instructions for auditing stale attributes on existing MODIFY Events.",
    )
    parser.add_argument(
        "--single-pass-prompt-file",
        type=Path,
        default=root / "prompt" / "stage1_prompt_single_pass.md",
    )
    parser.add_argument("--output-dir", type=Path, default=root / "outputs" / "stage1_annotations")
    parser.add_argument("--run-root", type=Path, default=root / "outputs" / "stage1_runs")
    parser.add_argument(
        "--stats-file",
        type=Path,
        default=root / "outputs" / "stage1_requirement_event_statistics.csv",
    )
    parser.add_argument("--log-dir", type=Path, default=root / "outputs" / "stage1_logs")
    parser.add_argument("--project-id", action="append", help="Project directory ID; repeat to select several.")
    parser.add_argument(
        "--upgrade-existing-annotation",
        type=Path,
        help=(
            "Incrementally upgrade one existing Stage 1 annotation without rerunning "
            "Evidence Scan, Requirement Discovery, or Event Extraction."
        ),
    )
    parser.add_argument(
        "--annotation-mode",
        choices=("multipass", "single-pass"),
        default="multipass",
        help="Multi-pass is the recommended/default workflow.",
    )
    parser.add_argument("--model", default=ANNOTATION_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default=REASONING_EFFORT,
    )
    parser.add_argument(
        "--max-concurrent-requests",
        "--concurrency",
        dest="max_concurrent_requests",
        type=int,
        default=4,
    )
    parser.add_argument("--project-concurrency", type=int, default=1)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Per-request API timeout in seconds (default: 900 / 15 minutes).",
    )
    parser.add_argument("--evidence-chunk-size", type=int, default=150)
    parser.add_argument("--evidence-chunk-overlap", type=int, default=10)
    parser.add_argument("--context-window", type=int, default=2)
    parser.add_argument("--event-context-mode", choices=("filtered", "full_history"), default="filtered")
    parser.add_argument(
        "--max-requirement-context-messages",
        type=int,
        default=160,
        help="Maximum focused chat messages sent for one Requirement (default: 160).",
    )
    parser.add_argument(
        "--min-requirement-events",
        type=int,
        default=0,
        help=(
            "Optional lifecycle-length filter. The default 0 retains Requirements "
            "with any Event count, including zero."
        ),
    )
    parser.add_argument("--max-audit-rounds", type=int, default=1)
    parser.add_argument("--max-impact-audit-rounds", type=int, default=2)
    parser.add_argument("--max-impact-candidates-per-event", type=int, default=12)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force-stage", action="append", choices=sorted(FORCE_STAGES), default=[])
    parser.add_argument("--force-requirement", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true", help="Process projects even when a final output exists.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for trusted staging only.")
    args = parser.parse_args()
    if args.max_concurrent_requests < 1 or args.project_concurrency < 1:
        parser.error("Concurrency values must be >= 1")
    if args.retries < 0 or args.timeout <= 0:
        parser.error("--retries must be >= 0 and --timeout must be > 0")
    if args.force_requirement and (not args.project_id or len(args.project_id) != 1):
        parser.error("--force-requirement requires exactly one --project-id")
    if args.upgrade_existing_annotation is not None:
        if not args.project_id or len(args.project_id) != 1:
            parser.error("--upgrade-existing-annotation requires exactly one --project-id")
        if args.annotation_mode != "multipass":
            parser.error("--upgrade-existing-annotation cannot be combined with --annotation-mode single-pass")
        if args.force_stage or args.force_requirement:
            parser.error("--upgrade-existing-annotation cannot be combined with --force-stage/--force-requirement")
    return args


async def main_async(args: argparse.Namespace) -> int:
    try:
        common_prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        verification_addendum = args.verification_addendum_file.read_text(encoding="utf-8-sig")
        impact_audit_addendum = args.impact_audit_addendum_file.read_text(encoding="utf-8-sig")
        value_removal_addendum = args.value_removal_addendum_file.read_text(encoding="utf-8-sig")
        single_prompt = args.single_pass_prompt_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"Cannot read prompt file: {exc}", file=sys.stderr)
        return 2
    if args.upgrade_existing_annotation is not None and not args.upgrade_existing_annotation.is_file():
        print(
            f"Existing annotation file not found: {args.upgrade_existing_annotation}",
            file=sys.stderr,
        )
        return 2

    wanted_ids = set(args.project_id) if args.project_id else None
    try:
        discovered = discover_projects(args.dataset_root, args.output_dir, args.run_root, wanted_ids)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if wanted_ids:
        missing = wanted_ids.difference(project.project_id for project in discovered)
        if missing:
            print(f"Unknown project ID(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    if not args.dry_run:
        exclude_existing_empty_outputs(discovered, args.annotation_mode)

    selective_force = bool(args.force_stage or args.force_requirement or args.upgrade_existing_annotation)
    projects = discovered
    if not args.overwrite:
        if selective_force:
            # A batch force-stage rollout targets the currently published dataset,
            # not projects without a final annotation (including zero-Requirement
            # exclusions and unfinished runs). An explicit --project-id or
            # --overwrite remains available when reprocessing one is intentional.
            if wanted_ids is None:
                projects = [
                    project
                    for project in projects
                    if project.output_path.is_file()
                ]
        else:
            projects = [project for project in projects if not completed_for_mode(project, args.annotation_mode)]
    if args.dry_run:
        print(
            f"Would process {len(projects)} project(s) in {args.annotation_mode} mode with "
            f"{args.model} (reasoning={args.reasoning_effort}):"
        )
        for project in projects:
            print(f"  {project.project_id}: {project.chat_path} -> {project.output_path}")
        return 0
    if not projects:
        totals = write_statistics(args.stats_file, args.output_dir)
        print(f"No projects need annotation. Statistics: {totals[0]} projects, {totals[1]} requirements, {totals[2]} events")
        return 0

    api_key = os.environ.get("UPWORK_API_KEY", "").strip()
    budget_id = os.environ.get("UPWORK_BUDGET_ID", "").strip()
    missing_variables = [
        name for name, value in (("UPWORK_API_KEY", api_key), ("UPWORK_BUDGET_ID", budget_id)) if not value
    ]
    if missing_variables:
        print(f"Missing required environment variable(s): {', '.join(missing_variables)}", file=sys.stderr)
        return 2

    config = PipelineConfig(
        prompt_path=args.prompt_file,
        output_dir=args.output_dir,
        run_root=args.run_root,
        verification_addendum_path=args.verification_addendum_file,
        impact_audit_addendum_path=args.impact_audit_addendum_file,
        value_removal_addendum_path=args.value_removal_addendum_file,
        upgrade_existing_annotation_path=args.upgrade_existing_annotation,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        annotation_mode=args.annotation_mode,
        resume=args.resume,
        force_stages=set(args.force_stage),
        force_requirements=set(args.force_requirement),
        evidence_chunk_size=args.evidence_chunk_size,
        evidence_chunk_overlap=args.evidence_chunk_overlap,
        context_window=args.context_window,
        event_context_mode=args.event_context_mode,
        max_requirement_context_messages=args.max_requirement_context_messages,
        min_requirement_events=args.min_requirement_events,
        max_audit_rounds=args.max_audit_rounds,
        max_impact_audit_rounds=args.max_impact_audit_rounds,
        max_impact_candidates_per_event=args.max_impact_candidates_per_event,
    )
    try:
        config.validate()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.log_dir.mkdir(parents=True, exist_ok=True)
    call_log_path = args.log_dir / "api_calls.jsonl"
    timeout = httpx.Timeout(args.timeout)
    project_semaphore = asyncio.Semaphore(args.project_concurrency)
    failures: list[dict[str, str]] = []

    async with httpx.AsyncClient(verify=not args.insecure, trust_env=False, timeout=timeout) as http_client:
        api = Stage1ApiClient(
            http_client=http_client,
            api_key=api_key,
            budget_id=budget_id,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            retries=args.retries,
            max_concurrent_requests=args.max_concurrent_requests,
            log_path=call_log_path,
            failed_response_dir=args.log_dir / "failed_responses",
        )
        pipeline = Stage1Pipeline(
            api,
            config,
            common_prompt,
            call_log_path,
            single_prompt,
            verification_addendum,
            impact_audit_addendum,
            value_removal_addendum,
        )

        async def run_project(project):
            async with project_semaphore:
                print(f"[{project.project_id}] pipeline started ({args.annotation_mode})", flush=True)
                try:
                    annotation = await pipeline.run(project)
                except Exception as exc:
                    print(f"[{project.project_id}] pipeline FAILED: {exc}", flush=True)
                    return project.project_id, None, str(exc)
                _, requirement_count, event_count = annotation_statistics(project.project_id, annotation)
                if requirement_count == 0:
                    print(
                        f"[{project.project_id}] project EXCLUDED: 0 requirements; "
                        "no final annotation written",
                        flush=True,
                    )
                else:
                    print(
                        f"[{project.project_id}] annotation DONE: {requirement_count} requirements, "
                        f"{event_count} events -> {project.output_path}",
                        flush=True,
                    )
                return project.project_id, annotation, None

        results = await asyncio.gather(*(run_project(project) for project in projects))

    for project_id, _, error in results:
        if error:
            failures.append({"project_id": project_id, "error": error})
    totals = write_statistics(args.stats_file, args.output_dir)
    print(f"Statistics updated: {totals[0]} projects, {totals[1]} requirements, {totals[2]} events -> {args.stats_file}")
    excluded_count = sum(
        1
        for _, annotation, error in results
        if error is None and isinstance(annotation, dict) and not annotation.get("requirements")
    )
    print(
        f"Completed: {len(results) - len(failures)}/{len(results)}; "
        f"excluded with 0 requirements: {excluded_count}"
    )
    failure_path = args.output_dir / "stage1_batch_failures.json"
    if failures:
        write_json(failure_path, {"failures": failures})
        print(f"Failure details: {failure_path}", file=sys.stderr)
        return 1
    return 0


def exclude_existing_empty_outputs(projects, annotation_mode: str) -> list[str]:
    """Remove stale zero-Requirement final files and preserve a resumable exclusion marker."""
    excluded: list[str] = []
    for project in projects:
        if not project.output_path.is_file():
            continue
        try:
            annotation = read_json(project.output_path)
        except (OSError, ValueError):
            continue
        requirements = annotation.get("requirements") if isinstance(annotation, dict) else None
        if requirements != []:
            continue

        remove_final_annotation_files(project)
        metadata_path = project.run_dir / "run_metadata.json"
        try:
            metadata = read_json(metadata_path) if metadata_path.is_file() else {}
        except (OSError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        write_json(
            metadata_path,
            {
                **metadata,
                "project_id": project.project_id,
                "annotation_mode": metadata.get("annotation_mode") or annotation_mode,
                "status": EXCLUDED_NO_REQUIREMENTS,
                "excluded_at": datetime.now(timezone.utc).isoformat(),
                "exclusion_reason": "Final annotation contains no Requirements.",
                "final_output": None,
            },
        )
        excluded.append(project.project_id)
        print(
            f"[{project.project_id}] removed existing empty final annotation (0 requirements)",
            flush=True,
        )
    return excluded


def completed_for_mode(project, annotation_mode: str) -> bool:
    metadata_path = project.run_dir / "run_metadata.json"
    metadata = None
    if metadata_path.is_file():
        try:
            metadata = read_json(metadata_path)
        except (OSError, ValueError):
            metadata = None
    if (
        isinstance(metadata, dict)
        and metadata.get("status") == EXCLUDED_NO_REQUIREMENTS
        and metadata.get("annotation_mode") == annotation_mode
    ):
        return True
    if not project.output_path.is_file():
        return False
    if annotation_mode == "single-pass":
        return True
    return (
        isinstance(metadata, dict)
        and metadata.get("status") == "DONE"
        and metadata.get("annotation_mode") == "multipass"
    )
def main() -> int:
    args = parse_args()
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

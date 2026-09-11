#!/usr/bin/env python3
"""Run the v7 PII cleaning pipeline over the raw dataset projects.

Thin CLI, following the repo convention (``Code/stage1_batch_annotate.py``,
``Code/stage2_generate_gold_state.py``): parse arguments, read the prompts,
construct the API client, hand strings and config to the library layer.  All
pipeline logic lives in ``Code/PII/``.

Credentials come only from the environment.  Nothing is committed for a project
while any of its messages is unresolved; the run writes an agent task package
instead and ``Code/pii_finalize.py`` completes the project offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

try:  # ``python Code/pii_clean.py``
    from PII._compat import write_json
    from PII.config import PHASES, PiiConfig
    from PII.discovery import adapt_messages, discover_projects, load_chat
    from PII.errors import PiiError
    from PII.finalize import status_report
    from PII.pipeline import PiiPipeline
    from PII.prompts import load_prompt_set
    from PII.secret_shield import build_secret_registry
    from PII.textutil import word_bucket
    from stage1.api_client import Stage1ApiClient
    from stage1.config import ANNOTATION_MODEL, REASONING_EFFORT
except ModuleNotFoundError:  # ``python -m Code.pii_clean``
    from Code.PII._compat import write_json
    from Code.PII.config import PHASES, PiiConfig
    from Code.PII.discovery import adapt_messages, discover_projects, load_chat
    from Code.PII.errors import PiiError
    from Code.PII.finalize import status_report
    from Code.PII.pipeline import PiiPipeline
    from Code.PII.prompts import load_prompt_set
    from Code.PII.secret_shield import build_secret_registry
    from Code.PII.textutil import word_bucket
    from Code.stage1.api_client import Stage1ApiClient
    from Code.stage1.config import ANNOTATION_MODEL, REASONING_EFFORT

# Phase 5 bounds its own attempts, so it must not multiply them by the global
# retry budget; see PII/phase5_repair.py.
RETRIES_OVERRIDES = {"PII7_REPAIR": 1}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Clean dataset chat transcripts into natural synthetic content (v7)."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=root / "Datasets" / "project",
        help="Directory containing <project_id>/chat_messages.json.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "Datasets" / "PII_clean_project",
        help="Destination for the published dataset.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=root / "outputs" / "pii_runs",
        help="Run directory for phase checkpoints, the ledger and agent tasks.",
    )
    parser.add_argument(
        "--log-root",
        type=Path,
        default=root / "outputs" / "pii_logs",
        help="Destination for API call logs and redacted failed responses.",
    )
    parser.add_argument(
        "--prompt-dir",
        type=Path,
        default=root / "prompt" / "PII",
        help="Directory holding the v7 prompt files.",
    )
    parser.add_argument("--project-id", action="append", help="Repeat for several projects.")
    parser.add_argument("--model", default=ANNOTATION_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default=REASONING_EFFORT,
    )
    parser.add_argument(
        "--phase-effort",
        action="append",
        default=[],
        metavar="PHASE=LEVEL",
        help="Override reasoning effort for one phase, e.g. PHASE_2_TRANSFORMATION_PLAN=max.",
    )
    parser.add_argument("--preserve-short-max-words", type=int, default=2)
    parser.add_argument("--short-message-max-words", type=int, default=4)
    parser.add_argument("--max-batch-messages", type=int, default=40)
    parser.add_argument("--max-batch-chars", type=int, default=30_000)
    parser.add_argument("--neighbor-window", type=int, default=2)
    parser.add_argument("--semantic-fold-chars", type=int, default=60_000)
    parser.add_argument("--semantic-fold-records", type=int, default=120)
    parser.add_argument("--max-accumulator-chars", type=int, default=250_000)
    parser.add_argument("--plan-chunk-bundles", type=int, default=25)
    parser.add_argument("--plan-chunk-chars", type=int, default=40_000)
    parser.add_argument("--max-repair-attempts", type=int, default=2)
    parser.add_argument("--project-concurrency", type=int, default=2)
    parser.add_argument("--max-concurrent-requests", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--force-phase",
        action="append",
        default=[],
        help=(
            "Recompute this phase and everything downstream of it in the phase DAG. "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--stop-after-phase",
        choices=PHASES,
        default=None,
        help="Run only up to this phase; nothing is committed.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--keep-run-artifacts",
        action="store_true",
        help=(
            "Keep the PII-bearing run artifacts after success. The phase-2 plan pairs "
            "original values with their replacements, so it is a complete "
            "re-identification key for the released dataset."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Local pre-flight only: no API calls, no output.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read-only report of each project's state and the next command to run.",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Disable TLS verification (trusted staging only)."
    )
    parser.add_argument("--preserve-term", action="append", default=[])
    parser.add_argument("--extra-private-term", action="append", default=[])
    parser.add_argument("--list-phases", action="store_true", help="Print the phase names.")

    args = parser.parse_args()
    if args.source_root.resolve() == args.output_root.resolve():
        parser.error("--output-root must differ from --source-root")
    if args.project_concurrency < 1 or args.max_concurrent_requests < 1:
        parser.error("concurrency values must be >= 1")
    if args.retries < 0 or args.timeout <= 0:
        parser.error("--retries must be >= 0 and --timeout must be > 0")
    for item in args.force_phase:
        if item not in PHASES:
            parser.error(f"--force-phase {item!r} is not a phase; see --list-phases")
    return args


def phase_efforts(values: list[str]) -> dict[str, str]:
    efforts: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise PiiError(f"--phase-effort expects PHASE=LEVEL, got {item!r}")
        phase, _, level = item.partition("=")
        efforts[phase.strip()] = level.strip()
    return efforts


def build_config(args: argparse.Namespace) -> PiiConfig:
    config = PiiConfig(
        output_root=args.output_root,
        work_root=args.work_root,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        phase_reasoning_effort=phase_efforts(args.phase_effort),
        preserve_short_max_words=args.preserve_short_max_words,
        short_message_max_words=args.short_message_max_words,
        max_batch_messages=args.max_batch_messages,
        max_batch_chars=args.max_batch_chars,
        neighbor_window=args.neighbor_window,
        semantic_fold_chars=args.semantic_fold_chars,
        semantic_fold_records=args.semantic_fold_records,
        max_accumulator_chars=args.max_accumulator_chars,
        plan_chunk_bundles=args.plan_chunk_bundles,
        plan_chunk_chars=args.plan_chunk_chars,
        max_repair_attempts=args.max_repair_attempts,
        resume=args.resume,
        overwrite=args.overwrite,
        force_phases=frozenset(args.force_phase),
        stop_after_phase=args.stop_after_phase,
        keep_run_artifacts=args.keep_run_artifacts,
        preserve_terms=tuple(args.preserve_term),
        extra_private_terms=tuple(args.extra_private_term),
    )
    config.validate()
    return config


def dry_run(args: argparse.Namespace, config: PiiConfig) -> int:
    """Local pre-flight: what the shield and the bucketer see, with zero API use."""

    from_ids = set(args.project_id) if args.project_id else None
    projects = discover_projects(args.source_root, from_ids)
    summaries = []
    for project in projects:
        chat = load_chat(project.chat_path)
        messages = adapt_messages(chat, project.project_id)
        registry, _spans = build_secret_registry(project.project_id, messages)
        buckets: dict[str, int] = {}
        for message in messages:
            bucket = word_bucket(
                message["text"],
                preserve_short_max_words=config.preserve_short_max_words,
                short_message_max_words=config.short_message_max_words,
            )
            buckets[bucket] = buckets.get(bucket, 0) + 1
        summaries.append(
            {
                "project_id": project.project_id,
                "messages": len(messages),
                "secret_candidates": len(registry.secrets),
                "secret_kinds": registry.counts_by_kind(),
                "provisional_buckets": dict(sorted(buckets.items())),
            }
        )
    print(json.dumps({"projects": summaries}, ensure_ascii=False, indent=2))
    return 0


def show_status(args: argparse.Namespace) -> int:
    wanted = set(args.project_id) if args.project_id else None
    projects = discover_projects(args.source_root, wanted)
    rows = [status_report(project, args.work_root) for project in projects]
    interesting = [row for row in rows if row["status"] not in ("UNKNOWN", "PASSED")]
    print(json.dumps({"projects": rows}, ensure_ascii=False, indent=2))
    if interesting:
        print("\nNext steps:", file=sys.stderr)
        for row in interesting:
            print(f"  [{row['project_id']}] {row['next_command']}", file=sys.stderr)
    return 0


async def main_async(args: argparse.Namespace) -> int:
    config = build_config(args)
    try:
        prompts = load_prompt_set(args.prompt_dir)
    except PiiError as exc:
        print(f"Cannot read prompts: {exc}", file=sys.stderr)
        return 2

    wanted = set(args.project_id) if args.project_id else None
    projects = discover_projects(args.source_root, wanted)
    if not projects:
        print("No projects containing chat_messages.json found.", file=sys.stderr)
        return 2

    api_key = os.environ.get("UPWORK_API_KEY", "").strip()
    budget_id = os.environ.get("UPWORK_BUDGET_ID", "").strip()
    missing = [
        name
        for name, value in (("UPWORK_API_KEY", api_key), ("UPWORK_BUDGET_ID", budget_id))
        if not value
    ]
    if missing:
        print(
            f"Missing required environment variable(s): {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    log_path = args.log_root / "api_calls.jsonl"
    failures: list[dict[str, str]] = []
    statuses: list[dict[str, object]] = []
    semaphore = asyncio.Semaphore(args.project_concurrency)
    timeout = httpx.Timeout(args.timeout)

    async with httpx.AsyncClient(
        verify=not args.insecure, trust_env=False, timeout=timeout
    ) as http_client:
        api = Stage1ApiClient(
            http_client=http_client,
            api_key=api_key,
            budget_id=budget_id,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            retries=args.retries,
            max_concurrent_requests=args.max_concurrent_requests,
            log_path=log_path,
            failed_response_dir=args.log_root / "failed_responses",
            reasoning_effort_overrides={},
            retries_overrides=RETRIES_OVERRIDES,
        )
        pipeline = PiiPipeline(api, config, prompts, run_root=args.work_root)

        async def run_one(project) -> None:
            async with semaphore:
                try:
                    statuses.append(await pipeline.run(project))
                except Exception as exc:  # keep the remaining projects runnable
                    failures.append(
                        {"project_id": project.project_id, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    print(
                        f"[{project.project_id}] FAILED: {exc}", file=sys.stderr, flush=True
                    )

        await asyncio.gather(*(run_one(project) for project in projects))

    unresolved = [
        row
        for row in statuses
        if isinstance(row, dict) and row.get("status") not in ("SKIPPED", "DONE")
    ]
    if failures:
        write_json(args.log_root / "batch_failures.json", failures)
    if unresolved:
        print(
            f"\n{len(unresolved)} project(s) need attention. Run with --status for the "
            "exact next command per project.",
            file=sys.stderr,
        )
    if failures:
        print(f"Completed with {len(failures)} failed project(s).", file=sys.stderr)
        return 1
    if unresolved:
        return 1
    print(f"All {len(projects)} project(s) cleaned successfully.")
    return 0


def main() -> int:
    args = parse_args()
    if args.list_phases:
        for phase in PHASES:
            print(phase)
        return 0
    try:
        if args.status:
            return show_status(args)
        if args.dry_run:
            return dry_run(args, build_config(args))
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        return asyncio.run(main_async(args))
    except (OSError, ValueError, PiiError, httpx.HTTPError) as exc:
        print(f"PII cleaning failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fold agent repairs into a blocked project and commit the clean JSON.

Fully offline: no credentials are read and no API is called.  The agent's text
passes exactly the phase-3 local gate plus the two staleness guards, then phase
6A renders credentials deterministically and phase 6B audits the whole project.

Nothing is committed unless every open agent-actionable task is covered, every
submitted repair is accepted, and the audit reports zero violations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # ``python Code/pii_finalize.py``
    from PII.config import PiiConfig
    from PII.discovery import discover_projects
    from PII.errors import AuditFailure, PiiError, PiiValidationError
    from PII.finalize import finalize_project, status_report, write_submission_template
except ModuleNotFoundError:  # ``python -m Code.pii_finalize``
    from Code.PII.config import PiiConfig
    from Code.PII.discovery import discover_projects
    from Code.PII.errors import AuditFailure, PiiError, PiiValidationError
    from Code.PII.finalize import finalize_project, status_report, write_submission_template


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Apply agent repairs and commit the final clean chat_messages.json (offline)."
        )
    )
    parser.add_argument(
        "--source-root", type=Path, default=root / "Datasets" / "project"
    )
    parser.add_argument(
        "--output-root", type=Path, default=root / "Datasets" / "PII_clean_project"
    )
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    parser.add_argument(
        "--project-id",
        action="append",
        help="Repeat for several projects. Defaults to every project with a run directory.",
    )
    parser.add_argument(
        "--submission",
        type=Path,
        default=None,
        help="Path to the agent's repairs.json (defaults to the project's run directory).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and audit, then report. Writes no dataset output.",
    )
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Emit a prefilled repairs.template.json and exit.",
    )
    parser.add_argument(
        "--status", action="store_true", help="Read-only state report; no writes."
    )
    parser.add_argument(
        "--keep-run-artifacts",
        action="store_true",
        help="Keep the PII-bearing run artifacts after a successful commit.",
    )
    parser.add_argument("--preserve-term", action="append", default=[])
    parser.add_argument("--extra-private-term", action="append", default=[])
    args = parser.parse_args()
    if args.submission is not None and len(args.project_id or []) != 1:
        parser.error("--submission requires exactly one --project-id")
    return args


def build_config(args: argparse.Namespace) -> PiiConfig:
    config = PiiConfig(
        output_root=args.output_root,
        work_root=args.work_root,
        # Model and effort are recorded in the manifest for provenance only;
        # this command never calls a model.
        model="offline",
        reasoning_effort="high",
        keep_run_artifacts=args.keep_run_artifacts,
        preserve_terms=tuple(args.preserve_term),
        extra_private_terms=tuple(args.extra_private_term),
    )
    config.validate()
    return config


def selected_projects(args: argparse.Namespace):
    wanted = set(args.project_id) if args.project_id else None
    projects = discover_projects(args.source_root, wanted)
    if wanted is not None:
        return projects
    # Without an explicit selection, only projects that actually have a run.
    return [
        project
        for project in projects
        if (args.work_root / project.project_id).is_dir()
    ]


def main() -> int:
    args = parse_args()
    try:
        projects = selected_projects(args)
    except PiiError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not projects:
        print(
            "No projects with a run directory found; run Code/pii_clean.py first.",
            file=sys.stderr,
        )
        return 2

    if args.status:
        rows = [status_report(project, args.work_root) for project in projects]
        print(json.dumps({"projects": rows}, ensure_ascii=False, indent=2))
        return 0

    if args.write_template:
        for project in projects:
            try:
                path = write_submission_template(project, args.work_root / project.project_id)
            except PiiError as exc:
                print(f"[{project.project_id}] {exc}", file=sys.stderr)
                continue
            print(f"[{project.project_id}] template written: {path}")
        return 0

    config = build_config(args)
    failures: list[str] = []
    committed = 0
    for project in projects:
        try:
            finalize_project(
                project,
                config,
                run_root=args.work_root,
                submission_path=args.submission,
                validate_only=args.validate_only,
            )
            committed += 1
        except (PiiValidationError, AuditFailure, PiiError) as exc:
            failures.append(f"[{project.project_id}] {type(exc).__name__}: {exc}")
            print(f"[{project.project_id}] NOT COMMITTED: {exc}", file=sys.stderr)

    if failures:
        print(
            f"\n{len(failures)} project(s) could not be finalized; "
            f"{committed} succeeded.",
            file=sys.stderr,
        )
        return 1
    action = "validated" if args.validate_only else "committed"
    print(f"All {committed} project(s) {action}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for deterministic ReqMemBench Stage 2 State Graph construction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stage1.storage import read_json, write_json
from stage2.state_graph import Stage2ReplayError, build_requirement_state_graph


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Build requirement_state_graph.json from Stage 1 annotations."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="One explicit Stage 1 annotation JSON file.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=root / "outputs" / "stage1_annotations",
        help="Directory containing <project_id>_stage1_annotation.json files.",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        help="Project ID to build; repeat for multiple projects. Without it, build every input file.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "outputs" / "stage2",
        help="Root for <project_id>/requirement_state_graph.json outputs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Explicit output path; valid only with --input.",
    )
    args = parser.parse_args()
    if args.input is not None and args.project_id:
        parser.error("--input cannot be combined with --project-id")
    if args.output is not None and args.input is None:
        parser.error("--output requires --input")
    return args


def discover_inputs(args: argparse.Namespace) -> list[Path]:
    if args.input is not None:
        return [args.input]
    if args.project_id:
        paths = [
            args.input_dir / f"{project_id}_stage1_annotation.json"
            for project_id in args.project_id
        ]
        missing = [path for path in paths if not path.is_file()]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise Stage2ReplayError(f"Stage 1 annotation file(s) not found: {joined}")
        return paths
    return sorted(args.input_dir.glob("*_stage1_annotation.json"))


def main() -> int:
    args = parse_args()
    try:
        inputs = discover_inputs(args)
        if not inputs:
            raise Stage2ReplayError(f"No Stage 1 annotations found in {args.input_dir}")
        for input_path in inputs:
            annotation = read_json(input_path)
            graph = build_requirement_state_graph(annotation)
            output_path = (
                args.output
                if args.output is not None
                else args.output_root / graph["project_id"] / "requirement_state_graph.json"
            )
            write_json(output_path, graph)
            node_count = sum(len(item["nodes"]) for item in graph["requirement_graphs"])
            print(
                f"{graph['project_id']}: {len(graph['requirement_graphs'])} Requirement graphs, "
                f"{node_count} states -> {output_path}"
            )
    except (OSError, ValueError, Stage2ReplayError) as exc:
        print(f"Stage 2 generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create an RQ3 review template or freeze an adjudicated review into Gold."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stage2.rq3_review import RQ3ReviewError, apply_review, build_review_template


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RQ3ReviewError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template-out", type=Path)
    group.add_argument("--review", type=Path)
    parser.add_argument(
        "--output-instance",
        type=Path,
        help="Required with --review; write the frozen instance here.",
    )
    args = parser.parse_args()
    if args.review is not None and args.output_instance is None:
        parser.error("--review requires --output-instance")
    return args


def main() -> int:
    args = _args()
    try:
        instance = _read(args.instance)
        if args.template_out is not None:
            _write(args.template_out, build_review_template(instance))
            print(f"RQ3 review template written: {args.template_out}")
        else:
            _write(args.output_instance, apply_review(instance, _read(args.review)))
            print(f"Frozen RQ3 instance written: {args.output_instance}")
        return 0
    except (OSError, json.JSONDecodeError, RQ3ReviewError) as exc:
        print(f"RQ3 Gold finalization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

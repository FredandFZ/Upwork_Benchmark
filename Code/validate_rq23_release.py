#!/usr/bin/env python3
"""Independently validate a frozen RQ2/RQ3 release and Phase A loading."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from rq_agent_input import materialize_reasoning_input
from stage2.rq_instances import validate_rq_instance


PENDING_STATUSES = {
    "PENDING_COMPARATOR_REVIEW",
    "REQUIRES_FIELD_REVIEW",
    "REQUIRES_FROZEN_SEMANTIC_JUDGE",
    "PENDING_BLOCKING_AMBIGUITY_REVIEW",
}


class ReleaseValidationError(ValueError):
    """The frozen release is internally inconsistent."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"{path} must contain an object")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pending_values(value: Any, path: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if (
                key in {"status", "review_status"}
                and isinstance(child, str)
                and child in PENDING_STATUSES
            ):
                findings.append(child_path)
            findings.extend(_pending_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_pending_values(child, f"{path}[{index}]"))
    return findings


def _args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage2-root", type=Path, default=root / "outputs_new" / "stage2"
    )
    parser.add_argument(
        "--review-dir",
        type=Path,
        default=root / "ccfa-workfiles" / "reviews" / "rq23-offline-audit",
    )
    parser.add_argument(
        "--instructions", type=Path, default=root / "prompt" / "rq_agent_instructions.md"
    )
    parser.add_argument(
        "--response-schema",
        type=Path,
        default=root / "schema" / "rq_agent_response.schema.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        summary_path = args.review_dir / "summary.json"
        summary = _read(summary_path)
        expected_targets = summary.get("target_count")
        if expected_targets != 349:
            raise ReleaseValidationError(
                f"review summary target_count is {expected_targets!r}, expected 349"
            )

        rq_counts: Counter[str] = Counter()
        decisions: Counter[str] = Counter()
        projects = 0
        materialized_packages = 0
        seen_targets: set[str] = set()

        for project_dir in sorted(path for path in args.stage2_root.iterdir() if path.is_dir()):
            manifest_path = project_dir / "rq_instance_manifest.json"
            if not manifest_path.exists():
                continue
            manifest = _read(manifest_path)
            targets = manifest.get("targets", [])
            if not isinstance(targets, list):
                raise ReleaseValidationError(f"{manifest_path} has invalid targets")
            if not targets:
                continue
            projects += 1
            source = manifest.get("source_artifacts", {}).get("rq23_offline_review", {})
            source_path = Path(__file__).resolve().parents[1] / str(source.get("path"))
            if source_path.resolve() != summary_path.resolve():
                raise ReleaseValidationError(f"{manifest_path} has the wrong review path")
            if source.get("sha256") != _file_sha256(summary_path):
                raise ReleaseValidationError(f"{manifest_path} has a stale review hash")

            indexes: dict[str, dict[str, Mapping[str, Any]]] = {}
            for rq_id in ("RQ2", "RQ3"):
                index = _read(project_dir / rq_id / "index.json")
                indexes[rq_id] = {
                    str(row["instance_id"]): row for row in index.get("instances", [])
                }

            for target in targets:
                target_id = str(target["target_id"])
                if target_id in seen_targets:
                    raise ReleaseValidationError(f"duplicate target {target_id}")
                seen_targets.add(target_id)
                for rq_id in ("RQ2", "RQ3"):
                    ref = target.get("instances", {}).get(rq_id)
                    if not isinstance(ref, Mapping):
                        raise ReleaseValidationError(f"{target_id} lacks {rq_id}")
                    path = project_dir / str(ref["file"])
                    instance = _read(path)
                    errors = validate_rq_instance(instance)
                    if errors:
                        raise ReleaseValidationError(
                            f"{path} failed schema validation: {'; '.join(errors)}"
                        )
                    expected_hash = _canonical_sha256(instance)
                    if ref.get("content_sha256") != expected_hash:
                        raise ReleaseValidationError(f"{path} manifest hash mismatch")
                    instance_id = str(instance["instance_id"])
                    if indexes[rq_id].get(instance_id, {}).get("content_sha256") != expected_hash:
                        raise ReleaseValidationError(f"{path} index hash mismatch")
                    if instance.get("readiness", {}).get("formal_reasoning_allowed") is not True:
                        raise ReleaseValidationError(f"{path} is not formal-reasoning ready")
                    rq_counts[rq_id] += 1
                    if rq_id == "RQ2":
                        if instance["construction_gold"].get("status") != "FINAL_TYPED_STATE_GOLD":
                            raise ReleaseValidationError(f"{path} has non-final RQ2 Gold")
                        pending = _pending_values(
                            instance["construction_gold"].get("field_scoring_specs")
                        )
                    else:
                        gold = instance["construction_gold"]
                        if gold.get("status") != "FINAL_UPDATE_OR_CLARIFY_GOLD":
                            raise ReleaseValidationError(f"{path} has non-final RQ3 Gold")
                        pending = _pending_values(gold.get("post_state_scoring_specs"))
                        c1 = gold["final_gold_by_condition"]["C1"]
                        c2 = gold["final_gold_by_condition"]["C2"]
                        if c1 != c2:
                            raise ReleaseValidationError(f"{path} has divergent C1/C2 Gold")
                        decisions[str(c1["decision"])] += 1
                    if pending:
                        raise ReleaseValidationError(
                            f"{path} retains pending scoring fields: {pending}"
                        )

                for condition in ("C1", "C2"):
                    materialize_reasoning_input(
                        project_dir,
                        target_id,
                        condition,
                        instructions_path=args.instructions,
                        response_schema_path=args.response_schema,
                        mode="formal",
                    )
                    materialized_packages += 1

        for filename in ("reviewer-a.jsonl", "reviewer-b.jsonl", "adjudication.jsonl"):
            rows = [
                line
                for line in (args.review_dir / filename).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if len(rows) != expected_targets:
                raise ReleaseValidationError(
                    f"{filename} has {len(rows)} rows, expected {expected_targets}"
                )
        for rq_id in ("rq2", "rq3"):
            review_count = len(list((args.review_dir / rq_id).glob("*.json")))
            if review_count != expected_targets:
                raise ReleaseValidationError(
                    f"{rq_id} review count is {review_count}, expected {expected_targets}"
                )

        actual = {
            "project_count": projects,
            "target_count": len(seen_targets),
            "instance_counts": dict(rq_counts),
            "rq3_decisions": dict(decisions),
            "formal_phase_a_packages_validated": materialized_packages,
            "review_rows_per_role": expected_targets,
            "per_rq_review_files": expected_targets,
            "status": "PASS",
        }
        expected_decisions = summary.get("rq3", {}).get("final_decision_distribution")
        if len(seen_targets) != expected_targets or dict(decisions) != expected_decisions:
            raise ReleaseValidationError(
                f"release counts disagree with review summary: {actual}"
            )
        print(json.dumps(actual, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ReleaseValidationError, ValueError) as exc:
        print(f"RQ2/RQ3 release validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

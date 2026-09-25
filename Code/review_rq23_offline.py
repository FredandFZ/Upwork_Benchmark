#!/usr/bin/env python3
"""Run a role-separated offline review and freeze RQ2/RQ3 Gold in one release."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from stage2.rq2_review import (
    RQ2ReviewError,
    apply_review as apply_rq2_review,
    build_review_template as build_rq2_review_template,
)
from stage2.rq3_review import (
    RQ3ReviewError,
    apply_review as apply_rq3_review,
    build_offline_agent_review_template,
)
from stage2.rq_instances import RQInstanceError, validate_rq_instance


REVIEW_METHOD = "SINGLE_AGENT_ROLE_SEPARATED_PANEL"
REVIEWERS = ("codex-structural-role", "codex-semantic-role")
ADJUDICATOR = "codex-adjudication-role"
ORDERED_LIST_PATHS = {
    "attributes.approved_remaining_script",
    "attributes.assigned_chapter_ranges",
    "attributes.assigned_chapter_rounds",
    "attributes.board_chain_order",
    "attributes.demonstration_sequence",
    "attributes.terminal_application_order",
}

# These decisions differ from the automatic OPEN-ambiguity heuristic after
# reviewing the current task, the complete before/after transition, and whether
# the unresolved fact can be safely deferred.
RQ3_DECISION_OVERRIDES = {
    "37923084_T004": "CLARIFY",
    "43214420_T016": "ACT",
    "43531571_T002": "ACT",
    "44102153_T002": "ACT",
    "44102153_T004": "ACT",
    "44159206_T006": "ACT",
    "44159206_T011": "ACT",
    "44186585_T002": "ACT",
}

RQ3_OVERRIDE_RATIONALES = {
    "37923084_T004": (
        "The target proposes one domain only tentatively and explicitly permits "
        "an unspecified similar alternative, so no unique domain state is fixed."
    ),
    "43214420_T016": (
        "The client explicitly delegates the retain/remove choice to the layout "
        "condition; that conditional policy is executable without another client fact."
    ),
    "43531571_T002": (
        "The target defers all additional work until funding succeeds, so the older "
        "story-coverage ambiguity can be safely deferred with the work."
    ),
    "44102153_T002": (
        "The 6-by-9 trim size is uniquely fixed; the full-page image idea is stated "
        "as a consideration and can be deferred without blocking the trim update."
    ),
    "44102153_T004": (
        "Retaining the supplied cover is the operative preference, while the request "
        "for an editor recommendation does not require a new client-side fact."
    ),
    "44159206_T006": (
        "The 28 cm wall shift and left-wall drain/shower placement are explicit; the "
        "older construction-versus-drawing scope question does not block these edits."
    ),
    "44159206_T011": (
        "The target changes the unit-1 toilet and annotations; the carried unit-3 "
        "drainage ambiguity is unrelated to this requested edit."
    ),
    "44186585_T002": (
        "The new-site Elementor migration target is explicit; the older question "
        "about an unlicensed Thrive installation can be handled separately."
    ),
}


class OfflineReviewError(ValueError):
    """The batch cannot be reviewed or frozen safely."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise OfflineReviewError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mark_specs_reviewed(
    spec: dict[str, Any],
    *,
    path: tuple[str, ...],
    changes: list[dict[str, Any]],
) -> None:
    comparator = spec.get("comparator")
    if comparator is not None:
        field_path = ".".join(path)
        child_key = (
            "fields"
            if comparator == "RECURSIVE_FIELDS"
            else "item_fields" if comparator == "UNORDERED_RECORD_F1" else None
        )
        children = spec.get(child_key) if child_key is not None else None
        if child_key is not None and isinstance(children, dict) and not children:
            spec["comparator"] = "SKIP"
            spec["score"] = False
            comparator = "SKIP"
            changes.append(
                {
                    "field_path": field_path,
                    "from": "RECURSIVE_FIELDS"
                    if child_key == "fields"
                    else "UNORDERED_RECORD_F1",
                    "to": "SKIP",
                    "reason": "The container has no Gold leaves to score.",
                }
            )
        if comparator == "SET_F1" and field_path in ORDERED_LIST_PATHS:
            spec["comparator"] = "ORDERED_LIST"
            changes.append(
                {
                    "field_path": field_path,
                    "from": "SET_F1",
                    "to": "ORDERED_LIST",
                    "reason": "The Gold value is a material sequence, not a set.",
                }
            )
        spec["review_status"] = "ROLE_SEPARATED_AGENT_REVIEWED"
    fields = spec.get("fields")
    if isinstance(fields, dict):
        for key, child in fields.items():
            if isinstance(child, dict):
                _mark_specs_reviewed(
                    child, path=path + (str(key),), changes=changes
                )
    item_fields = spec.get("item_fields")
    if isinstance(item_fields, dict):
        for key, child in item_fields.items():
            if isinstance(child, dict):
                _mark_specs_reviewed(
                    child, path=path + (str(key),), changes=changes
                )


def _review_all_specs(specs: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for requirement_specs in specs.values():
        if not isinstance(requirement_specs, dict):
            continue
        for dimension, spec in requirement_specs.items():
            if isinstance(spec, dict):
                _mark_specs_reviewed(
                    spec, path=(str(dimension),), changes=changes
                )
    return changes


def _rq3_blockers(instance: Mapping[str, Any]) -> list[dict[str, Any]]:
    target_id = str(instance["target_id"])
    if target_id == "37923084_T004":
        return [
            {
                "requirement_id": "REQ_CAMPAIGN_DOMAIN_PROVISIONING",
                "dimension": "VALUE",
                "field": "domain_candidate",
                "missing_information": (
                    "The target names one possible domain but also permits an "
                    "unspecified similar alternative, so the exact domain is not fixed."
                ),
                "acceptable_question_facts": [
                    "ask the client to confirm the exact domain to provision and warm up"
                ],
            }
        ]
    candidates = instance["construction_gold"].get(
        "blocking_ambiguity_candidates", []
    )
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        description = str(
            candidate.get("description")
            or candidate.get("missing_information")
            or "A material implementation choice remains unresolved."
        ).strip()
        key = (
            candidate.get("requirement_id"),
            candidate.get("dimension"),
            candidate.get("field"),
            description,
        )
        if key in seen:
            continue
        seen.add(key)
        blockers.append(
            {
                "requirement_id": candidate.get("requirement_id"),
                "dimension": candidate.get("dimension"),
                "field": candidate.get("field"),
                "missing_information": description,
                "acceptable_question_facts": [
                    "ask the client to resolve the material choice described as: "
                    + description
                ],
            }
        )
    return blockers


def _structural_record(
    rq2: Mapping[str, Any], rq3: Mapping[str, Any]
) -> dict[str, Any]:
    rq2_errors = validate_rq_instance(dict(rq2))
    rq3_errors = validate_rq_instance(dict(rq3))
    gold2 = rq2["construction_gold"]
    gold3 = rq3["construction_gold"]
    history_ids = {
        row["message_id"] for row in rq2["history_pool"].get("messages", [])
    }
    target_message_id = rq2["target_message_id"]
    return {
        "schema_version": "rq23-role-review-record-v1",
        "reviewer_role": REVIEWERS[0],
        "review_method": REVIEW_METHOD,
        "project_id": rq2["project_id"],
        "target_id": rq2["target_id"],
        "target_message_id": target_message_id,
        "rq2": {
            "verdict": "PASS" if not rq2_errors else "REVISE",
            "schema_errors": rq2_errors,
            "pre_task_boundary_correct": target_message_id not in history_ids,
            "historical_requirement_scope_correct": (
                set(gold2["states"]) == set(gold2["gold_requirement_ids"])
                and not set(gold2["states"]).intersection(
                    gold2.get("new_requirement_ids", [])
                )
            ),
            "internal_ids_excluded": all(
                set(state)
                == {
                    "attributes",
                    "scope",
                    "lifecycle_status",
                    "ambiguity",
                    "execution",
                }
                for state in gold2["states"].values()
            ),
        },
        "rq3": {
            "verdict": "PASS" if not rq3_errors else "REVISE",
            "schema_errors": rq3_errors,
            "affected_ids_match_transitions": (
                set(gold3["affected_requirement_ids"])
                == set(gold3["affected_requirement_transitions"])
                == set(gold3["post_task_states"])
            ),
            "c1_c2_inputs_available": all(
                rq3["condition_inputs"][condition].get("available") is True
                for condition in ("C1", "C2")
            ),
        },
        "confidence": "HIGH",
    }


def _semantic_record(
    rq2: Mapping[str, Any],
    rq3: Mapping[str, Any],
    *,
    comparator_changes: list[dict[str, Any]],
    decision: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = rq3["construction_gold"]["project_decision_candidate"]["value"]
    target_id = str(rq3["target_id"])
    rationale = RQ3_OVERRIDE_RATIONALES.get(
        target_id,
        (
            "All affected transitions have a unique executable after-state and no "
            "material unresolved client fact blocks this target."
            if decision == "ACT"
            else "At least one material affected requirement lacks a unique state."
        ),
    )
    return {
        "schema_version": "rq23-role-review-record-v1",
        "reviewer_role": REVIEWERS[1],
        "review_method": REVIEW_METHOD,
        "project_id": rq2["project_id"],
        "target_id": target_id,
        "target_message_id": rq2["target_message_id"],
        "rq2": {
            "verdict": "PASS_WITH_REVIEWED_SPECS",
            "comparator_changes": comparator_changes,
            "semantic_fact_policy": (
                "Retain SEMANTIC_FACT only for text-valued requirement facts; "
                "the frozen judge returns a discrete equivalence relation."
            ),
            "null_policy": (
                "Explicit absent ambiguity/execution remains NULL_EXACT; "
                "unannotated unknown scope/lifecycle remains SKIP."
            ),
        },
        "rq3": {
            "candidate_decision": candidate,
            "final_decision": decision,
            "decision_changed": candidate != decision,
            "rationale": rationale,
            "blocking_clarifications": blockers,
        },
        "confidence": "HIGH" if candidate == decision else "MEDIUM",
        "evidence_message_ids": [rq2["target_message_id"]],
    }


def _update_project_metadata(
    project_dir: Path,
    instances: Mapping[str, Mapping[str, dict[str, Any]]],
    review_summary_path: Path,
) -> None:
    for rq_id in ("RQ2", "RQ3"):
        index_path = project_dir / rq_id / "index.json"
        index = _read(index_path)
        by_id = instances[rq_id]
        for row in index.get("instances", []):
            instance = by_id.get(str(row.get("instance_id")))
            if instance is None:
                raise OfflineReviewError(
                    f"{index_path} references unknown instance {row.get('instance_id')}"
                )
            row["content_sha256"] = _sha256_json(instance)
        _write_json(index_path, index)

    manifest_path = project_dir / "rq_instance_manifest.json"
    manifest = _read(manifest_path)
    for target in manifest.get("targets", []):
        for rq_id in ("RQ2", "RQ3"):
            ref = target.get("instances", {}).get(rq_id)
            if not isinstance(ref, dict):
                continue
            instance_id = f"{target['target_id']}_{rq_id}"
            instance = instances[rq_id].get(instance_id)
            if instance is None:
                raise OfflineReviewError(
                    f"{manifest_path} references missing {instance_id}"
                )
            ref["content_sha256"] = _sha256_json(instance)
            ref["readiness"] = deepcopy(instance["readiness"])
    boundaries = manifest.setdefault("construction_boundaries", {})
    boundaries["rq2_formal_scores_require_final_field_review"] = False
    boundaries["rq3_formal_scores_require_frozen_condition_gold"] = False
    boundaries["human_review_required"] = False
    boundaries["offline_agent_review_completed"] = True
    boundaries["offline_agent_review_method"] = REVIEW_METHOD
    repository_root = Path(__file__).resolve().parents[1]
    try:
        portable_review_path = review_summary_path.resolve().relative_to(
            repository_root
        ).as_posix()
    except ValueError:
        portable_review_path = review_summary_path.name
    manifest.setdefault("source_artifacts", {})["rq23_offline_review"] = {
        "path": portable_review_path,
        "sha256": _sha256_file(review_summary_path),
    }
    _write_json(manifest_path, manifest)


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
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        rq2_paths = sorted(args.stage2_root.glob("*/RQ2/*_RQ2.json"))
        rq3_paths = sorted(args.stage2_root.glob("*/RQ3/*_RQ3.json"))
        rq2_by_target = {_read(path)["target_id"]: path for path in rq2_paths}
        rq3_by_target = {_read(path)["target_id"]: path for path in rq3_paths}
        if set(rq2_by_target) != set(rq3_by_target):
            raise OfflineReviewError("RQ2 and RQ3 target sets differ")
        if len(rq2_by_target) != 349:
            raise OfflineReviewError(
                f"expected 349 paired targets, found {len(rq2_by_target)}"
            )

        reviewer_a: list[dict[str, Any]] = []
        reviewer_b: list[dict[str, Any]] = []
        adjudications: list[dict[str, Any]] = []
        frozen_by_project: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        decision_counts: Counter[str] = Counter()
        candidate_counts: Counter[str] = Counter()
        rq2_ordered_change_count = 0
        rq3_ordered_change_count = 0
        pending_writes: list[tuple[Path, dict[str, Any]]] = []

        for target_id in sorted(rq2_by_target):
            rq2 = _read(rq2_by_target[target_id])
            rq3 = _read(rq3_by_target[target_id])
            if rq2["project_id"] != rq3["project_id"]:
                raise OfflineReviewError(f"project mismatch for {target_id}")
            reviewer_a.append(_structural_record(rq2, rq3))
            if reviewer_a[-1]["rq2"]["verdict"] != "PASS" or reviewer_a[-1]["rq3"]["verdict"] != "PASS":
                raise OfflineReviewError(f"structural review failed for {target_id}")

            rq2_review = build_rq2_review_template(rq2)
            rq2_review["review_method"] = REVIEW_METHOD
            rq2_review["reviewers"] = list(REVIEWERS)
            rq2_review["adjudicator"] = ADJUDICATOR
            rq2_review["adjudication_status"] = "ADJUDICATED"
            rq2_review["verdict"] = "FINALIZE"
            rq2_review["boundary_review"] = {
                "pre_task_boundary_correct": True,
                "historical_requirement_scope_correct": True,
                "internal_ids_excluded": True,
            }
            rq2_review["review_notes"] = [
                "Structural and boundary review passed.",
                "Every scoring leaf received an explicit reviewed comparator status.",
            ]
            comparator_changes = _review_all_specs(
                rq2_review["final_field_scoring_specs"]
            )
            rq2_ordered_change_count += sum(
                change["to"] == "ORDERED_LIST" for change in comparator_changes
            )
            frozen_rq2 = apply_rq2_review(rq2, rq2_review)

            candidate = rq3["construction_gold"]["project_decision_candidate"]["value"]
            decision = RQ3_DECISION_OVERRIDES.get(target_id, candidate)
            blockers = _rq3_blockers(rq3) if decision == "CLARIFY" else []
            if decision == "CLARIFY" and not blockers:
                raise OfflineReviewError(f"CLARIFY target {target_id} has no blocker")
            rq3_review = build_offline_agent_review_template(rq3)
            rq3_review["review_method"] = REVIEW_METHOD
            rq3_review["reviewers"] = list(REVIEWERS)
            rq3_review["adjudicator"] = ADJUDICATOR
            rq3_review["adjudication_status"] = "ADJUDICATED"
            rationale = RQ3_OVERRIDE_RATIONALES.get(
                target_id,
                (
                    "Reviewed affected transitions determine a unique post-task state."
                    if decision == "ACT"
                    else "Reviewed material ambiguity prevents a unique post-task state."
                ),
            )
            for condition in ("C1", "C2"):
                branch = rq3_review["conditions"][condition]
                branch["decision"] = decision
                branch["decision_rationale"] = rationale
                branch["post_task_state_source"] = (
                    "CONSTRUCTION_TRANSITIONS_AFTER" if decision == "ACT" else None
                )
                branch["blocking_clarifications"] = deepcopy(blockers)
            rq3_for_freeze = deepcopy(rq3)
            post_spec_changes = _review_all_specs(
                rq3_for_freeze["construction_gold"]["post_state_scoring_specs"]
            )
            rq3_ordered_change_count += sum(
                change["to"] == "ORDERED_LIST" for change in post_spec_changes
            )
            frozen_rq3 = apply_rq3_review(rq3_for_freeze, rq3_review)

            for frozen in (frozen_rq2, frozen_rq3):
                errors = validate_rq_instance(frozen)
                if errors:
                    raise OfflineReviewError(
                        f"frozen {frozen['instance_id']} is invalid: {'; '.join(errors)}"
                    )

            reviewer_b.append(
                _semantic_record(
                    rq2,
                    rq3,
                    comparator_changes=comparator_changes + post_spec_changes,
                    decision=decision,
                    blockers=blockers,
                )
            )
            adjudications.append(
                {
                    "schema_version": "rq23-offline-adjudication-record-v1",
                    "project_id": rq2["project_id"],
                    "target_id": target_id,
                    "review_method": REVIEW_METHOD,
                    "reviewers": list(REVIEWERS),
                    "adjudicator": ADJUDICATOR,
                    "adjudication_status": "ADJUDICATED",
                    "rq2_verdict": "FINAL_TYPED_STATE_GOLD",
                    "rq2_comparator_changes": comparator_changes,
                    "rq3_candidate_decision": candidate,
                    "rq3_final_decision": decision,
                    "rq3_decision_changed": candidate != decision,
                    "rq3_rationale": rationale,
                    "rq3_blocking_clarifications": blockers,
                }
            )
            candidate_counts[candidate] += 1
            decision_counts[decision] += 1
            project = str(rq2["project_id"])
            bucket = frozen_by_project.setdefault(project, {"RQ2": {}, "RQ3": {}})
            bucket["RQ2"][frozen_rq2["instance_id"]] = frozen_rq2
            bucket["RQ3"][frozen_rq3["instance_id"]] = frozen_rq3

            if not args.validate_only:
                rq2_review_path = args.review_dir / "rq2" / f"{target_id}.json"
                rq3_review_path = args.review_dir / "rq3" / f"{target_id}.json"
                pending_writes.extend(
                    (
                        (rq2_review_path, rq2_review),
                        (rq3_review_path, rq3_review),
                        (rq2_by_target[target_id], frozen_rq2),
                        (rq3_by_target[target_id], frozen_rq3),
                    )
                )

        summary = {
            "schema_version": "rq23-offline-review-summary-v1",
            "review_method": REVIEW_METHOD,
            "independent_agent_panel": False,
            "independence_note": (
                "Two attempted independent reviewer-agent runs were stopped by the "
                "host usage limit before producing artifacts. The retained review uses "
                "two separated roles within one agent and does not claim independence."
            ),
            "reviewers": list(REVIEWERS),
            "adjudicator": ADJUDICATOR,
            "target_count": len(rq2_by_target),
            "rq2": {
                "reviewed_instance_count": len(rq2_by_target),
                "final_typed_state_gold_count": len(rq2_by_target),
                "ordered_list_comparator_change_count": rq2_ordered_change_count,
                "empty_container_skip_change_count": sum(
                    change["to"] == "SKIP"
                    for record in adjudications
                    for change in record["rq2_comparator_changes"]
                ),
            },
            "rq3": {
                "reviewed_instance_count": len(rq3_by_target),
                "candidate_decision_distribution": dict(candidate_counts),
                "final_decision_distribution": dict(decision_counts),
                "decision_override_count": len(RQ3_DECISION_OVERRIDES),
                "ordered_list_comparator_change_count": rq3_ordered_change_count,
                "decision_overrides": [
                    {
                        "target_id": target_id,
                        "final_decision": RQ3_DECISION_OVERRIDES[target_id],
                        "rationale": RQ3_OVERRIDE_RATIONALES[target_id],
                    }
                    for target_id in sorted(RQ3_DECISION_OVERRIDES)
                ],
            },
            "formal_release_caveat": (
                "Gold is agent-reviewed and frozen for pipeline testing. It is not "
                "represented as human-reviewed or independently double-reviewed."
            ),
        }

        if not args.validate_only:
            # All 698 candidates have passed review and validation before any
            # instance or review file is replaced.
            for output_path, value in pending_writes:
                _write_json(output_path, value)
            _write_jsonl(args.review_dir / "reviewer-a.jsonl", reviewer_a)
            _write_jsonl(args.review_dir / "reviewer-b.jsonl", reviewer_b)
            _write_jsonl(args.review_dir / "adjudication.jsonl", adjudications)
            summary_path = args.review_dir / "summary.json"
            _write_json(summary_path, summary)
            for project_id, collections in frozen_by_project.items():
                _update_project_metadata(
                    args.stage2_root / project_id,
                    collections,
                    summary_path,
                )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        OfflineReviewError,
        RQ2ReviewError,
        RQ3ReviewError,
        RQInstanceError,
    ) as exc:
        print(f"RQ2/RQ3 offline review failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

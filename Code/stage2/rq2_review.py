"""Offline-agent review and deterministic freezing for RQ2 typed Gold."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterator, Mapping


REVIEW_SCHEMA_VERSION = "rq2-offline-agent-review-v1"
FINAL_STATUS = "FINAL_TYPED_STATE_GOLD"
PENDING_REVIEW_STATUSES = {
    "PENDING_COMPARATOR_REVIEW",
    "REQUIRES_FIELD_REVIEW",
    "REQUIRES_FROZEN_SEMANTIC_JUDGE",
}
CONTAINER_COMPARATORS = {"RECURSIVE_FIELDS", "UNORDERED_RECORD_F1"}
ALLOWED_COMPARATORS = {
    "BOOLEAN_EXACT",
    "NORMALIZED_EXACT",
    "NUMBER_EXACT",
    "SET_F1",
    "ORDERED_LIST",
    "RECURSIVE_FIELDS",
    "UNORDERED_RECORD_F1",
    "SEMANTIC_FACT",
    "NUMERIC_TOLERANCE",
    "NULL_EXACT",
    "SKIP",
}
ALLOWED_REVIEW_METHODS = {
    "OFFLINE_AGENT_PANEL",
    "SINGLE_AGENT_ROLE_SEPARATED_PANEL",
}


class RQ2ReviewError(ValueError):
    """An RQ2 field review cannot be frozen as final Gold."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQ2ReviewError(f"{label} must be a non-empty string")
    return value.strip()


def _leaf_specs(
    value: Mapping[str, Any], path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Mapping[str, Any]]]:
    comparator = value.get("comparator")
    if comparator is not None:
        child_key = None
        if comparator == "RECURSIVE_FIELDS":
            child_key = "fields"
        elif comparator == "UNORDERED_RECORD_F1":
            child_key = "item_fields"
        children = value.get(child_key) if child_key is not None else None
        if isinstance(children, Mapping) and children:
            for key, child in children.items():
                if not isinstance(child, Mapping):
                    raise RQ2ReviewError(
                        f"scoring spec {'.'.join(path + (str(key),))} must be an object"
                    )
                yield from _leaf_specs(child, path + (str(key),))
            return
        yield path, value
        return
    for key, child in value.items():
        if not isinstance(child, Mapping):
            raise RQ2ReviewError(
                f"scoring spec {'.'.join(path + (str(key),))} must be an object"
            )
        yield from _leaf_specs(child, path + (str(key),))


def _reviewed_leaf(spec: Mapping[str, Any], label: str) -> None:
    comparator = spec.get("comparator")
    if comparator not in ALLOWED_COMPARATORS:
        raise RQ2ReviewError(f"{label} has unsupported comparator {comparator!r}")
    if not isinstance(spec.get("score"), bool):
        raise RQ2ReviewError(f"{label}.score must be boolean")
    status = spec.get("review_status")
    if status in PENDING_REVIEW_STATUSES or not isinstance(status, str):
        raise RQ2ReviewError(f"{label} has not been reviewed")
    if comparator == "SKIP" and spec.get("score") is not False:
        raise RQ2ReviewError(f"{label} SKIP must use score=false")
    if comparator != "SKIP" and spec.get("score") is not True:
        raise RQ2ReviewError(f"{label} non-SKIP comparator must use score=true")
    if comparator == "NUMERIC_TOLERANCE":
        tolerance = spec.get("tolerance")
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
            raise RQ2ReviewError(f"{label} requires numeric tolerance")
    if comparator in CONTAINER_COMPARATORS:
        raise RQ2ReviewError(f"{label} container comparator has no reviewed children")


def build_review_template(instance: Mapping[str, Any]) -> dict[str, Any]:
    if instance.get("rq_id") != "RQ2":
        raise RQ2ReviewError("instance.rq_id must be RQ2")
    gold = instance.get("construction_gold")
    if not isinstance(gold, Mapping):
        raise RQ2ReviewError("construction_gold must be an object")
    specs = gold.get("field_scoring_specs")
    states = gold.get("states")
    if not isinstance(specs, Mapping) or not isinstance(states, Mapping):
        raise RQ2ReviewError("RQ2 Gold requires states and field_scoring_specs")
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "target_id": deepcopy(instance.get("target_id")),
        "review_method": "OFFLINE_AGENT_PANEL",
        "reviewers": [],
        "adjudicator": None,
        "adjudication_status": "PENDING",
        "verdict": None,
        "boundary_review": {
            "pre_task_boundary_correct": None,
            "historical_requirement_scope_correct": None,
            "internal_ids_excluded": None,
        },
        "reviewed_states": deepcopy(states),
        "final_field_scoring_specs": deepcopy(specs),
        "review_notes": [],
    }


def validate_review(instance: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    if instance.get("rq_id") != "RQ2":
        raise RQ2ReviewError("instance.rq_id must be RQ2")
    if review.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise RQ2ReviewError("invalid review schema_version")
    if str(review.get("target_id")) != str(instance.get("target_id")):
        raise RQ2ReviewError("review target_id does not match instance")
    if review.get("review_method") not in ALLOWED_REVIEW_METHODS:
        raise RQ2ReviewError("review_method is not an allowed offline review method")
    reviewers = review.get("reviewers")
    if not isinstance(reviewers, list) or len({_text(v, "reviewers[]") for v in reviewers}) < 2:
        raise RQ2ReviewError("final RQ2 Gold requires two distinct reviewers")
    adjudicator = _text(review.get("adjudicator"), "adjudicator")
    if adjudicator in {str(value).strip() for value in reviewers}:
        raise RQ2ReviewError("adjudicator must be distinct from the two reviewers")
    if review.get("adjudication_status") != "ADJUDICATED":
        raise RQ2ReviewError("review must be ADJUDICATED")
    if review.get("verdict") != "FINALIZE":
        raise RQ2ReviewError("only a FINALIZE verdict can freeze RQ2 Gold")
    boundary = review.get("boundary_review")
    required_boundary = {
        "pre_task_boundary_correct",
        "historical_requirement_scope_correct",
        "internal_ids_excluded",
    }
    if not isinstance(boundary, Mapping) or set(boundary) != required_boundary:
        raise RQ2ReviewError("boundary_review has invalid fields")
    if any(boundary[name] is not True for name in required_boundary):
        raise RQ2ReviewError("all RQ2 boundary checks must pass")

    gold = instance.get("construction_gold")
    requirement_ids = gold.get("gold_requirement_ids", [])
    reviewed_states = review.get("reviewed_states")
    final_specs = review.get("final_field_scoring_specs")
    if not isinstance(reviewed_states, Mapping) or set(reviewed_states) != set(requirement_ids):
        raise RQ2ReviewError("reviewed_states must equal gold_requirement_ids")
    if not isinstance(final_specs, Mapping) or set(final_specs) != set(requirement_ids):
        raise RQ2ReviewError("final_field_scoring_specs must equal gold_requirement_ids")
    for requirement_id in requirement_ids:
        spec = final_specs[requirement_id]
        if not isinstance(spec, Mapping):
            raise RQ2ReviewError(f"specs for {requirement_id} must be an object")
        leaves = list(_leaf_specs(spec))
        if not leaves:
            raise RQ2ReviewError(f"specs for {requirement_id} contain no score leaves")
        for path, leaf in leaves:
            _reviewed_leaf(leaf, f"{requirement_id}.{'.'.join(path)}")
    notes = review.get("review_notes")
    if not isinstance(notes, list):
        raise RQ2ReviewError("review_notes must be an array")
    for note in notes:
        _text(note, "review_notes[]")


def apply_review(instance: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]:
    validate_review(instance, review)
    output = deepcopy(dict(instance))
    gold = output["construction_gold"]
    gold["states"] = deepcopy(review["reviewed_states"])
    gold["field_scoring_specs"] = deepcopy(review["final_field_scoring_specs"])
    gold["status"] = FINAL_STATUS
    gold["review_status"] = "OFFLINE_AGENT_REVIEWED_AND_ADJUDICATED"
    gold["review_metadata"] = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_method": review["review_method"],
        "reviewers": deepcopy(review["reviewers"]),
        "adjudicator": review["adjudicator"],
        "adjudication_status": review["adjudication_status"],
        "boundary_review": deepcopy(review["boundary_review"]),
        "review_notes": deepcopy(review["review_notes"]),
    }
    output["readiness"] = {
        "construction": "COMPLETE",
        "smoke_allowed": True,
        "formal_reasoning_allowed": True,
        "formal_execution_allowed": False,
        "blockers": [],
    }
    return output


__all__ = [
    "FINAL_STATUS",
    "REVIEW_SCHEMA_VERSION",
    "RQ2ReviewError",
    "apply_review",
    "build_review_template",
    "validate_review",
]

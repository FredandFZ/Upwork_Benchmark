"""Human-review templates and deterministic freezing for RQ3 Gold."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


REVIEW_SCHEMA_VERSION = "rq3-human-review-v2"
OFFLINE_AGENT_REVIEW_SCHEMA_VERSION = "rq3-offline-agent-review-v1"
CONDITIONS = ("C1", "C2")
DIMENSIONS = ("VALUE", "SCOPE", "LIFECYCLE", "BEHAVIOR", "DEPENDENCY", "EXECUTION")
OFFLINE_REVIEW_METHODS = {
    "OFFLINE_AGENT_PANEL",
    "SINGLE_AGENT_ROLE_SEPARATED_PANEL",
}


class RQ3ReviewError(ValueError):
    """An RQ3 review cannot be frozen as final Gold."""


def build_review_template(instance: Mapping[str, Any]) -> dict[str, Any]:
    if instance.get("rq_id") != "RQ3":
        raise RQ3ReviewError("instance.rq_id must be RQ3")
    gold = instance.get("construction_gold")
    if not isinstance(gold, Mapping):
        raise RQ3ReviewError("construction_gold must be an object")
    candidates = gold.get("decision_candidates_by_condition", {})
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "target_id": deepcopy(instance.get("target_id")),
        "reviewers": [],
        "adjudication_status": "PENDING",
        "conditions": {
            condition: {
                "candidate_decision": deepcopy(
                    candidates.get(condition, {}).get("value")
                    if isinstance(candidates.get(condition), Mapping)
                    else None
                ),
                "decision": None,
                "decision_rationale": None,
                "post_task_state_source": None,
                "blocking_clarifications": [],
            }
            for condition in CONDITIONS
        },
        "blocking_ambiguity_candidates": deepcopy(
            gold.get("blocking_ambiguity_candidates", [])
        ),
        "review_instruction": (
            "Review each condition independently. ACT requires the reviewed "
            "construction transition after-state for every affected Requirement. "
            "CLARIFY requires all material blocking issues and acceptable question facts."
        ),
    }


def build_offline_agent_review_template(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Build the RQ3 template used by two offline reviewers and an adjudicator."""

    review = build_review_template(instance)
    review["schema_version"] = OFFLINE_AGENT_REVIEW_SCHEMA_VERSION
    review["review_method"] = "OFFLINE_AGENT_PANEL"
    review["adjudicator"] = None
    review["review_instruction"] = (
        "Two offline reviewer agents inspect each condition independently. "
        "A distinct adjudicator resolves conflicts. ACT requires reviewed "
        "construction after-states for every affected Requirement. CLARIFY "
        "requires every material unresolved blocker and acceptable question facts."
    )
    return review


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RQ3ReviewError(f"{label} must be a non-empty string")
    return value.strip()


def validate_review(instance: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    schema_version = review.get("schema_version")
    if schema_version not in {
        REVIEW_SCHEMA_VERSION,
        OFFLINE_AGENT_REVIEW_SCHEMA_VERSION,
    }:
        raise RQ3ReviewError("invalid review schema_version")
    if str(review.get("target_id")) != str(instance.get("target_id")):
        raise RQ3ReviewError("review target_id does not match instance")
    reviewers = review.get("reviewers")
    if not isinstance(reviewers, list) or len({_text(v, "reviewers[]") for v in reviewers}) < 2:
        raise RQ3ReviewError("final RQ3 Gold requires two distinct reviewers")
    if review.get("adjudication_status") != "ADJUDICATED":
        raise RQ3ReviewError("review must be ADJUDICATED")
    if schema_version == OFFLINE_AGENT_REVIEW_SCHEMA_VERSION:
        if review.get("review_method") not in OFFLINE_REVIEW_METHODS:
            raise RQ3ReviewError("offline review_method is not allowed")
        adjudicator = _text(review.get("adjudicator"), "adjudicator")
        if adjudicator in {str(value).strip() for value in reviewers}:
            raise RQ3ReviewError(
                "offline adjudicator must be distinct from the two reviewers"
            )
    conditions = review.get("conditions")
    if not isinstance(conditions, Mapping) or set(conditions) != set(CONDITIONS):
        raise RQ3ReviewError("review.conditions must contain exactly C1 and C2")
    gold = instance.get("construction_gold")
    affected = set(gold.get("affected_requirement_ids", []))
    for condition in CONDITIONS:
        branch = conditions[condition]
        if not isinstance(branch, Mapping):
            raise RQ3ReviewError(f"conditions.{condition} must be an object")
        decision = branch.get("decision")
        if decision not in {"ACT", "CLARIFY"}:
            raise RQ3ReviewError(f"conditions.{condition}.decision must be ACT or CLARIFY")
        _text(branch.get("decision_rationale"), f"conditions.{condition}.decision_rationale")
        blockers = branch.get("blocking_clarifications")
        if not isinstance(blockers, list):
            raise RQ3ReviewError(
                f"conditions.{condition}.blocking_clarifications must be an array"
            )
        if decision == "ACT":
            if branch.get("post_task_state_source") != "CONSTRUCTION_TRANSITIONS_AFTER":
                raise RQ3ReviewError(
                    f"conditions.{condition} ACT must use reviewed construction after-states"
                )
            if blockers:
                raise RQ3ReviewError(f"conditions.{condition} ACT cannot contain blockers")
            continue
        if branch.get("post_task_state_source") is not None:
            raise RQ3ReviewError(
                f"conditions.{condition} CLARIFY cannot have a post-state source"
            )
        if not blockers:
            raise RQ3ReviewError(f"conditions.{condition} CLARIFY requires blockers")
        for index, blocker in enumerate(blockers):
            if not isinstance(blocker, Mapping):
                raise RQ3ReviewError(
                    f"conditions.{condition}.blocking_clarifications[{index}] must be an object"
                )
            requirement_id = blocker.get("requirement_id")
            if requirement_id not in affected:
                raise RQ3ReviewError(
                    f"conditions.{condition} blocker references a non-affected Requirement"
                )
            if blocker.get("dimension") not in DIMENSIONS:
                raise RQ3ReviewError(
                    f"conditions.{condition} blocker has invalid dimension"
                )
            if blocker.get("field") is not None:
                _text(blocker.get("field"), f"conditions.{condition}.blocker.field")
            _text(
                blocker.get("missing_information"),
                f"conditions.{condition}.blocker.missing_information",
            )
            facts = blocker.get("acceptable_question_facts")
            if not isinstance(facts, list) or not facts:
                raise RQ3ReviewError(
                    f"conditions.{condition} blocker requires acceptable_question_facts"
                )
            for fact in facts:
                _text(fact, f"conditions.{condition}.acceptable_question_facts[]")
    if conditions["C1"].get("decision") != conditions["C2"].get("decision"):
        raise RQ3ReviewError("C1 and C2 must freeze the same decision")
    if conditions["C1"].get("blocking_clarifications") != conditions["C2"].get(
        "blocking_clarifications"
    ):
        raise RQ3ReviewError(
            "C1 and C2 must freeze the same blocking clarifications"
        )


def apply_review(instance: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]:
    validate_review(instance, review)
    output = deepcopy(dict(instance))
    gold = output["construction_gold"]
    frozen: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        branch = review["conditions"][condition]
        if branch["decision"] == "ACT":
            frozen[condition] = {
                "decision": "ACT",
                "post_task_states": deepcopy(gold["post_task_states"]),
                "blocking_clarifications": [],
            }
        else:
            frozen[condition] = {
                "decision": "CLARIFY",
                "post_task_states": None,
                "blocking_clarifications": deepcopy(
                    branch["blocking_clarifications"]
                ),
            }
    gold["final_gold_by_condition"] = frozen
    gold["status"] = "FINAL_UPDATE_OR_CLARIFY_GOLD"
    offline_agent_review = (
        review.get("schema_version") == OFFLINE_AGENT_REVIEW_SCHEMA_VERSION
    )
    gold["review_status"] = (
        "OFFLINE_AGENT_REVIEWED_AND_ADJUDICATED"
        if offline_agent_review
        else "HUMAN_REVIEWED_AND_ADJUDICATED"
    )
    gold["review_metadata"] = {
        "schema_version": review["schema_version"],
        "review_method": (
            review.get("review_method") if offline_agent_review else "HUMAN_PANEL"
        ),
        "reviewers": deepcopy(review["reviewers"]),
        "adjudicator": review.get("adjudicator"),
        "adjudication_status": review["adjudication_status"],
        "condition_gold_consistent": True,
        "decision_rationales": {
            condition: review["conditions"][condition]["decision_rationale"]
            for condition in CONDITIONS
        },
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
    "CONDITIONS",
    "DIMENSIONS",
    "OFFLINE_AGENT_REVIEW_SCHEMA_VERSION",
    "REVIEW_SCHEMA_VERSION",
    "RQ3ReviewError",
    "apply_review",
    "build_offline_agent_review_template",
    "build_review_template",
    "validate_review",
]

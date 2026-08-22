from __future__ import annotations

import unittest

from Code.stage2.state_graph import build_requirement_state_graph
from Code.stage2.task_gold import (
    audit_event_provenance,
    build_evaluation_instances,
    build_gold_states,
    validate_evaluation_instances,
    validate_gold_states,
)


def event(
    requirement_id: str,
    number: int,
    message_id: int,
    event_type: str,
    *,
    value_updates=None,
    value_removals=None,
    scope_updates=None,
    ambiguity=None,
    execution=None,
    speaker: str = "client",
):
    return {
        "event_id": f"{requirement_id}_E{number:03d}",
        "source_message": {
            "message_id": message_id,
            "speaker": speaker,
            "text": f"message {message_id}",
        },
        "event_type": event_type,
        "value_updates": value_updates,
        "value_removals": value_removals,
        "scope_updates": scope_updates,
        "ambiguity": ambiguity,
        "execution": execution,
    }


def requirement(requirement_id: str, events, family_id: str | None = None):
    return {
        "requirement_id": requirement_id,
        "title": requirement_id,
        "family_id": family_id,
        "events": events,
    }


def annotation(*requirements):
    return {
        "project": {"project_id": "P1", "project_title": "Project"},
        "requirements": list(requirements),
    }


def artifacts(stage1):
    graph = build_requirement_state_graph(stage1)
    gold = build_gold_states(stage1, graph)
    instances = build_evaluation_instances(gold, graph)
    return graph, gold, instances


def task(items, message_id: int):
    return next(
        item
        for item in items
        if item["target_task"]["source_message_id"] == message_id
    )


class TaskGoldTests(unittest.TestCase):
    def test_one_task_modifies_one_requirement(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"x": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"x": 2}),
                ],
            )
        )
        _, gold, instances = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        self.assertEqual(target["affected_requirement_ids"], ["REQ_A"])
        transition = task(instances["instances"], 2)["rq_gold"]["RQ3"][
            "requirement_transitions"
        ]["REQ_A"]
        self.assertEqual(transition["before_state_id"], "REQ_A_S001")
        self.assertEqual(transition["after_state_id"], "REQ_A_S002")

    def test_one_task_modifies_multiple_requirements(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_B",
                [
                    event("REQ_B", 1, 1, "INTRODUCE", value_updates={"b": 1}),
                    event("REQ_B", 2, 2, "MODIFY", value_updates={"b": 2}),
                ],
            ),
        )
        _, gold, _ = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        self.assertEqual(
            target["task_event_ids"], ["REQ_A_E002", "REQ_B_E002"]
        )
        self.assertEqual(target["affected_requirement_ids"], ["REQ_A", "REQ_B"])

    def test_unaffected_requirement_is_in_both_complete_snapshots(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_C",
                [event("REQ_C", 1, 1, "INTRODUCE", value_updates={"c": 1})],
            ),
        )
        _, gold, _ = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        pre = {row["requirement_id"]: row["state_id"] for row in target[
            "pre_task_gold_state"
        ]["requirement_states"]}
        post = {row["requirement_id"]: row["state_id"] for row in target[
            "post_task_gold_state"
        ]["requirement_states"]}
        self.assertEqual(pre["REQ_C"], "REQ_C_S001")
        self.assertEqual(post["REQ_C"], "REQ_C_S001")

    def test_remove_remains_in_post_snapshot(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "REMOVE"),
                ],
            )
        )
        graph, gold, instances = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        post_id = target["post_task_gold_state"]["requirement_states"][0]["state_id"]
        node = graph["requirement_graphs"][0]["nodes"][1]
        self.assertEqual(post_id, "REQ_A_S002")
        self.assertEqual(node["lifecycle_status"], "REMOVED")
        actions = task(instances["instances"], 2)["rq_gold"]["RQ4"]["REQ_A"]
        self.assertEqual(actions["dimension_actions"]["lifecycle_status"], "OVERRIDE")

    def test_defer_and_resume_retrieve_correct_lifecycle(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "DEFER"),
                    event("REQ_A", 3, 3, "RESUME"),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        deferred = task(instances["instances"], 2)["rq_gold"]["RQ3"][
            "requirement_transitions"
        ]["REQ_A"]
        resumed = task(instances["instances"], 3)["rq_gold"]["RQ3"][
            "requirement_transitions"
        ]["REQ_A"]
        self.assertEqual(deferred["lifecycle_after"], "DEFERRED")
        self.assertEqual(resumed["lifecycle_before"], "DEFERRED")
        self.assertEqual(resumed["lifecycle_after"], "ACTIVE")

    def test_introduce_is_absent_pre_and_rq2_ineligible(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_NEW",
                [event("REQ_NEW", 1, 2, "INTRODUCE", value_updates={"n": True})],
            )
        )
        _, gold, instances = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        self.assertEqual(target["pre_task_gold_state"]["requirement_states"], [])
        instance = task(instances["instances"], 2)
        self.assertFalse(instance["rq_eligibility"]["RQ2"])
        self.assertEqual(instance["rq_gold"]["RQ2"], {})
        self.assertIsNone(
            instance["rq_gold"]["RQ3"]["requirement_transitions"]["REQ_NEW"][
                "before_state_id"
            ]
        )

    def test_open_ambiguity_derives_clarify(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "AMBIGUOUS",
                        ambiguity={"dimension": "VALUE", "description": "a unclear"},
                    ),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        instance = task(instances["instances"], 2)
        action = instance["rq_gold"]["RQ4"]["REQ_A"]
        self.assertEqual(action["requirement_action"], "CLARIFY")
        self.assertEqual(action["ambiguity_dimension"], "VALUE")

    def test_scope_preserved_when_only_value_changes(self) -> None:
        scope = {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["BACKEND"],
            "contexts": ["FLOW"],
        }
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event(
                        "REQ_A",
                        1,
                        1,
                        "INTRODUCE",
                        value_updates={"a": 1},
                        scope_updates=scope,
                    ),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        rq2 = task(instances["instances"], 2)["rq_gold"]["RQ2"]["REQ_A"]
        self.assertEqual(rq2["scope_transition"], "PRESERVED")

    def test_scope_update_is_detected(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event(
                        "REQ_A",
                        1,
                        1,
                        "INTRODUCE",
                        value_updates={"a": 1},
                        scope_updates={
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["BACKEND"],
                            "contexts": ["OLD"],
                        },
                    ),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "MODIFY",
                        scope_updates={
                            "persistence": None,
                            "components": None,
                            "contexts": ["NEW"],
                        },
                    ),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        rq2 = task(instances["instances"], 2)["rq_gold"]["RQ2"]["REQ_A"]
        self.assertEqual(rq2["scope_transition"], "UPDATED")

    def test_rq4_multi_attribute_use_and_override(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event(
                        "REQ_A",
                        1,
                        1,
                        "INTRODUCE",
                        value_updates={"winner_count": 5, "prize_amount": 500},
                    ),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "MODIFY",
                        value_updates={"winner_count": 1},
                    ),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        actions = task(instances["instances"], 2)["rq_gold"]["RQ4"]["REQ_A"][
            "dimension_actions"
        ]
        self.assertEqual(actions["winner_count"], "OVERRIDE")
        self.assertEqual(actions["prize_amount"], "USE")

    def test_future_event_never_leaks_into_current_post_state(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                    event("REQ_A", 3, 3, "MODIFY", value_updates={"a": 3}),
                ],
            )
        )
        graph, gold, instances = artifacts(stage1)
        target = task(gold["task_gold_states"], 2)
        post_id = target["post_task_gold_state"]["requirement_states"][0]["state_id"]
        self.assertEqual(post_id, "REQ_A_S002")
        evidence = task(instances["instances"], 2)["rq_gold"]["RQ1"][
            "historical_evidence"
        ]["REQ_A"]
        self.assertEqual(evidence, ["REQ_A_E001"])
        self.assertEqual(validate_gold_states(gold, graph), [])
        self.assertEqual(validate_evaluation_instances(instances, gold, graph), [])

    def test_execution_only_message_is_not_automatically_a_task(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "RUNTIME_FAILURE",
                        execution={"status": "FAILED", "observed_behavior": "a failed"},
                    ),
                ],
            )
        )
        graph = build_requirement_state_graph(stage1)
        gold = build_gold_states(stage1, graph)
        message_ids = [
            item["target_task"]["source_message_id"]
            for item in gold["task_gold_states"]
        ]
        self.assertEqual(message_ids, [1])
        opted_in = build_gold_states(
            stage1, graph, include_execution_only_tasks=True
        )
        self.assertEqual(
            [item["target_task"]["source_message_id"] for item in opted_in["task_gold_states"]],
            [1, 2],
        )

    def test_upgrade_verified_events_shape_supplies_task_messages(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1})],
            )
        )
        graph = build_requirement_state_graph(stage1)
        verified_events = {
            "REQ_A": [
                {
                    key: value
                    for key, value in stage1["requirements"][0]["events"][0].items()
                    if key != "event_id"
                }
            ]
        }
        gold = build_gold_states(verified_events, graph)
        self.assertEqual(
            gold["task_gold_states"][0]["target_task"]["text"], "message 1"
        )
        self.assertEqual(audit_event_provenance(verified_events, graph), [])

    def test_normalized_project_shape_supplies_complete_message_catalog(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, 2, "INTRODUCE", value_updates={"a": 1})],
            )
        )
        graph = build_requirement_state_graph(stage1)
        normalized_project = {
            "project_id": "P1",
            "messages": [
                {"message_id": 1, "speaker": "freelancer", "text": "context"},
                {"message_id": 2, "speaker": "client", "text": "message 2"},
            ],
        }
        gold = build_gold_states(normalized_project, graph)
        self.assertEqual(
            gold["task_gold_states"][0]["target_task"],
            {"source_message_id": 2, "speaker": "client", "text": "message 2"},
        )

    def test_open_scope_ambiguity_is_rq2_unresolved(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event(
                        "REQ_A",
                        1,
                        1,
                        "INTRODUCE",
                        value_updates={"a": 1},
                        scope_updates={
                            "persistence": "PROJECT_PERSISTENT",
                            "components": ["BACKEND"],
                            "contexts": ["FLOW"],
                        },
                    ),
                    event(
                        "REQ_A",
                        2,
                        2,
                        "AMBIGUOUS",
                        ambiguity={
                            "dimension": "SCOPE",
                            "description": "scope unclear",
                        },
                    ),
                ],
            )
        )
        _, _, instances = artifacts(stage1)
        instance = task(instances["instances"], 2)
        self.assertEqual(
            instance["rq_gold"]["RQ2"]["REQ_A"]["scope_transition"],
            "UNRESOLVED",
        )
        self.assertEqual(
            instance["rq_gold"]["RQ4"]["REQ_A"]["requirement_action"],
            "CLARIFY",
        )


if __name__ == "__main__":
    unittest.main()

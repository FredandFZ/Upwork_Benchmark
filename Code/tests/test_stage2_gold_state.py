from __future__ import annotations

import unittest

from Code.stage2.gold_state import (
    TaskSelectionConfig,
    audit_event_provenance,
    build_gold_states,
    validate_gold_states,
)
from Code.stage2.state_graph import build_requirement_state_graph


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


def requirement(requirement_id: str, events):
    return {
        "requirement_id": requirement_id,
        "title": requirement_id,
        "family_id": None,
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
    return graph, gold


def task(gold, message_id: int):
    return next(
        item
        for item in gold["task_gold_states"]
        if item["target_task"]["source_message_id"] == message_id
    )


def snapshot_map(task_gold, field: str):
    return {
        item["requirement_id"]: item["state_id"]
        for item in task_gold[field]["requirement_states"]
    }


class GoldStateTests(unittest.TestCase):
    def test_one_task_one_requirement_one_event(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, 1, "INTRODUCE", value_updates={"x": 1})],
            )
        )
        graph, gold = artifacts(stage1)
        target = task(gold, 1)
        self.assertEqual(target["task_event_ids"], ["REQ_A_E001"])
        self.assertEqual(target["affected_requirement_ids"], ["REQ_A"])
        self.assertEqual(target["pre_task_gold_state"]["requirement_states"], [])
        self.assertEqual(
            snapshot_map(target, "post_task_gold_state"), {"REQ_A": "REQ_A_S001"}
        )
        self.assertEqual(validate_gold_states(gold, graph), [])

    def test_one_task_multiple_requirements(self) -> None:
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
        _, gold = artifacts(stage1)
        target = task(gold, 2)
        self.assertEqual(target["task_event_ids"], ["REQ_A_E002", "REQ_B_E002"])
        self.assertEqual(target["affected_requirement_ids"], ["REQ_A", "REQ_B"])

    def test_same_task_replays_all_events_for_one_requirement(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                    event(
                        "REQ_A",
                        3,
                        2,
                        "AMBIGUOUS",
                        ambiguity={"dimension": "VALUE", "description": "unclear"},
                    ),
                ],
            )
        )
        _, gold = artifacts(stage1)
        target = task(gold, 2)
        self.assertEqual(target["task_event_ids"], ["REQ_A_E002", "REQ_A_E003"])
        self.assertEqual(snapshot_map(target, "pre_task_gold_state")["REQ_A"], "REQ_A_S001")
        self.assertEqual(snapshot_map(target, "post_task_gold_state")["REQ_A"], "REQ_A_S003")

    def test_preserved_requirement_reuses_state(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_KEEP",
                [event("REQ_KEEP", 1, 1, "INTRODUCE", value_updates={"k": 1})],
            ),
        )
        _, gold = artifacts(stage1)
        target = task(gold, 2)
        pre = snapshot_map(target, "pre_task_gold_state")
        post = snapshot_map(target, "post_task_gold_state")
        self.assertEqual(target["preserved_requirement_ids"], ["REQ_KEEP"])
        self.assertEqual(pre["REQ_KEEP"], post["REQ_KEEP"])

    def test_remove_is_retained_as_removed_state(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "REMOVE"),
                ],
            )
        )
        graph, gold = artifacts(stage1)
        target = task(gold, 2)
        self.assertEqual(snapshot_map(target, "pre_task_gold_state")["REQ_A"], "REQ_A_S001")
        self.assertEqual(snapshot_map(target, "post_task_gold_state")["REQ_A"], "REQ_A_S002")
        self.assertEqual(
            graph["requirement_graphs"][0]["nodes"][1]["lifecycle_status"],
            "REMOVED",
        )

    def test_defer_and_resume_lifecycle(self) -> None:
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
        graph, gold = artifacts(stage1)
        deferred = task(gold, 2)
        resumed = task(gold, 3)
        self.assertEqual(snapshot_map(deferred, "post_task_gold_state")["REQ_A"], "REQ_A_S002")
        self.assertEqual(snapshot_map(resumed, "pre_task_gold_state")["REQ_A"], "REQ_A_S002")
        self.assertEqual(snapshot_map(resumed, "post_task_gold_state")["REQ_A"], "REQ_A_S003")
        nodes = graph["requirement_graphs"][0]["nodes"]
        self.assertEqual(nodes[1]["lifecycle_status"], "DEFERRED")
        self.assertEqual(nodes[2]["lifecycle_status"], "ACTIVE")

    def test_ambiguous_post_state_is_open(self) -> None:
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
                        ambiguity={"dimension": "VALUE", "description": "unclear"},
                    ),
                ],
            )
        )
        graph, gold = artifacts(stage1)
        target = task(gold, 2)
        self.assertEqual(snapshot_map(target, "post_task_gold_state")["REQ_A"], "REQ_A_S002")
        self.assertEqual(
            graph["requirement_graphs"][0]["nodes"][1]["ambiguity"]["status"],
            "OPEN",
        )

    def test_future_requirement_is_excluded_from_both_snapshots(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                ],
            ),
            requirement(
                "REQ_FUTURE",
                [event("REQ_FUTURE", 1, 3, "INTRODUCE", value_updates={"f": 1})],
            ),
        )
        _, gold = artifacts(stage1)
        target = task(gold, 2)
        self.assertNotIn("REQ_FUTURE", snapshot_map(target, "pre_task_gold_state"))
        self.assertNotIn("REQ_FUTURE", snapshot_map(target, "post_task_gold_state"))

    def test_execution_only_message_is_excluded_by_default(self) -> None:
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
                        execution={"status": "FAILED", "observed_behavior": "failed"},
                    ),
                ],
            )
        )
        graph = build_requirement_state_graph(stage1)
        default_gold = build_gold_states(stage1, graph)
        included_gold = build_gold_states(
            stage1, graph, include_execution_only_tasks=True
        )
        self.assertEqual(
            [item["target_task"]["source_message_id"] for item in default_gold["task_gold_states"]],
            [1],
        )
        self.assertEqual(
            [item["target_task"]["source_message_id"] for item in included_gold["task_gold_states"]],
            [1, 2],
        )

    def test_graph_only_source_marks_metadata_unavailable(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1})],
            )
        )
        graph = build_requirement_state_graph(stage1)
        gold = build_gold_states(None, graph)
        self.assertEqual(
            gold["task_gold_states"][0]["target_task"],
            {"source_message_id": 1, "speaker": None, "text": None},
        )

    def test_sampling_uses_highest_priority_event_on_task(self) -> None:
        stage1 = annotation(
            requirement(
                "REQ_A",
                [
                    event("REQ_A", 1, 1, "INTRODUCE", value_updates={"a": 1}),
                    event("REQ_A", 2, 2, "MODIFY", value_updates={"a": 2}),
                    event(
                        "REQ_A",
                        3,
                        2,
                        "AMBIGUOUS",
                        ambiguity={"dimension": "VALUE", "description": "unclear"},
                    ),
                ],
            ),
            *[
                requirement(
                    f"REQ_{message_id}",
                    [event(f"REQ_{message_id}", 1, message_id, "INTRODUCE", value_updates={"x": 1})],
                )
                for message_id in range(3, 10)
            ],
        )
        graph = build_requirement_state_graph(stage1)
        config = TaskSelectionConfig.from_mapping(
            {
                "position_ratio": {"early": 1, "middle": 0, "late": 0},
                "max_tasks_per_project": 1,
                "random_seed": 7,
            }
        )
        gold = build_gold_states(stage1, graph, selection_config=config)
        self.assertEqual(
            gold["task_gold_states"][0]["target_task"]["source_message_id"], 2
        )

    def test_verified_events_can_supply_metadata_and_provenance(self) -> None:
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
        self.assertEqual(gold["task_gold_states"][0]["target_task"]["text"], "message 1")
        self.assertEqual(audit_event_provenance(verified_events, graph), [])


if __name__ == "__main__":
    unittest.main()

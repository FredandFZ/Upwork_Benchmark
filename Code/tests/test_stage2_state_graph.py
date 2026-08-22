from __future__ import annotations

import unittest

from Code.stage2.state_graph import Stage2ReplayError, build_requirement_state_graph


def event(
    number: int,
    event_type: str,
    *,
    value_updates=None,
    value_removals=None,
    scope_updates=None,
    ambiguity=None,
    execution=None,
):
    return {
        "event_id": f"REQ_X_E{number:03d}",
        "source_message": {
            "message_id": number,
            "speaker": "client",
            "text": f"message {number}",
        },
        "event_type": event_type,
        "value_updates": value_updates,
        "value_removals": value_removals,
        "scope_updates": scope_updates,
        "ambiguity": ambiguity,
        "execution": execution,
    }


def annotation(events):
    return {
        "project": {"project_id": "P1", "project_title": "Project"},
        "requirements": [
            {
                "requirement_id": "REQ_X",
                "title": "X",
                "family_id": None,
                "events": events,
            }
        ],
    }


class RequirementStateGraphTests(unittest.TestCase):
    def test_all_state_dimensions_and_minimal_support_are_replayed(self) -> None:
        events = [
            event(
                1,
                "INTRODUCE",
                value_updates={"a": 1, "b": 2},
                scope_updates={
                    "persistence": "PROJECT_PERSISTENT",
                    "components": ["BACKEND"],
                    "contexts": None,
                },
            ),
            event(2, "MODIFY", value_updates={"a": 3}),
            event(
                3,
                "AMBIGUOUS",
                ambiguity={"dimension": "VALUE", "description": "a is unclear"},
            ),
            event(
                4,
                "RUNTIME_FAILURE",
                execution={"status": "FAILED", "observed_behavior": "a failed"},
            ),
            event(5, "MODIFY", value_updates={"a": 4}),
            event(6, "DEFER"),
            event(7, "RESUME"),
            event(8, "REMOVE"),
        ]

        graph = build_requirement_state_graph(annotation(events))["requirement_graphs"][0]

        self.assertEqual(len(graph["nodes"]), 8)
        self.assertEqual(len(graph["edges"]), 8)
        self.assertIsNone(graph["edges"][0]["from_state_id"])
        self.assertEqual(graph["edges"][1]["from_state_id"], "REQ_X_S001")
        ambiguous = graph["nodes"][2]
        self.assertEqual(ambiguous["ambiguity"]["source_event_id"], "REQ_X_E003")
        after_resolution = graph["nodes"][4]
        self.assertIsNone(after_resolution["ambiguity"])
        self.assertIsNone(after_resolution["execution"])
        self.assertEqual(after_resolution["attributes"], {"a": 4, "b": 2})
        self.assertEqual(
            after_resolution["supporting_event_ids"],
            ["REQ_X_E001", "REQ_X_E005"],
        )
        removed = graph["nodes"][-1]
        self.assertEqual(removed["lifecycle_status"], "REMOVED")
        self.assertIsNone(removed["execution"])
        self.assertEqual(
            removed["supporting_event_ids"],
            ["REQ_X_E001", "REQ_X_E005", "REQ_X_E008"],
        )

    def test_null_scope_fields_preserve_previous_dimensions(self) -> None:
        events = [
            event(
                1,
                "INTRODUCE",
                value_updates={"x": True},
                scope_updates={
                    "persistence": "PROJECT_PERSISTENT",
                    "components": ["FRONTEND"],
                    "contexts": ["OLD"],
                },
            ),
            event(
                2,
                "MODIFY",
                scope_updates={
                    "persistence": None,
                    "components": None,
                    "contexts": ["NEW"],
                },
            ),
        ]
        node = build_requirement_state_graph(annotation(events))["requirement_graphs"][0]["nodes"][-1]
        self.assertEqual(
            node["scope"],
            {
                "persistence": "PROJECT_PERSISTENT",
                "components": ["FRONTEND"],
                "contexts": ["NEW"],
            },
        )
        self.assertEqual(node["supporting_event_ids"], ["REQ_X_E001", "REQ_X_E002"])

    def test_requirement_without_introduce_is_removed(self) -> None:
        events = [
            event(
                1,
                "IMPLEMENTATION_CLAIM",
                execution={
                    "status": "CLAIMED_WORKING",
                    "observed_behavior": "reported complete",
                },
            )
        ]
        graphs = build_requirement_state_graph(annotation(events))["requirement_graphs"]
        self.assertEqual(graphs, [])

    def test_resume_after_ambiguity_resolving_modify_is_not_a_state(self) -> None:
        events = [
            event(1, "INTRODUCE", value_updates={"x": 1}),
            event(
                2,
                "AMBIGUOUS",
                ambiguity={"dimension": "VALUE", "description": "x is unclear"},
            ),
            event(3, "MODIFY", value_updates={"x": 2}),
            event(4, "RESUME"),
            event(
                5,
                "RUNTIME_VERIFICATION",
                execution={"status": "VERIFIED_WORKING", "observed_behavior": "x works"},
            ),
        ]

        graph = build_requirement_state_graph(annotation(events))["requirement_graphs"][0]

        self.assertEqual(
            [edge["event_id"] for edge in graph["edges"]],
            ["REQ_X_E001", "REQ_X_E002", "REQ_X_E003", "REQ_X_E005"],
        )
        self.assertEqual(
            [node["state_id"] for node in graph["nodes"]],
            ["REQ_X_S001", "REQ_X_S002", "REQ_X_S003", "REQ_X_S004"],
        )
        self.assertEqual(graph["edges"][-1]["from_state_id"], "REQ_X_S003")

    def test_event_after_remove_is_a_consistency_error(self) -> None:
        events = [
            event(1, "INTRODUCE", value_updates={"x": True}),
            event(2, "REMOVE"),
            event(3, "MODIFY", value_updates={"x": False}),
        ]
        with self.assertRaisesRegex(Stage2ReplayError, "after the Requirement was REMOVED"):
            build_requirement_state_graph(annotation(events))

    def test_value_removals_delete_stale_attribute_and_retain_absence_provenance(self) -> None:
        events = [
            event(1, "INTRODUCE", value_updates={"small_counter": True, "big_counter": True}),
            event(2, "MODIFY", value_removals=["big_counter"]),
        ]

        graph = build_requirement_state_graph(annotation(events))["requirement_graphs"][0]
        final_node = graph["nodes"][-1]

        self.assertEqual(final_node["attributes"], {"small_counter": True})
        self.assertEqual(final_node["supporting_event_ids"], ["REQ_X_E001", "REQ_X_E002"])
        self.assertEqual(graph["edges"][-1]["value_removals"], ["big_counter"])

    def test_value_removal_of_absent_attribute_fails(self) -> None:
        events = [
            event(1, "INTRODUCE", value_updates={"small_counter": True}),
            event(2, "MODIFY", value_removals=["big_counter"]),
        ]
        with self.assertRaisesRegex(Stage2ReplayError, "absent attribute"):
            build_requirement_state_graph(annotation(events))

    def test_same_attribute_cannot_be_updated_and_removed(self) -> None:
        events = [
            event(1, "INTRODUCE", value_updates={"counter": True}),
            event(2, "MODIFY", value_updates={"counter": False}, value_removals=["counter"]),
        ]
        with self.assertRaisesRegex(Stage2ReplayError, "updates and removes"):
            build_requirement_state_graph(annotation(events))


if __name__ == "__main__":
    unittest.main()

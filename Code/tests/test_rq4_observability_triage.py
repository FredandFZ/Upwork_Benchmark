from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from Code.rq4_observability_triage import (
    DEFAULT_PLANS_ROOT,
    ROOT,
    _required_surfaces,
    _triage_record,
    build_triage,
)


class RQ4ObservabilityTriageTest(unittest.TestCase):
    def test_web_catalog_is_not_a_project_behavior_contract(self):
        required = _required_surfaces(
            "web",
            {"FRONTEND", "BACKEND"},
            "Add a quote page and submit form.",
        )
        self.assertIn("PROJECT_BEHAVIOR_CONTRACT", required)
        self.assertIn("DOM_SEMANTICS", required)
        self.assertIn("BROWSER_INTERACTION", required)
        self.assertIn("ROUTES", required)
        self.assertIn("DOMAIN_BEHAVIOR", required)

    def test_subjective_clause_never_silently_becomes_binary_gold(self):
        record = _triage_record(
            renderer="web",
            components={"FRONTEND"},
            task_text="Make the page more modern and professional.",
            pre_features={"REQ": {"attributes": {"theme": "old"}}},
            post_features={"REQ": {"attributes": {"theme": "modern"}}},
            affected_ids=["REQ"],
        )
        self.assertTrue(record["subjective_clause_detected"])
        self.assertIn(
            "SUBJECTIVE_CLAUSES_REQUIRE_SEPARATION_OR_EXCLUSION",
            record["blockers"],
        )

    def test_current_release_produces_one_private_work_item_per_build_target(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rq4-validation"
            report = build_triage(
                plans_root=DEFAULT_PLANS_ROOT,
                output_root=output,
                code_environment_root=ROOT / "Code Environment",
                project_ids=None,
                replace=False,
            )
            self.assertEqual(report["project_count"], 7)
            self.assertEqual(report["target_count"], 99)
            self.assertEqual(
                sum(report["status_counts"].values()), report["target_count"]
            )
            items = list(output.glob("projects/*/targets/*/work_item.json"))
            self.assertEqual(len(items), 99)
            records = [json.loads(path.read_text(encoding="utf-8")) for path in items]
            self.assertTrue(
                all(
                    record["visibility"]
                    == "RESEARCHER_PRIVATE_NEVER_AGENT_VISIBLE_DURING_BENCHMARK"
                    for record in records
                )
            )
            observed = {
                record["observability_triage"]["status"] for record in records
            }
            self.assertIn("ELIGIBLE_FOR_VALIDATOR_AUTHORING", observed)
            self.assertIn("SUBJECTIVE_REVIEW_REQUIRED", observed)
            self.assertIn("NO_DETERMINISTIC_OBSERVABLE", observed)

            authored = items[0].parent / "author" / "criteria_proposal.json"
            authored.parent.mkdir()
            authored.write_text('{"proposal":"stale-but-preserved"}\n', encoding="utf-8")
            build_triage(
                plans_root=DEFAULT_PLANS_ROOT,
                output_root=output,
                code_environment_root=ROOT / "Code Environment",
                project_ids=None,
                replace=True,
            )
            self.assertEqual(
                authored.read_text(encoding="utf-8"),
                '{"proposal":"stale-but-preserved"}\n',
            )


if __name__ == "__main__":
    unittest.main()

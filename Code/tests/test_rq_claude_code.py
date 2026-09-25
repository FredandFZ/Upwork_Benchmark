from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from Code.preflight_rq123_claude_code import (
    ClaudePreflightError,
    _version_tuple,
    validate_claude_agent_config,
)
from Code.rq_run_identity import normalize_agent_config


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "Code" / "config" / "rq123_claude_code_experiment.example.json"


def _config() -> dict:
    value = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    value["agent"]["runtime_version"] = "2.1.259"
    value["agent"]["model"] = "claude-test"
    value["agent"]["model_version"] = "claude-test-snapshot"
    return value


class ClaudeCodeRQConfigTests(unittest.TestCase):
    def test_template_enforces_stateless_tool_free_structured_run(self):
        command = validate_claude_agent_config(_config())
        self.assertIn("--restricted", command)
        self.assertIn("--no-session-persistence", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(
            command[command.index("--json-schema") + 1],
            "{response_schema_json}",
        )

    def test_resume_flag_is_rejected(self):
        config = deepcopy(_config())
        config["agent"]["command"].append("--continue")
        with self.assertRaises(ClaudePreflightError):
            validate_claude_agent_config(config)

    def test_host_customization_flag_removal_is_rejected(self):
        config = deepcopy(_config())
        config["agent"]["command"].remove("--restricted")
        with self.assertRaises(ClaudePreflightError):
            validate_claude_agent_config(config)

    def test_claude_code_version_parser_accepts_cli_text(self):
        self.assertEqual(_version_tuple("2.1.259 (Claude Code)"), (2, 1, 259))

    def test_shared_agent_identity_accepts_claude_output_mode(self):
        config = _config()
        normalized = normalize_agent_config(
            config["agent"],
            run_prompt_sha256="a" * 64,
            instructions_sha256="b" * 64,
            response_schema_sha256="c" * 64,
        )
        self.assertEqual(normalized["output_mode"], "claude_structured_json")
        self.assertFalse(normalized["persistent_conversation"])


if __name__ == "__main__":
    unittest.main()

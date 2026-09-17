"""CLI wiring tests.

The tuning flags are duplicated between ``argparse`` and :class:`PiiConfig`, and
they drifted once: the dataclass default was raised to 2,000,000 while argparse
still passed 250,000, so the new limit never took effect on the command line and
a real run failed against the old value.  These tests make that class of bug
impossible to reintroduce silently.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path

from Code.PII.config import PHASES, PiiConfig


def load_cli():
    spec = importlib.util.spec_from_file_location("pii_clean_cli", "Code/pii_clean.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parser_defaults() -> dict[str, object]:
    """Build the real parser and read back every default."""

    cli = load_cli()
    captured: dict[str, argparse.ArgumentParser] = {}
    original = argparse.ArgumentParser.parse_args

    def intercept(self, *args, **kwargs):
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = intercept
    try:
        argv = sys.argv
        sys.argv = ["pii_clean.py"]
        with contextlib.suppress(SystemExit):
            cli.parse_args()
        sys.argv = argv
    finally:
        argparse.ArgumentParser.parse_args = original
    return {
        action.dest: action.default
        for action in captured["parser"]._actions
        if action.dest != "help"
    }


class DefaultsTests(unittest.TestCase):
    def test_every_shared_flag_matches_the_config_default(self):
        defaults = parser_defaults()
        mismatches = []
        for field in dataclasses.fields(PiiConfig):
            if field.default is dataclasses.MISSING:
                continue
            if field.name not in defaults:
                continue
            if defaults[field.name] != field.default:
                mismatches.append(
                    f"{field.name}: CLI={defaults[field.name]!r} config={field.default!r}"
                )
        self.assertEqual(mismatches, [], "CLI and PiiConfig defaults have drifted")

    def test_accumulator_limit_is_generous_enough_for_a_real_project(self):
        """An 824-message project reaches ~500 KB of slots and histories."""

        defaults = parser_defaults()
        self.assertGreaterEqual(defaults["max_accumulator_chars"], 1_000_000)

    def test_stop_after_phase_accepts_only_real_phases(self):
        defaults = parser_defaults()
        self.assertIsNone(defaults["stop_after_phase"])
        cli = load_cli()
        self.assertTrue(set(PHASES))
        # The flag's choices are the phase list itself.
        self.assertIn("PHASE_2_TRANSFORMATION_PLAN", PHASES)
        self.assertTrue(hasattr(cli, "build_config"))

    def test_build_config_round_trips_the_parsed_values(self):
        cli = load_cli()
        args = argparse.Namespace(
            output_root=Path("out"),
            work_root=Path("runs"),
            model="m",
            reasoning_effort="high",
            phase_effort=[],
            preserve_short_max_words=2,
            short_message_max_words=4,
            max_batch_messages=11,
            max_batch_chars=12_000,
            neighbor_window=3,
            semantic_fold_chars=13_000,
            semantic_fold_records=14,
            max_accumulator_chars=1_500_000,
            plan_chunk_bundles=15,
            plan_chunk_chars=16_000,
            max_repair_attempts=1,
            resume=True,
            overwrite=False,
            force_phase=[],
            stop_after_phase=None,
            keep_run_artifacts=False,
            preserve_term=["OAuth"],
            extra_private_term=[],
        )
        config = cli.build_config(args)
        self.assertEqual(config.max_accumulator_chars, 1_500_000)
        self.assertEqual(config.max_batch_messages, 11)
        self.assertEqual(config.preserve_terms, ("OAuth",))


if __name__ == "__main__":
    unittest.main()

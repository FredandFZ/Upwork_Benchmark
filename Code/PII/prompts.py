"""Load the phase prompts from ``prompt/PII/`` and hash them per phase.

Repo convention (``Code/stage1_batch_annotate.py:166-178``): the CLI reads prompt
files eagerly with ``utf-8-sig`` and injects the resulting *strings*; the library
layer never touches the filesystem for prompt text.

Shared fragments are inlined at load time and the hash is taken over the
**resolved** text.  The entity taxonomy appears in four prompts (0B classifies
with it, 2 generates against it, 3 applies it, 4 verifies it); defining it once
and inlining is what stops the "public third parties are preserved" reversal
from drifting between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ._compat import sha256_text
from .config import (
    BUCKET_LONG,
    LLM_PHASES,
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
)
from .errors import PiiError

PROMPT_DIR_NAME = "PII"
AGENT_REPAIR_FILE = "agent_repair_instructions.md"

FRAGMENT_ENTITY_POLICY = "_shared_entity_policy.md"
FRAGMENT_SEMANTIC_ONTOLOGY = "_shared_semantic_ontology.md"
FRAGMENT_OUTPUT_CONTRACT = "_shared_output_contract.md"

FRAGMENT_FILES: tuple[str, ...] = (
    FRAGMENT_ENTITY_POLICY,
    FRAGMENT_SEMANTIC_ONTOLOGY,
    FRAGMENT_OUTPUT_CONTRACT,
)

# Phase 3 is two prompts, so it is keyed by bucket rather than by phase alone.
PROMPT_KEY_REWRITE_SHORT = "PHASE_3A_SHORT"
PROMPT_KEY_REWRITE_LONG = "PHASE_3B_LONG"

PROMPT_FILES: Mapping[str, str] = {
    PHASE_0B: "phase0b_pii_discovery.md",
    PHASE_1A: "phase1a_message_semantics.md",
    PHASE_1B: "phase1b_project_consolidation.md",
    PHASE_2: "phase2_transformation_plan.md",
    PROMPT_KEY_REWRITE_SHORT: "phase3a_short_rewrite.md",
    PROMPT_KEY_REWRITE_LONG: "phase3b_long_rewrite.md",
    PHASE_4: "phase4_semantic_verification.md",
    PHASE_5: "phase5_targeted_repair.md",
}

SHARED_FRAGMENTS: Mapping[str, tuple[str, ...]] = {
    PHASE_0B: (FRAGMENT_ENTITY_POLICY, FRAGMENT_OUTPUT_CONTRACT),
    PHASE_1A: (FRAGMENT_SEMANTIC_ONTOLOGY, FRAGMENT_OUTPUT_CONTRACT),
    PHASE_1B: (FRAGMENT_SEMANTIC_ONTOLOGY, FRAGMENT_OUTPUT_CONTRACT),
    PHASE_2: (FRAGMENT_ENTITY_POLICY, FRAGMENT_OUTPUT_CONTRACT),
    PROMPT_KEY_REWRITE_SHORT: (FRAGMENT_ENTITY_POLICY, FRAGMENT_OUTPUT_CONTRACT),
    PROMPT_KEY_REWRITE_LONG: (FRAGMENT_ENTITY_POLICY, FRAGMENT_OUTPUT_CONTRACT),
    PHASE_4: FRAGMENT_FILES,
    PHASE_5: (FRAGMENT_ENTITY_POLICY, FRAGMENT_OUTPUT_CONTRACT),
}

VERSION_MARKER = "**Prompt version:**"


def parse_prompt_version(text: str) -> str | None:
    """Read the ``**Prompt version:**`` line, matching stage1's rule.

    Mirrors ``Code/stage1/pipeline.py:1905-1913``: last match wins, backticks
    stripped.
    """

    version: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(VERSION_MARKER):
            value = stripped[len(VERSION_MARKER) :].strip().strip("`").strip()
            version = value or None
    return version


@dataclass(frozen=True)
class PromptSet:
    """Resolved prompt text keyed by phase (or by phase-3 bucket key)."""

    texts: Mapping[str, str]
    paths: Mapping[str, Path]
    versions: Mapping[str, str | None]
    hashes: Mapping[str, str]
    agent_instructions: str
    agent_instructions_path: Path
    agent_instructions_sha256: str

    def text(self, key: str) -> str:
        try:
            return self.texts[key]
        except KeyError:
            raise PiiError(f"no prompt loaded for {key}") from None

    def sha256(self, key: str) -> str:
        """Hash of the resolved prompt; ``""`` for phases with no prompt."""

        return self.hashes.get(key, "")

    def version(self, key: str) -> str | None:
        return self.versions.get(key)

    def manifest_entries(self) -> dict[str, dict[str, str | None]]:
        return {
            key: {
                # ``paths`` is provenance only, so a set built without it (a test
                # fixture, an in-memory prompt) still produces a valid manifest.
                "path": str(self.paths[key]) if key in self.paths else None,
                "version": self.versions.get(key),
                "sha256": self.hashes.get(key, ""),
            }
            for key in sorted(self.texts)
        } | {
            "AGENT_REPAIR_INSTRUCTIONS": {
                "path": str(self.agent_instructions_path),
                "version": parse_prompt_version(self.agent_instructions),
                "sha256": self.agent_instructions_sha256,
            }
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PiiError(f"cannot read prompt file {path}: {exc}") from exc


def _resolve(body: str, fragments: Mapping[str, str], names: tuple[str, ...]) -> str:
    """Prepend the named fragments, each in a labelled block."""

    blocks = [
        f"<!-- fragment: {name} -->\n{fragments[name].strip()}\n" for name in names
    ]
    blocks.append(body.strip())
    return "\n\n".join(blocks) + "\n"


def load_prompt_set(prompt_dir: Path) -> PromptSet:
    """Read every v7 prompt, inline shared fragments, and hash the result."""

    if not prompt_dir.is_dir():
        raise PiiError(f"prompt directory not found: {prompt_dir}")

    fragments = {name: _read(prompt_dir / name) for name in FRAGMENT_FILES}

    texts: dict[str, str] = {}
    paths: dict[str, Path] = {}
    versions: dict[str, str | None] = {}
    hashes: dict[str, str] = {}
    for key, filename in PROMPT_FILES.items():
        path = prompt_dir / filename
        body = _read(path)
        resolved = _resolve(body, fragments, SHARED_FRAGMENTS.get(key, ()))
        texts[key] = resolved
        paths[key] = path
        versions[key] = parse_prompt_version(body)
        hashes[key] = sha256_text(resolved)

    agent_path = prompt_dir / AGENT_REPAIR_FILE
    agent_text = _read(agent_path)

    return PromptSet(
        texts=texts,
        paths=paths,
        versions=versions,
        hashes=hashes,
        agent_instructions=agent_text,
        agent_instructions_path=agent_path,
        agent_instructions_sha256=sha256_text(agent_text),
    )


def rewrite_prompt_key(bucket: str) -> str:
    """Map a rewrite bucket to its prompt key.

    Phases 3A and 3B are separate files so iterating on short-message wording
    does not invalidate the long rewrites, which are ~74% of the corpus.
    """

    return PROMPT_KEY_REWRITE_LONG if bucket == BUCKET_LONG else PROMPT_KEY_REWRITE_SHORT


def prompt_key_for_phase(phase: str, bucket: str | None = None) -> str:
    if phase == PHASE_3:
        if bucket is None:
            raise PiiError("phase 3 requires a bucket to select its prompt")
        return rewrite_prompt_key(bucket)
    if phase not in LLM_PHASES:
        return ""
    return phase

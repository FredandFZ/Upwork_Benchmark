"""Per-phase, per-shard checkpoints with precise cascade invalidation.

Every cached artifact is wrapped in a self-hashing envelope and keyed by an
``input_sha256`` that covers exactly what the shard consumed: its prompt, the
model and effort, the parameters that phase reads, the *output* hashes of its
upstream phases, and its own payload.

Chaining on upstream **output** hashes (not input hashes) means rerunning an
upstream phase that happens to produce byte-identical output costs nothing
downstream.  Combined with the per-phase parameter projection in
``PiiConfig.params_for``, editing one prompt invalidates exactly its own phase
and that phase's descendants -- not the whole project, which is what v6's single
global signature did (``Code/PII_Clean.py:2473-2520``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ._compat import read_json, safe_filename, write_json
from .config import (
    ENGINE_VERSION,
    PHASE_0A,
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
    PHASE_6,
    PHASES,
)
from .errors import PiiError
from .textutil import canonical_json, canonical_sha256

CHECKPOINT_SCHEMA_VERSION = "pii-v7-checkpoint-1"

PHASE_DIR: Mapping[str, str] = {
    PHASE_0A: "phase0a_secret_shield",
    PHASE_0B: "phase0b_pii_discovery",
    PHASE_1A: "phase1a_message_semantics",
    PHASE_1B: "phase1b_project_consolidation",
    PHASE_2: "phase2_transformation_plan",
    PHASE_3: "phase3_rewrite",
    PHASE_4: "phase4_verification",
    PHASE_5: "phase5_repair",
    PHASE_6: "phase6_render",
}

OUTPUT_META_NAME = "output.meta.json"
SOURCE_SIGNATURE_NAME = "source_signature.json"

_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "engine_version",
        "phase",
        "shard_id",
        "input_sha256",
        "prompt_sha256",
        "prompt_variant",
        "model",
        "reasoning_effort",
        "created_at",
        "attempt",
        "body",
        "content_sha256",
    }
)


@dataclass(frozen=True)
class PhaseHashes:
    input_sha256: str
    output_sha256: str

    def to_json(self) -> dict[str, str]:
        return {"input_sha256": self.input_sha256, "output_sha256": self.output_sha256}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_signature(source_sha256: str, chat_path: Path, message_count: int) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "message_count": message_count,
        "chat_path": str(chat_path),
    }


def check_source_signature(
    run_dir: Path, expected: Mapping[str, Any]
) -> tuple[bool, str | None]:
    """Compare the stored run identity against the current source.

    Only the raw-chat hash is fatal.  Message ordinals are derived from list
    position (``Code/PII_Clean.py:1284-1291``), so if the source changed, every
    per-message artifact in the run directory may now refer to a different
    message -- the one genuinely unrecoverable case.  Everything else (model,
    effort, prompts, batch limits) lives in the per-phase input hashes and
    invalidates only what it affects.
    """

    path = run_dir / SOURCE_SIGNATURE_NAME
    if not path.is_file():
        return True, None
    try:
        stored = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"unreadable {SOURCE_SIGNATURE_NAME}: {exc}"
    if not isinstance(stored, dict):
        return False, f"{SOURCE_SIGNATURE_NAME} is not a JSON object"
    if stored.get("engine_version") != expected.get("engine_version"):
        return True, None  # a different engine simply has no reusable artifacts
    if stored.get("source_sha256") != expected.get("source_sha256"):
        return False, (
            "the raw chat_messages.json changed since this run directory was created; "
            "message ordinals can no longer be trusted"
        )
    return True, None


class CheckpointStore:
    """Read/write validated phase artifacts under one project's run directory."""

    def __init__(
        self,
        run_dir: Path,
        *,
        resume: bool = True,
        forced: frozenset[str] = frozenset(),
        model: str = "",
        reasoning_effort: str = "",
    ) -> None:
        self.run_dir = run_dir
        self.resume = resume
        self.forced = frozenset(forced)
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._output_hashes: dict[str, str] = {}

    # -- paths ------------------------------------------------------------- #

    def phase_dir(self, phase: str) -> Path:
        try:
            return self.run_dir / PHASE_DIR[phase]
        except KeyError:
            raise PiiError(f"unknown phase: {phase}") from None

    def shard_path(self, phase: str, shard: str) -> Path:
        parts = [safe_filename(part) for part in str(shard).split("/") if part]
        if not parts:
            raise PiiError("shard id must not be empty")
        path = self.phase_dir(phase)
        for part in parts[:-1]:
            path = path / part
        return path / f"{parts[-1]}.json"

    def list_shards(self, phase: str) -> list[str]:
        root = self.phase_dir(phase)
        if not root.is_dir():
            return []
        found: list[str] = []
        for path in sorted(root.rglob("*.json")):
            if path.name == OUTPUT_META_NAME:
                continue
            relative = path.relative_to(root).with_suffix("")
            found.append(relative.as_posix())
        return found

    # -- hashing ----------------------------------------------------------- #

    def input_hash(
        self,
        phase: str,
        *,
        prompt_sha256: str = "",
        params: Mapping[str, Any] | None = None,
        upstream: Mapping[str, str] | None = None,
        scope: Any = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        return canonical_sha256(
            {
                "schema": CHECKPOINT_SCHEMA_VERSION,
                "engine": ENGINE_VERSION,
                "phase": phase,
                "prompt_sha256": prompt_sha256,
                "model": self.model if model is None else model,
                "reasoning_effort": (
                    self.reasoning_effort if reasoning_effort is None else reasoning_effort
                ),
                "params": dict(params or {}),
                "upstream": dict(sorted((upstream or {}).items())),
                "scope": scope,
            }
        )

    def upstream_hashes(self, phases: Sequence[str]) -> dict[str, str]:
        """Output hashes for the given upstream phases.

        A missing upstream hash is a programming error: the pipeline must run
        phases in topological order.
        """

        result: dict[str, str] = {}
        for phase in phases:
            value = self.output_hash(phase)
            if value is None:
                raise PiiError(f"upstream phase {phase} has no committed output hash")
            result[phase] = value
        return result

    # -- shard I/O --------------------------------------------------------- #

    def load(
        self,
        phase: str,
        shard: str,
        expected_input: str,
        validator: Callable[[Any], None] | None = None,
    ) -> dict[str, Any] | None:
        """Return a reusable cached body, or ``None`` to recompute.

        Five layers, in order: integrity, schema/engine, identity, freshness,
        then a full re-validation of the body with the *same* validator the live
        response had to pass.  That last layer is why editing a Python validator
        (with no prompt change) correctly invalidates cached work -- the stored
        body simply fails the new rules.

        Never raises.  A checkpoint is a cache; an unreadable cache means
        "recompute", not "abort".
        """

        if not self.resume or phase in self.forced:
            return None
        path = self.shard_path(phase, shard)
        if not path.is_file():
            return None
        try:
            envelope = read_json(path)
            if not isinstance(envelope, dict):
                raise ValueError("envelope must be a JSON object")
            unknown = sorted(set(envelope).difference(_ENVELOPE_KEYS))
            if unknown:
                raise ValueError(f"unknown envelope keys: {', '.join(unknown)}")
            recorded = envelope.get("content_sha256")
            body_for_hash = {
                key: value for key, value in envelope.items() if key != "content_sha256"
            }
            if recorded != canonical_sha256(body_for_hash):
                raise ValueError("content_sha256 mismatch")
            if envelope.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
                raise ValueError("checkpoint schema_version mismatch")
            if envelope.get("engine_version") != ENGINE_VERSION:
                raise ValueError("checkpoint engine_version mismatch")
            if envelope.get("phase") != phase:
                raise ValueError("checkpoint phase mismatch")
            if envelope.get("shard_id") != shard:
                raise ValueError("checkpoint shard_id mismatch")
            if envelope.get("input_sha256") != expected_input:
                raise ValueError("stale input_sha256")
            if "body" not in envelope:
                raise ValueError("envelope has no body")
            if validator is not None:
                validator(envelope["body"])
            return envelope
        except (OSError, ValueError, json.JSONDecodeError, PiiError) as exc:
            print(f"[checkpoint invalid] {path}: {exc}; rerunning", flush=True)
            return None

    def commit(
        self,
        phase: str,
        shard: str,
        *,
        input_sha256: str,
        body: Any,
        prompt_sha256: str = "",
        prompt_variant: str | None = None,
        attempt: int = 1,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> Path:
        envelope = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "phase": phase,
            "shard_id": shard,
            "input_sha256": input_sha256,
            "prompt_sha256": prompt_sha256,
            "prompt_variant": prompt_variant,
            "model": self.model if model is None else model,
            "reasoning_effort": (
                self.reasoning_effort if reasoning_effort is None else reasoning_effort
            ),
            "created_at": _now(),
            "attempt": attempt,
            "body": body,
        }
        envelope["content_sha256"] = canonical_sha256(envelope)
        path = self.shard_path(phase, shard)
        write_json(path, envelope)
        return path

    # -- phase output ------------------------------------------------------ #

    def commit_output(self, phase: str, *, body: Any, input_sha256: str) -> str:
        """Record the merged phase output hash and return it."""

        output_sha256 = canonical_sha256(body)
        write_json(
            self.phase_dir(phase) / OUTPUT_META_NAME,
            PhaseHashes(input_sha256=input_sha256, output_sha256=output_sha256).to_json(),
        )
        self._output_hashes[phase] = output_sha256
        return output_sha256

    def output_hash(self, phase: str) -> str | None:
        cached = self._output_hashes.get(phase)
        if cached is not None:
            return cached
        path = self.phase_dir(phase) / OUTPUT_META_NAME
        if not path.is_file():
            return None
        try:
            stored = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(stored, dict):
            return None
        value = stored.get("output_sha256")
        if not isinstance(value, str) or not value:
            return None
        self._output_hashes[phase] = value
        return value

    def output_meta(self, phase: str) -> PhaseHashes | None:
        path = self.phase_dir(phase) / OUTPUT_META_NAME
        if not path.is_file():
            return None
        try:
            stored = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(stored, dict):
            return None
        input_sha256 = stored.get("input_sha256")
        output_sha256 = stored.get("output_sha256")
        if not isinstance(input_sha256, str) or not isinstance(output_sha256, str):
            return None
        return PhaseHashes(input_sha256=input_sha256, output_sha256=output_sha256)

    # -- invalidation ------------------------------------------------------ #

    def discard(self, phase: str) -> list[Path]:
        """Delete every artifact for one phase.  Returns what was removed."""

        root = self.phase_dir(phase)
        removed: list[Path] = []
        if not root.is_dir():
            self._output_hashes.pop(phase, None)
            return removed
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
                removed.append(path)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        try:
            root.rmdir()
        except OSError:
            pass
        self._output_hashes.pop(phase, None)
        return removed

    def discard_phases(self, phases: frozenset[str] | set[str] | Sequence[str]) -> list[Path]:
        removed: list[Path] = []
        for phase in PHASES:
            if phase in phases:
                removed.extend(self.discard(phase))
        return removed


def message_scope(
    *,
    ordinal: int,
    message_id: Any,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The common part of a per-message shard scope."""

    scope: dict[str, Any] = {"ordinal": ordinal, "message_id": message_id}
    if extra:
        scope.update(extra)
    return scope


def payload_hash(value: Any) -> str:
    """Content hash of an arbitrary JSON-serializable payload."""

    return canonical_sha256(value)


def payload_size(value: Any) -> int:
    return len(canonical_json(value))

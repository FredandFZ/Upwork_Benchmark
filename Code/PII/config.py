"""Phase identity, the phase dependency DAG, and the run configuration.

The DAG is the reason resume works at the right granularity.  v6 folded every
prompt hash and every tunable into one global signature
(``Code/PII_Clean.py:2473-2520``), so editing the repair prompt invalidated the
context-classification results as well -- which is exactly why
``_read_matching_checkpoint`` grew six compatibility branches (``:2547-2591``).
Here each phase hashes only the prompt it uses, only the parameters it reads,
and only the outputs of its own upstream phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .errors import PiiError

ENGINE_VERSION = "7.0"

PHASE_0A = "PHASE_0A_SECRET_SHIELD"
PHASE_0B = "PHASE_0B_PII_DISCOVERY"
PHASE_1A = "PHASE_1A_MESSAGE_SEMANTICS"
PHASE_1B = "PHASE_1B_PROJECT_CONSOLIDATION"
PHASE_2 = "PHASE_2_TRANSFORMATION_PLAN"
PHASE_3 = "PHASE_3_REWRITE"
PHASE_4 = "PHASE_4_VERIFICATION"
PHASE_5 = "PHASE_5_REPAIR"
PHASE_6 = "PHASE_6_RENDER"

# Topological order.  Used for --stop-after-phase and for deterministic reporting.
PHASES: tuple[str, ...] = (
    PHASE_0A,
    PHASE_0B,
    PHASE_1A,
    PHASE_1B,
    PHASE_2,
    PHASE_3,
    PHASE_4,
    PHASE_5,
    PHASE_6,
)

# Phase -> the phases whose *output* it consumes.  A DAG, not a chain.
#
# Two edges deserve explanation:
#   * 1A does not depend on 0B.  Semantic slot assignment is about meaning, not
#     entity typing, so tightening the PII taxonomy and rerunning 0B preserves
#     every 1A/1B result.  The safety condition is that 1A never emits PII,
#     which its local validator enforces.
#   * 4 does not depend on 1A.  The verifier is specified as independent: it
#     re-derives meaning from the shielded original instead of grading against
#     phase 1A's own notes.
UPSTREAM: Mapping[str, tuple[str, ...]] = {
    PHASE_0A: (),
    PHASE_0B: (PHASE_0A,),
    PHASE_1A: (PHASE_0A,),
    PHASE_1B: (PHASE_1A,),
    PHASE_2: (PHASE_0A, PHASE_0B, PHASE_1B),
    PHASE_3: (PHASE_0A, PHASE_2),
    PHASE_4: (PHASE_0A, PHASE_2, PHASE_3),
    PHASE_5: (PHASE_0A, PHASE_2, PHASE_4),
    PHASE_6: (PHASE_0A, PHASE_2, PHASE_3, PHASE_5),
}

# Phase groups act as barriers.  Within a group every message is attempted so a
# single run enumerates every failure; at a group boundary the run stops
# advancing if anything is still unresolved, because phases 1B/2 build one
# project-wide artifact and global consistency cannot be derived from a partial
# inventory.
PHASE_GROUPS: tuple[tuple[str, ...], ...] = (
    (PHASE_0A,),
    (PHASE_0B, PHASE_1A),
    (PHASE_1B, PHASE_2),
    (PHASE_3, PHASE_4, PHASE_5),
    (PHASE_6,),
)

LOCAL_PHASES = frozenset({PHASE_0A, PHASE_6})
LLM_PHASES = frozenset(PHASES).difference(LOCAL_PHASES)

# ``run_mode`` strings reach the API call log and the failed-response filenames
# (``Code/stage1/api_client.py:203-216``, ``:229-231``).  ``Stage1ApiClient`` does
# not validate them against ``stage1.config.RUN_MODES``; only the stage1 prompt
# builder does, and this package does not use it.
RUN_MODE: Mapping[str, str] = {
    PHASE_0B: "PII7_PII_DISCOVERY",
    PHASE_1A: "PII7_MESSAGE_SEMANTICS",
    PHASE_1B: "PII7_PROJECT_CONSOLIDATION",
    PHASE_2: "PII7_TRANSFORMATION_PLAN",
    PHASE_3: "PII7_REWRITE",
    PHASE_4: "PII7_VERIFICATION",
    PHASE_5: "PII7_REPAIR",
}

# Rewrite buckets.  ``PRESERVE_SHORT`` and ``EMPTY`` never reach an LLM.
BUCKET_EMPTY = "EMPTY"
BUCKET_PRESERVE_SHORT = "PRESERVE_SHORT"
BUCKET_SHORT = "SHORT"
BUCKET_LONG = "LONG"
BUCKETS: tuple[str, ...] = (BUCKET_EMPTY, BUCKET_PRESERVE_SHORT, BUCKET_SHORT, BUCKET_LONG)
# Buckets whose final text is the shielded original, byte for byte.
PRESERVED_BUCKETS = frozenset({BUCKET_EMPTY, BUCKET_PRESERVE_SHORT})

REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

# Synthetic domains must sit under an RFC 2606 reserved name so a generated URL
# or address can never resolve to a real asset.
RESERVED_DOMAIN_SUFFIX = ".example"

DEFAULT_PHASE_EFFORT: Mapping[str, str] = {
    PHASE_1B: "max",
    PHASE_2: "max",
    PHASE_4: "max",
    PHASE_3: "high",
    PHASE_5: "high",
}


@dataclass(frozen=True)
class ProjectFiles:
    project_id: str
    project_dir: Path
    chat_path: Path


@dataclass(frozen=True)
class PiiConfig:
    """Everything a run needs besides credentials and prompt text."""

    output_root: Path
    work_root: Path
    model: str
    reasoning_effort: str

    phase_reasoning_effort: Mapping[str, str] = field(default_factory=dict)

    # Bucket boundaries.  1-2 words with no PII/secret/slot are preserved
    # verbatim; 3-4 words go to the short rewrite; 5+ to the long rewrite.
    preserve_short_max_words: int = 2
    short_message_max_words: int = 4

    max_batch_messages: int = 40
    max_batch_chars: int = 30_000
    neighbor_window: int = 2

    semantic_fold_chars: int = 60_000
    semantic_fold_records: int = 120
    max_accumulator_chars: int = 250_000

    plan_chunk_bundles: int = 25
    plan_chunk_chars: int = 40_000

    max_repair_attempts: int = 2

    resume: bool = True
    overwrite: bool = False
    force_phases: frozenset[str] = frozenset()
    stop_after_phase: str | None = None
    keep_run_artifacts: bool = False

    preserve_terms: tuple[str, ...] = ()
    extra_private_terms: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.model.strip() == "":
            raise PiiError("model must be a non-empty string")
        if self.reasoning_effort not in REASONING_EFFORTS:
            raise PiiError(f"reasoning_effort must be one of {sorted(REASONING_EFFORTS)}")
        for phase, effort in self.phase_reasoning_effort.items():
            if phase not in PHASES:
                raise PiiError(f"unknown phase in phase_reasoning_effort: {phase}")
            if effort not in REASONING_EFFORTS:
                raise PiiError(f"invalid reasoning effort for {phase}: {effort}")
        if self.preserve_short_max_words < 0:
            raise PiiError("preserve_short_max_words must be >= 0")
        if self.short_message_max_words < self.preserve_short_max_words:
            raise PiiError("short_message_max_words must be >= preserve_short_max_words")
        for name in ("max_batch_messages", "semantic_fold_records", "plan_chunk_bundles"):
            if getattr(self, name) < 1:
                raise PiiError(f"{name} must be >= 1")
        for name in (
            "max_batch_chars",
            "semantic_fold_chars",
            "max_accumulator_chars",
            "plan_chunk_chars",
        ):
            if getattr(self, name) < 1:
                raise PiiError(f"{name} must be >= 1")
        if self.neighbor_window < 0:
            raise PiiError("neighbor_window must be >= 0")
        if self.max_repair_attempts < 0:
            raise PiiError("max_repair_attempts must be >= 0")
        unknown = sorted(set(self.force_phases).difference(PHASES))
        if unknown:
            raise PiiError(f"unknown force_phases: {', '.join(unknown)}")
        if self.stop_after_phase is not None and self.stop_after_phase not in PHASES:
            raise PiiError(f"unknown stop_after_phase: {self.stop_after_phase}")
        if self.output_root.resolve() == self.work_root.resolve():
            raise PiiError("work_root must differ from output_root")

    def effort_for(self, phase: str) -> str:
        override = self.phase_reasoning_effort.get(phase)
        if override is not None:
            return override
        return DEFAULT_PHASE_EFFORT.get(phase, self.reasoning_effort)

    def params_for(self, phase: str) -> dict[str, Any]:
        """Only the parameters this phase actually reads.

        Keeping this narrow is what stops an unrelated tunable from invalidating
        a phase's cached work.
        """

        terms = {
            "preserve_terms": sorted(term.strip() for term in self.preserve_terms if term.strip()),
            "extra_private_terms": sorted(
                term.strip() for term in self.extra_private_terms if term.strip()
            ),
        }
        batching = {
            "max_batch_messages": self.max_batch_messages,
            "max_batch_chars": self.max_batch_chars,
        }
        if phase == PHASE_0A:
            return {}
        if phase == PHASE_0B:
            return {**batching, **terms}
        if phase == PHASE_1A:
            return {**batching, "neighbor_window": self.neighbor_window}
        if phase == PHASE_1B:
            return {
                "semantic_fold_chars": self.semantic_fold_chars,
                "semantic_fold_records": self.semantic_fold_records,
                "max_accumulator_chars": self.max_accumulator_chars,
            }
        if phase == PHASE_2:
            return {
                "plan_chunk_bundles": self.plan_chunk_bundles,
                "plan_chunk_chars": self.plan_chunk_chars,
                "reserved_domain_suffix": RESERVED_DOMAIN_SUFFIX,
            }
        if phase == PHASE_3:
            return {
                **batching,
                **terms,
                "preserve_short_max_words": self.preserve_short_max_words,
                "short_message_max_words": self.short_message_max_words,
            }
        if phase == PHASE_4:
            return {**batching}
        if phase == PHASE_5:
            return {
                **terms,
                "max_repair_attempts": self.max_repair_attempts,
                "preserve_short_max_words": self.preserve_short_max_words,
                "short_message_max_words": self.short_message_max_words,
            }
        if phase == PHASE_6:
            return {**terms, "reserved_domain_suffix": RESERVED_DOMAIN_SUFFIX}
        raise PiiError(f"unknown phase: {phase}")

    def expanded_force_phases(self) -> frozenset[str]:
        """Forced phases plus their descendants in :data:`UPSTREAM`.

        A descendant closure, not the flat index prefix used by
        ``Code/stage1/config.py:103-118``.  Forcing 0B must not force 1A, because
        1A is not downstream of it.
        """

        return descendants_closure(self.force_phases)


def descendants_closure(phases: frozenset[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    """Every phase in ``phases`` plus everything reachable downstream of it."""

    unknown = sorted(set(phases).difference(PHASES))
    if unknown:
        raise PiiError(f"unknown phases: {', '.join(unknown)}")
    closure = set(phases)
    changed = True
    while changed:
        changed = False
        for phase in PHASES:
            if phase in closure:
                continue
            if closure.intersection(UPSTREAM[phase]):
                closure.add(phase)
                changed = True
    return frozenset(closure)


def phases_up_to(stop_after_phase: str | None) -> tuple[str, ...]:
    """The phase prefix to run, honouring ``--stop-after-phase``."""

    if stop_after_phase is None:
        return PHASES
    if stop_after_phase not in PHASES:
        raise PiiError(f"unknown stop_after_phase: {stop_after_phase}")
    return PHASES[: PHASES.index(stop_after_phase) + 1]


def group_of(phase: str) -> tuple[str, ...]:
    for group in PHASE_GROUPS:
        if phase in group:
            return group
    raise PiiError(f"unknown phase: {phase}")

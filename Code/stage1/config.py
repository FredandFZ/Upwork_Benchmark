from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


ANNOTATION_MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"
RUN_MODES = (
    "EVIDENCE_SCAN",
    "REQUIREMENT_DISCOVERY",
    "EVENT_EXTRACTION",
    "CONSISTENCY_AUDIT",
    "CROSS_REQUIREMENT_IMPACT_AUDIT",
    "EVENT_VERIFICATION",
)
FORCE_STAGES = {
    "evidence_scan",
    "requirement_discovery",
    "event_extraction",
    "consistency_audit",
    "cross_requirement_impact_audit",
    "event_verification",
    "assembly",
}


@dataclass(frozen=True)
class ProjectSource:
    project_id: str
    project_dir: Path
    chat_path: Path
    output_path: Path
    run_dir: Path


@dataclass
class PipelineConfig:
    prompt_path: Path
    output_dir: Path
    run_root: Path
    verification_addendum_path: Path | None = None
    impact_audit_addendum_path: Path | None = None
    value_removal_addendum_path: Path | None = None
    upgrade_existing_annotation_path: Path | None = None
    model: str = ANNOTATION_MODEL
    reasoning_effort: str = REASONING_EFFORT
    annotation_mode: str = "multipass"
    resume: bool = True
    force_stages: set[str] = field(default_factory=set)
    force_requirements: set[str] = field(default_factory=set)
    evidence_chunk_size: int = 150
    evidence_chunk_overlap: int = 10
    context_window: int = 2
    event_context_mode: str = "filtered"
    max_requirement_context_messages: int = 160
    min_requirement_events: int = 0
    max_audit_rounds: int = 1
    max_impact_audit_rounds: int = 2
    max_impact_candidates_per_event: int = 12

    def validate(self) -> None:
        if self.annotation_mode not in {"multipass", "single-pass"}:
            raise ValueError("annotation_mode must be 'multipass' or 'single-pass'")
        if self.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("reasoning_effort must be low, medium, high, xhigh, or max")
        unknown = self.force_stages.difference(FORCE_STAGES)
        if unknown:
            raise ValueError(f"Unknown force stage(s): {', '.join(sorted(unknown))}")
        if self.evidence_chunk_size < 1:
            raise ValueError("evidence_chunk_size must be >= 1")
        if self.evidence_chunk_overlap < 0 or self.evidence_chunk_overlap >= self.evidence_chunk_size:
            raise ValueError("evidence_chunk_overlap must be >= 0 and smaller than evidence_chunk_size")
        if self.context_window < 0:
            raise ValueError("context_window must be >= 0")
        if self.event_context_mode not in {"filtered", "full_history"}:
            raise ValueError("event_context_mode must be 'filtered' or 'full_history'")
        if self.max_requirement_context_messages < 1:
            raise ValueError("max_requirement_context_messages must be >= 1")
        if self.min_requirement_events < 0:
            raise ValueError("min_requirement_events must be >= 0")
        if self.max_audit_rounds < 1:
            raise ValueError("max_audit_rounds must be >= 1")
        if self.max_impact_audit_rounds < 1:
            raise ValueError("max_impact_audit_rounds must be >= 1")
        if self.max_impact_candidates_per_event < 1:
            raise ValueError("max_impact_candidates_per_event must be >= 1")

    def expanded_force_stages(self) -> set[str]:
        """Invalidate downstream semantic checkpoints when an upstream stage is forced."""
        ordered = [
            "evidence_scan",
            "requirement_discovery",
            "event_extraction",
            "consistency_audit",
            "cross_requirement_impact_audit",
            "event_verification",
            "assembly",
        ]
        if not self.force_stages:
            return set()
        earliest = min(ordered.index(stage) for stage in self.force_stages)
        return set(ordered[earliest:])

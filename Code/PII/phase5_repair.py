"""Phase 5: targeted repair of a message the verifier rejected.

Bounded by design.  ``max_repair_attempts`` counts *distinct repair prompts*,
each of which is itself subject to the API client's retry budget for this run
mode -- which is why the pipeline sets ``retries_overrides`` for it.  Without
that cap, "at most 2 repair attempts" would mean up to 8 API calls.

Repairs pass the *same* gate as a phase-3 rewrite
(:func:`phase3_rewrite.rewrite_violations`) plus one extra requirement: the
machine-checkable findings the verifier raised must now actually pass.  A model
that produces different-but-still-wrong text does not get credit for changing
something.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .config import BUCKET_LONG
from .errors import PiiValidationError, marked
from .models import MessagePlanSlice, RewriteRecord, SafeMessage, VerdictRecord
from .phase3_rewrite import (
    make_record,
    repair_instruction_for,
    rewrite_violations,
)

# Findings whose resolution is locally decidable.  The rest are judgement calls
# that only the phase-4 re-verification can clear.
MACHINE_CHECKABLE_FINDINGS = frozenset(
    {
        "PII_INCONSISTENT",
        "SLOT_VALUE_WRONG",
        "REWRITE_TOO_WEAK",
        "LOCAL_GUARD_CONTRADICTION",
    }
)

TASK = (
    "Repair the previous synthetic rewrite using the verifier's specific findings. "
    "Correct only the identified errors and keep every valid synthetic replacement."
)


def repair_prompt_instruction(bucket: str, verdict: VerdictRecord, attempt: int) -> str:
    """Restate the bucket rules plus this message's concrete objections."""

    codes = ", ".join(dict.fromkeys(finding.code for finding in verdict.findings))
    details = "; ".join(
        f"{finding.code}: {finding.detail}" for finding in verdict.findings[:6]
    )
    return (
        f"Repair attempt {attempt}. The independent verifier rejected the previous text "
        f"with: {codes}. Specifics: {details}. Correct exactly these problems. Do not "
        "return to the original wording, do not introduce new project facts, and keep "
        "every synthetic replacement that was already correct. "
        + repair_instruction_for(bucket)
    )


def build_sections(
    item: SafeMessage,
    slice_: MessagePlanSlice,
    rewrite: RewriteRecord,
    verdict: VerdictRecord,
    *,
    attempt: int,
) -> dict[str, Any]:
    return {
        "POLICY": {
            "bucket": item.bucket,
            "attempt": attempt,
            "require_structural_change": item.bucket == BUCKET_LONG,
        },
        "SAFE_ORIGINAL": [
            {
                "ordinal": item.ordinal,
                "message_id": item.message_id,
                "speaker": item.speaker,
                "text": item.safe_text,
                "bucket": item.bucket,
            }
        ],
        "SYNTHETIC_REWRITE": {str(item.ordinal): rewrite.text},
        "VERDICT": verdict.to_json(),
        "PLAN_SLICE": {str(item.ordinal): slice_.to_json()},
    }


def unresolved_findings(
    verdict: VerdictRecord, safe: SafeMessage, candidate: str, slice_: MessagePlanSlice
) -> list[str]:
    """Machine-checkable findings that the candidate still does not clear."""

    targeted = {
        finding.code for finding in verdict.findings
    } & MACHINE_CHECKABLE_FINDINGS
    if not targeted:
        return []
    violations = rewrite_violations(safe, candidate, slice_)
    if violations:
        return sorted(targeted)
    return []


def validate_repair_response(
    payload: Mapping[str, Any],
    item: SafeMessage,
    slice_: MessagePlanSlice,
    verdict: VerdictRecord,
    previous: RewriteRecord,
    *,
    attempt: int,
) -> RewriteRecord:
    """Validate a single-message repair."""

    failures: list[str] = []
    codes: list[str] = []

    raw = payload.get("rewrites")
    if not isinstance(raw, list) or len(raw) != 1:
        raise PiiValidationError(
            marked("REPAIR_SCHEMA_INVALID: response must contain exactly one rewrite"),
            failures=("REPAIR_SCHEMA_INVALID",),
        )
    entry = raw[0]
    if not isinstance(entry, dict):
        raise PiiValidationError(
            marked("REPAIR_SCHEMA_INVALID: rewrites[0] must be an object"),
            failures=("REPAIR_SCHEMA_INVALID",),
        )
    ordinal = entry.get("ordinal")
    if ordinal != item.ordinal:
        raise PiiValidationError(
            marked(f"REPAIR_SCHEMA_INVALID: expected ordinal {item.ordinal}"),
            failures=("REPAIR_SCHEMA_INVALID",),
        )
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise PiiValidationError(
            marked("REPAIR_SCHEMA_INVALID: repair text must be a non-empty string"),
            failures=("REPAIR_SCHEMA_INVALID",),
        )

    violations = rewrite_violations(item, text, slice_)
    if violations:
        failures.extend(violations[:6])
        codes.extend(violation.split(":", 1)[0] for violation in violations)

    if text.strip() == previous.text.strip():
        failures.append("REPAIR_REGRESSED: repair is identical to the rejected text")
        codes.append("REPAIR_REGRESSED")

    still_open = unresolved_findings(verdict, item, text, slice_)
    if still_open:
        failures.append(
            "REPAIR_REGRESSED: the verifier's machine-checkable findings are still open "
            f"({', '.join(still_open)})"
        )
        codes.append("REPAIR_REGRESSED")

    if failures:
        raise PiiValidationError(
            marked(
                f"phase 5 repair for ordinal {item.ordinal} is invalid: "
                + "; ".join(failures[:6])
            ),
            failures=tuple(dict.fromkeys(codes)),
        )
    return make_record(item, text, slice_, source="LLM_REPAIR", attempt=attempt)


def repair_exhausted(attempts: int, max_attempts: int) -> bool:
    return attempts >= max_attempts


def attempt_summary(
    attempt: int,
    phase: str,
    outcome: str,
    *,
    error: BaseException | None = None,
    findings: Sequence[Mapping[str, Any]] = (),
    candidate_sha256: str | None = None,
) -> dict[str, Any]:
    """One row of the attempt history carried into an agent repair task.

    The agent needs to know what has already been tried so it does not repeat a
    fix that already failed.
    """

    return {
        "attempt": attempt,
        "phase": phase,
        "outcome": outcome,
        "error": f"{type(error).__name__}: {error}" if error is not None else None,
        "findings": [dict(item) for item in findings],
        "candidate_sha256": candidate_sha256,
        "candidate_available": candidate_sha256 is not None,
    }

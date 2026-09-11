"""Phase 4: independent semantic verification.

The verifier re-derives meaning from the shielded original rather than grading
against phase 1A's own notes, which is why it has no dependency on 1A in
``config.UPSTREAM``.  It judges project-level equivalence, not word overlap.

``cross_check_verdict`` encodes the most important fail-closed rule in the
phase: **a model's PASS cannot override a local guard.**  If the deterministic
rewrite invariants reject the text, the verdict is downgraded to FAIL with
``LOCAL_GUARD_CONTRADICTION`` regardless of what the verifier said.

Findings carry *pointers* (a decision id, slot id, entity id, relation id or a
span) and never quoted source text, so a verdict is safe to persist, safe to log
and safe to hand to a repairing agent.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .errors import PiiValidationError, marked
from .models import MessagePlanSlice, RewriteRecord, SafeMessage, VerdictFinding, VerdictRecord
from .phase3_rewrite import rewrite_violations

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"

CHECK_DIMENSIONS: tuple[str, ...] = (
    "intent",
    "requirement_meaning",
    "decisions",
    "negation",
    "ambiguity",
    "execution_state",
    "synthetic_pii_consistency",
    "slot_values",
    "missing_facts",
    "invented_facts",
    "rewrite_strength",
)

FINDING_CODES: tuple[str, ...] = (
    "INTENT_CHANGED",
    "REQUIREMENT_MEANING_CHANGED",
    "DECISION_LOST",
    "NEGATION_FLIPPED",
    "AMBIGUITY_RESOLVED_OR_ADDED",
    "EXECUTION_STATE_CHANGED",
    "PII_INCONSISTENT",
    "SLOT_VALUE_WRONG",
    "FACT_MISSING",
    "FACT_INVENTED",
    "REWRITE_TOO_WEAK",
    "LOCAL_GUARD_CONTRADICTION",
)

EVIDENCE_KINDS = frozenset(
    {"DECISION_ID", "SLOT_ID", "ENTITY_ID", "RELATION_ID", "SPAN", "NONE"}
)

SEVERITIES = frozenset({"HIGH", "MEDIUM", "LOW"})

TASK = (
    "Independently verify each synthetic rewrite against its shielded original and the "
    "supplied transformation plan. Judge project-level semantic equivalence rather than "
    "word-for-word similarity."
)

REPAIR_INSTRUCTION = (
    "The previous response failed local validation. Return exactly one verdict per "
    "message, with a status of PASS or FAIL, a value for every named check dimension, at "
    "least one finding when the status is FAIL and none when it is PASS, and only allowed "
    "finding codes. Reference evidence by decision_id, slot_id, entity_id, relation_id or "
    "span -- never by quoting the source text."
)


def build_sections(
    items: Sequence[SafeMessage],
    slices: Mapping[int, MessagePlanSlice],
    rewrites: Mapping[int, RewriteRecord],
) -> dict[str, Any]:
    return {
        "POLICY": {
            "check_dimensions": list(CHECK_DIMENSIONS),
            "finding_codes": list(FINDING_CODES),
            "evidence_kinds": sorted(EVIDENCE_KINDS),
        },
        "SAFE_ORIGINAL": [
            {
                "ordinal": item.ordinal,
                "message_id": item.message_id,
                "speaker": item.speaker,
                "text": item.safe_text,
                "bucket": item.bucket,
            }
            for item in items
        ],
        "SYNTHETIC_REWRITE": {
            str(item.ordinal): rewrites[item.ordinal].text
            for item in items
            if item.ordinal in rewrites
        },
        "PLAN_SLICE": {
            str(item.ordinal): slices[item.ordinal].to_json()
            for item in items
            if item.ordinal in slices
        },
    }


def shard_sizer(item: SafeMessage) -> int:
    # A verdict request carries both texts plus the slice, so its effective
    # character budget is roughly half a rewrite request's.
    return len(item.safe_text) * 2 + 500


def validate_verdict_response(
    payload: Mapping[str, Any], items: Sequence[SafeMessage]
) -> dict[int, VerdictRecord]:
    failures: list[str] = []
    codes: list[str] = []

    raw = payload.get("verdicts")
    if not isinstance(raw, list):
        raise PiiValidationError(
            marked("VERIFY_SCHEMA_INVALID: response must contain a verdicts list"),
            failures=("VERIFY_SCHEMA_INVALID",),
        )

    expected = {item.ordinal: item for item in items}
    result: dict[int, VerdictRecord] = {}

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            failures.append(f"verdicts[{index}] must be an object")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        ordinal = entry.get("ordinal")
        if not isinstance(ordinal, int) or ordinal not in expected:
            failures.append(f"verdicts[{index}] has an unknown ordinal")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        if ordinal in result:
            failures.append(f"ordinal {ordinal} appears twice")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        status = entry.get("status")
        if status not in (STATUS_PASS, STATUS_FAIL):
            failures.append(f"ordinal {ordinal} status {status!r} is invalid")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue

        raw_checks = entry.get("checks")
        if not isinstance(raw_checks, dict):
            failures.append(f"ordinal {ordinal} has no checks object")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        checks: dict[str, str] = {}
        for dimension in CHECK_DIMENSIONS:
            value = raw_checks.get(dimension)
            if value not in (STATUS_PASS, STATUS_FAIL):
                failures.append(
                    f"ordinal {ordinal} check {dimension} is {value!r}, not PASS/FAIL"
                )
                codes.append("VERIFY_SCHEMA_INVALID")
                break
            checks[dimension] = value
        if len(checks) != len(CHECK_DIMENSIONS):
            continue

        raw_findings = entry.get("findings")
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            failures.append(f"ordinal {ordinal} findings must be a list")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        findings: list[VerdictFinding] = []
        malformed = False
        for position, item in enumerate(raw_findings):
            if not isinstance(item, dict):
                failures.append(f"ordinal {ordinal} finding {position} must be an object")
                codes.append("VERIFY_SCHEMA_INVALID")
                malformed = True
                break
            code = item.get("code")
            if code not in FINDING_CODES:
                failures.append(f"ordinal {ordinal} finding code {code!r} is invalid")
                codes.append("VERIFY_SCHEMA_INVALID")
                malformed = True
                break
            evidence = item.get("evidence") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            kind = evidence.get("kind", "NONE")
            if kind not in EVIDENCE_KINDS:
                failures.append(f"ordinal {ordinal} evidence kind {kind!r} is invalid")
                codes.append("VERIFY_SCHEMA_INVALID")
                malformed = True
                break
            severity = item.get("severity", "HIGH")
            findings.append(
                VerdictFinding(
                    code=code,
                    detail=str(item.get("detail") or ""),
                    evidence={"kind": kind, **{
                        key: value
                        for key, value in evidence.items()
                        if key in ("ref", "ordinal", "start", "end")
                    }},
                    severity=severity if severity in SEVERITIES else "HIGH",
                )
            )
        if malformed:
            continue

        any_failed = any(value == STATUS_FAIL for value in checks.values())
        if status == STATUS_FAIL and not findings:
            failures.append(f"ordinal {ordinal} is FAIL but lists no findings")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        if status == STATUS_PASS and findings:
            failures.append(f"ordinal {ordinal} is PASS but lists findings")
            codes.append("VERIFY_SCHEMA_INVALID")
            continue
        if (status == STATUS_FAIL) != any_failed:
            failures.append(
                f"ordinal {ordinal} status does not agree with its check dimensions"
            )
            codes.append("VERIFY_SCHEMA_INVALID")
            continue

        safe = expected[ordinal]
        result[ordinal] = VerdictRecord(
            ordinal=ordinal,
            message_id=safe.message_id,
            status=status,
            checks=checks,
            findings=tuple(findings),
            verified_against={},
        )

    missing = sorted(set(expected).difference(result))
    if missing and not failures:
        failures.append(f"omitted ordinals {missing[:20]}")
        codes.append("VERIFY_SCHEMA_INVALID")

    if failures:
        raise PiiValidationError(
            marked("phase 4 validation failed: " + "; ".join(failures[:8])),
            failures=tuple(dict.fromkeys(codes)),
        )
    return result


def cross_check_verdict(
    verdict: VerdictRecord,
    safe: SafeMessage,
    rewrite: RewriteRecord,
    slice_: MessagePlanSlice,
) -> VerdictRecord:
    """Bind the verdict to the exact text, and let local guards veto a PASS.

    Deterministic checks always win over model judgement.  Recording
    ``verified_against`` is what lets phase 6B assert that the text which
    shipped is the text that was verified, closing the "changed after
    verification" hole.
    """

    violations = rewrite_violations(safe, rewrite.text, slice_)
    findings = list(verdict.findings)
    checks = dict(verdict.checks)
    status = verdict.status

    if violations:
        status = STATUS_FAIL
        checks["synthetic_pii_consistency"] = STATUS_FAIL
        findings.append(
            VerdictFinding(
                code="LOCAL_GUARD_CONTRADICTION",
                detail=(
                    "local rewrite invariants reject this text: "
                    + "; ".join(violations[:4])
                ),
                evidence={"kind": "NONE"},
                severity="HIGH",
            )
        )

    return VerdictRecord(
        ordinal=verdict.ordinal,
        message_id=verdict.message_id,
        status=status,
        checks=checks,
        findings=tuple(findings),
        verified_against={
            "plan_slice_sha256": _slice_hash(slice_),
            "rewrite_text_sha256": rewrite.text_sha256,
            "safe_text_sha256": safe.safe_text_sha256,
        },
    )


def _slice_hash(slice_: MessagePlanSlice) -> str:
    from .textutil import canonical_sha256

    return canonical_sha256(slice_.to_json())


def validate_cached_verdict(
    body: Any, safe: SafeMessage, rewrite: RewriteRecord, slice_: MessagePlanSlice
) -> None:
    """Re-validate a restored verdict, including that it names this exact text."""

    record = VerdictRecord.from_json(body)
    if record.ordinal != safe.ordinal:
        raise PiiValidationError(marked("cached verdict belongs to another message"))
    if record.verified_against.get("rewrite_text_sha256") != rewrite.text_sha256:
        raise PiiValidationError(marked("cached verdict was issued for different text"))
    if record.verified_against.get("plan_slice_sha256") != _slice_hash(slice_):
        raise PiiValidationError(marked("cached verdict was issued against a stale plan"))
    if record.status not in (STATUS_PASS, STATUS_FAIL):
        raise PiiValidationError(marked(f"cached verdict status {record.status} is invalid"))

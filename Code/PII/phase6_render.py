"""Phase 6: final rendering and the hard-fail safety audit.

Written before the LLM phases on purpose.  The audit defines what "correct"
means for the whole pipeline, and enumerating its inputs is what tells each
earlier phase which data it must persist.  Building the phases first and the
audit last reliably produces an audit that needs data nobody saved.

:func:`audit_final_texts` is a pure function of ``(AuditInputs, cleaned_chat)``.
It runs every check before raising, so one pass names every violation instead of
stopping at the first, and it reports only ordinals, ids, counts and 12-hex
fingerprints -- never a sensitive value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .config import PRESERVED_BUCKETS
from .discovery import chat_field_violations
from .errors import AuditFailure
from .models import (
    ALLOWED_PROVENANCE,
    STATUS_DONE,
    MessageState,
    PiiEntityRegistry,
    SafeMessage,
    SecretRegistry,
    SemanticRegistry,
    TransformationPlan,
)
from .secret_shield import credential_map, render_text, unexpected_credential_spans
from .textutil import (
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    INTERNAL_TOKEN_RE,
    LEGACY_PLACEHOLDER_RE,
    LIST_MARKER_RE,
    PHONE_RE,
    RESERVED_DOMAIN_RE,
    URL_RE,
    contains_value,
    fingerprint,
    occurrence_count,
    preserved_term_counts,
)

# --------------------------------------------------------------------------- #
# Check names.  Every one is locally decidable from AuditInputs.
# --------------------------------------------------------------------------- #

CHECK_INVALID_OUTPUT_SCHEMA = "INVALID_OUTPUT_SCHEMA"
CHECK_COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
CHECK_PROVENANCE_INVALID = "PROVENANCE_INVALID"
CHECK_REQUIRED_CHANGE_NOT_APPLIED = "REQUIRED_CHANGE_NOT_APPLIED"
CHECK_PRESERVED_ROW_DRIFTED = "PRESERVED_ROW_DRIFTED"

CHECK_ORIGINAL_PERSON_PRESENT = "ORIGINAL_PERSON_PRESENT"
CHECK_ORIGINAL_PROJECT_IDENTIFIER_PRESENT = "ORIGINAL_PROJECT_IDENTIFIER_PRESENT"
CHECK_ORIGINAL_ENTITY_PRESENT = "ORIGINAL_ENTITY_PRESENT"
CHECK_ORIGINAL_EMAIL_PRESENT = "ORIGINAL_EMAIL_PRESENT"
CHECK_ORIGINAL_URL_PRESENT = "ORIGINAL_URL_PRESENT"
CHECK_ORIGINAL_PHONE_PRESENT = "ORIGINAL_PHONE_PRESENT"
CHECK_ORIGINAL_SENDER_ID_PRESENT = "ORIGINAL_SENDER_ID_PRESENT"
CHECK_MUST_REPLACE_TERM_PRESENT = "MUST_REPLACE_TERM_PRESENT"

CHECK_ORIGINAL_SECRET_PRESENT = "ORIGINAL_SECRET_PRESENT"
CHECK_INTERNAL_PLACEHOLDER_PRESENT = "INTERNAL_PLACEHOLDER_PRESENT"
CHECK_SECRET_TOKEN_MULTIPLICITY = "SECRET_TOKEN_MULTIPLICITY"
CHECK_FAKE_CREDENTIAL_MALFORMED = "FAKE_CREDENTIAL_MALFORMED"
CHECK_UNEXPECTED_CREDENTIAL_LIKE_VALUE = "UNEXPECTED_CREDENTIAL_LIKE_VALUE"

CHECK_PLAN_REPLACEMENT_COLLISION = "PLAN_REPLACEMENT_COLLISION"
CHECK_INCONSISTENT_SYNTHETIC_ENTITY = "INCONSISTENT_SYNTHETIC_ENTITY"
CHECK_INCONSISTENT_SLOT_VALUE = "INCONSISTENT_SLOT_VALUE"
CHECK_PRESERVED_VALUE_LOST = "PRESERVED_VALUE_LOST"
CHECK_LIST_MARKER_DAMAGED = "LIST_MARKER_DAMAGED"

CHECK_UNVERIFIED_TEXT = "UNVERIFIED_TEXT"
CHECK_UNRESOLVED_MESSAGE_PRESENT = "UNRESOLVED_MESSAGE_PRESENT"

AUDIT_CHECKS: tuple[str, ...] = (
    CHECK_INVALID_OUTPUT_SCHEMA,
    CHECK_COVERAGE_INCOMPLETE,
    CHECK_PROVENANCE_INVALID,
    CHECK_REQUIRED_CHANGE_NOT_APPLIED,
    CHECK_PRESERVED_ROW_DRIFTED,
    CHECK_ORIGINAL_PERSON_PRESENT,
    CHECK_ORIGINAL_PROJECT_IDENTIFIER_PRESENT,
    CHECK_ORIGINAL_ENTITY_PRESENT,
    CHECK_ORIGINAL_EMAIL_PRESENT,
    CHECK_ORIGINAL_URL_PRESENT,
    CHECK_ORIGINAL_PHONE_PRESENT,
    CHECK_ORIGINAL_SENDER_ID_PRESENT,
    CHECK_MUST_REPLACE_TERM_PRESENT,
    CHECK_ORIGINAL_SECRET_PRESENT,
    CHECK_INTERNAL_PLACEHOLDER_PRESENT,
    CHECK_SECRET_TOKEN_MULTIPLICITY,
    CHECK_FAKE_CREDENTIAL_MALFORMED,
    CHECK_UNEXPECTED_CREDENTIAL_LIKE_VALUE,
    CHECK_PLAN_REPLACEMENT_COLLISION,
    CHECK_INCONSISTENT_SYNTHETIC_ENTITY,
    CHECK_INCONSISTENT_SLOT_VALUE,
    CHECK_PRESERVED_VALUE_LOST,
    CHECK_LIST_MARKER_DAMAGED,
    CHECK_UNVERIFIED_TEXT,
    CHECK_UNRESOLVED_MESSAGE_PRESENT,
)

PERSON_TYPES = frozenset({"PERSON", "PERSONAL_USERNAME", "SOCIAL_ACCOUNT"})
PROJECT_TYPES = frozenset(
    {
        "PROJECT_NAME",
        "PRIVATE_ORGANIZATION",
        "PRIVATE_DOMAIN",
        "PRIVATE_REPOSITORY",
    }
)


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str
    ordinal: int | None = None
    message_id: Any = None
    fingerprints: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "detail": self.detail,
            "ordinal": self.ordinal,
            "message_id": self.message_id,
            "fingerprints": list(self.fingerprints),
        }


@dataclass
class AuditReport:
    project_id: str
    violations: tuple[Violation, ...]
    checks_run: tuple[str, ...]
    message_count: int

    @property
    def ok(self) -> bool:
        return not self.violations

    def counts_by_check(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for violation in self.violations:
            counts[violation.check] = counts.get(violation.check, 0) + 1
        return dict(sorted(counts.items()))

    def to_json(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "ok": self.ok,
            "message_count": self.message_count,
            "checks_run": list(self.checks_run),
            "violations": [item.to_json() for item in self.violations],
            "counts_by_check": self.counts_by_check(),
        }

    def raise_if_failed(self) -> None:
        if self.ok:
            return
        summary = ", ".join(
            f"{check}x{count}" for check, count in self.counts_by_check().items()
        )
        raise AuditFailure(
            f"phase 6B audit found {len(self.violations)} violation(s): {summary}",
            violations=tuple(item.to_json() for item in self.violations),
        )


@dataclass
class AuditInputs:
    """Everything phase 6B needs, and nothing it does not.

    Materializing this as one structure is what makes the audit unit-testable
    from fixtures with no network and no run directory.
    """

    project_id: str
    original_chat: Sequence[Any]
    messages: Sequence[Mapping[str, Any]]
    safe_messages: Sequence[SafeMessage]
    states: Mapping[int, MessageState]
    secret_registry: SecretRegistry
    entity_registry: PiiEntityRegistry
    semantic_registry: SemanticRegistry
    plan: TransformationPlan
    preserve_terms: tuple[str, ...] = ()
    extra_private_terms: tuple[str, ...] = ()
    sender_ids: tuple[str, ...] = ()
    verified_text_hashes: frozenset[tuple[int, str]] = frozenset()
    unresolved_message_ids: tuple[Any, ...] = ()
    must_replace_terms_by_ordinal: Mapping[int, tuple[str, ...]] = field(
        default_factory=dict
    )


# --------------------------------------------------------------------------- #
# Phase 6A -- rendering
# --------------------------------------------------------------------------- #


def render_final_texts(
    states: Mapping[int, MessageState], secret_registry: SecretRegistry
) -> dict[int, str]:
    """Substitute internal secret tokens with deterministic fake credentials.

    Reads only accepted texts.  A quarantined message raises rather than
    defaulting, which is why phase 6 iterates over states instead of a text map.
    """

    rendered = credential_map(secret_registry)
    return {
        ordinal: render_text(state.require_final_text(), rendered)
        for ordinal, state in sorted(states.items())
    }


def secret_values(
    registry: SecretRegistry, messages: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Re-derive ``secret_id -> raw value`` from the source spans, in memory only.

    The registry deliberately persists no raw value, but the audit must prove
    the original is gone, so it reconstructs the values from the recorded
    offsets at audit time and never writes them anywhere.
    """

    by_ordinal = {int(message["ordinal"]): str(message.get("text") or "") for message in messages}
    values: dict[str, str] = {}
    for entry in registry.secrets:
        for occurrence in entry.occurrences:
            text = by_ordinal.get(occurrence.ordinal, "")
            candidate = text[occurrence.start : occurrence.end]
            if candidate:
                values[entry.secret_id] = candidate
                break
    return values


# --------------------------------------------------------------------------- #
# Domain allow-listing
# --------------------------------------------------------------------------- #


def _domain_of(value: str) -> str:
    host = value.split("://", 1)[-1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@", 1)[-1]
    return host.split(":", 1)[0].strip("<>").casefold()


def allowed_hosts(plan: TransformationPlan) -> frozenset[str]:
    """Hosts a finished message may legitimately mention.

    v6 banned every address and URL from the output
    (``PII_Clean.py:1111-1113``).  v7 must *allow* the synthetic ones, so the
    check inverts: only reserved domains and explicitly preserved public hosts
    may appear.  Missing this inversion is the single most likely porting
    regression.
    """

    hosts: set[str] = set()
    for item in plan.entity_replacements:
        if item.policy == "SYNTHESIZE":
            for value in item.replacements():
                host = _domain_of(value)
                if host:
                    hosts.add(host)
        else:
            for value in (item.original, item.replacement):
                host = _domain_of(value)
                if host:
                    hosts.add(host)
    return frozenset(hosts)


def _host_is_allowed(host: str, allowed: frozenset[str]) -> bool:
    if not host:
        return False
    if RESERVED_DOMAIN_RE.search(host):
        return True
    if host in allowed:
        return True
    return any(host.endswith(f".{item}") or item.endswith(f".{host}") for item in allowed)


# --------------------------------------------------------------------------- #
# Phase 6B -- the audit
# --------------------------------------------------------------------------- #


def audit_final_texts(
    inputs: AuditInputs,
    final_texts: Mapping[int, str],
    cleaned_chat: Sequence[Any] | None = None,
) -> AuditReport:
    """Run every hard-fail check and collect all violations."""

    violations: list[Violation] = []
    add = violations.append

    source_by_ordinal = {
        int(message["ordinal"]): str(message.get("text") or "")
        for message in inputs.messages
    }
    safe_by_ordinal = {message.ordinal: message for message in inputs.safe_messages}
    ordinals = sorted(source_by_ordinal)
    raw_secrets = secret_values(inputs.secret_registry, inputs.messages)
    hosts = allowed_hosts(inputs.plan)
    entity_by_id = inputs.entity_registry.by_id()
    plan_entities = inputs.plan.entity_by_id()

    # -- E2: unresolved messages block everything -------------------------- #
    if inputs.unresolved_message_ids:
        add(
            Violation(
                check=CHECK_UNRESOLVED_MESSAGE_PRESENT,
                detail=(
                    f"{len(inputs.unresolved_message_ids)} message(s) are unresolved; "
                    "no output may be committed"
                ),
                fingerprints=tuple(
                    str(item) for item in inputs.unresolved_message_ids[:40]
                ),
            )
        )

    # -- A1: output schema -------------------------------------------------- #
    if cleaned_chat is not None:
        for detail in chat_field_violations(inputs.original_chat, cleaned_chat):
            add(Violation(check=CHECK_INVALID_OUTPUT_SCHEMA, detail=detail))

    # -- A2: coverage ------------------------------------------------------- #
    missing = [ordinal for ordinal in ordinals if ordinal not in final_texts]
    extra = [ordinal for ordinal in final_texts if ordinal not in source_by_ordinal]
    if missing or extra:
        add(
            Violation(
                check=CHECK_COVERAGE_INCOMPLETE,
                detail=f"missing={missing[:20]} unexpected={extra[:20]}",
            )
        )

    # -- D1: plan-level collisions ------------------------------------------ #
    by_replacement: dict[str, list[str]] = {}
    for item in inputs.plan.synthesized():
        for original, replacement in item.pairs():
            if original.casefold() == replacement.casefold():
                add(
                    Violation(
                        check=CHECK_PLAN_REPLACEMENT_COLLISION,
                        detail=f"{item.entity_id}: replacement equals its original",
                        fingerprints=(fingerprint(item.entity_type, original),),
                    )
                )
            by_replacement.setdefault(replacement.casefold(), []).append(item.entity_id)
    for replacement, owners in sorted(by_replacement.items()):
        distinct = sorted(set(owners))
        if len(distinct) > 1:
            add(
                Violation(
                    check=CHECK_PLAN_REPLACEMENT_COLLISION,
                    detail=f"one replacement is shared by {distinct}",
                    fingerprints=(fingerprint("REPLACEMENT", replacement),),
                )
            )

    # -- per-message checks -------------------------------------------------- #
    for ordinal in ordinals:
        message_id = ordinal
        state = inputs.states.get(ordinal)
        original = source_by_ordinal[ordinal]
        safe = safe_by_ordinal.get(ordinal)
        final = final_texts.get(ordinal)
        if final is None:
            continue

        # A3: provenance
        if state is None:
            add(
                Violation(
                    check=CHECK_PROVENANCE_INVALID,
                    detail="no message state recorded",
                    ordinal=ordinal,
                    message_id=message_id,
                )
            )
        else:
            if state.status != STATUS_DONE:
                add(
                    Violation(
                        check=CHECK_PROVENANCE_INVALID,
                        detail=f"status is {state.status}, not {STATUS_DONE}",
                        ordinal=ordinal,
                        message_id=state.message_id,
                    )
                )
            if state.provenance not in ALLOWED_PROVENANCE:
                add(
                    Violation(
                        check=CHECK_PROVENANCE_INVALID,
                        detail=f"provenance {state.provenance!r} is not allowed",
                        ordinal=ordinal,
                        message_id=state.message_id,
                    )
                )
            # A4 / A5: the original may only survive where change is not required
            if state.requires_change:
                if final == original or (safe is not None and final == safe.safe_text):
                    add(
                        Violation(
                            check=CHECK_REQUIRED_CHANGE_NOT_APPLIED,
                            detail="rendered text is identical to the original",
                            ordinal=ordinal,
                            message_id=state.message_id,
                        )
                    )
            elif state.bucket in PRESERVED_BUCKETS and final != original:
                add(
                    Violation(
                        check=CHECK_PRESERVED_ROW_DRIFTED,
                        detail="a deliberately preserved row was modified",
                        ordinal=ordinal,
                        message_id=state.message_id,
                    )
                )
            # E1: every changed row must carry a verification result
            if (
                state.requires_change
                and inputs.verified_text_hashes
                and (ordinal, state.text_sha256 or "") not in inputs.verified_text_hashes
            ):
                add(
                    Violation(
                        check=CHECK_UNVERIFIED_TEXT,
                        detail="no verification result for this exact text",
                        ordinal=ordinal,
                        message_id=state.message_id,
                    )
                )

        # C1: no pipeline-internal representation may survive
        internal = INTERNAL_TOKEN_RE.findall(final)
        legacy = LEGACY_PLACEHOLDER_RE.findall(final)
        if internal or legacy:
            add(
                Violation(
                    check=CHECK_INTERNAL_PLACEHOLDER_PRESENT,
                    detail=f"internal tokens={internal[:5]} legacy placeholders={legacy[:5]}",
                    ordinal=ordinal,
                    message_id=message_id,
                )
            )

        # C2: the shield's token multiset must be reflected exactly
        if safe is not None:
            expected = len(safe.secret_tokens)
            actual = len(FAKE_CREDENTIAL_RE.findall(final))
            if expected != actual:
                add(
                    Violation(
                        check=CHECK_SECRET_TOKEN_MULTIPLICITY,
                        detail=(
                            f"expected {expected} rendered credential(s), found {actual}"
                        ),
                        ordinal=ordinal,
                        message_id=message_id,
                    )
                )

        # C4: no original secret value
        for secret_id, value in raw_secrets.items():
            if value and value in final:
                add(
                    Violation(
                        check=CHECK_ORIGINAL_SECRET_PRESENT,
                        detail=f"secret {secret_id} survived rendering",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("SECRET", value),),
                    )
                )

        # C5: nothing credential-shaped beyond the fake renderings
        unexpected = unexpected_credential_spans(final)
        if unexpected:
            add(
                Violation(
                    check=CHECK_UNEXPECTED_CREDENTIAL_LIKE_VALUE,
                    detail=f"{len(unexpected)} credential-shaped value(s) present",
                    ordinal=ordinal,
                    message_id=message_id,
                    fingerprints=tuple(
                        fingerprint("CANDIDATE", span.value) for span in unexpected[:5]
                    ),
                )
            )

        # C3: rendered credentials must match the canonical shape
        for candidate in FAKE_CREDENTIAL_RE.finditer(final):
            if not FAKE_CREDENTIAL_RE.fullmatch(candidate.group(0)):
                add(
                    Violation(
                        check=CHECK_FAKE_CREDENTIAL_MALFORMED,
                        detail="rendered credential has a non-canonical shape",
                        ordinal=ordinal,
                        message_id=message_id,
                    )
                )

        # B1/B2: no original surface form of a synthesized entity
        for entity in inputs.entity_registry.for_ordinal(ordinal):
            if entity.policy != "SYNTHESIZE":
                continue
            replacement = plan_entities.get(entity.entity_id)
            surfaces = set(entity.surface_forms())
            if replacement is not None:
                surfaces.update(replacement.originals())
            for surface in sorted(surfaces):
                if not surface or not contains_value(final, surface):
                    continue
                if entity.entity_type in PERSON_TYPES:
                    check = CHECK_ORIGINAL_PERSON_PRESENT
                elif entity.entity_type in PROJECT_TYPES:
                    check = CHECK_ORIGINAL_PROJECT_IDENTIFIER_PRESENT
                else:
                    check = CHECK_ORIGINAL_ENTITY_PRESENT
                add(
                    Violation(
                        check=check,
                        detail=f"{entity.entity_id} ({entity.entity_type}) survived",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint(entity.entity_type, surface),),
                    )
                )

        # B3: addresses must sit under a reserved or preserved domain
        for match in EMAIL_RE.finditer(final):
            host = _domain_of(match.group(0))
            if not _host_is_allowed(host, hosts):
                add(
                    Violation(
                        check=CHECK_ORIGINAL_EMAIL_PRESENT,
                        detail=f"address host {host!r} is neither reserved nor preserved",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("EMAIL", match.group(0)),),
                    )
                )

        # B4: same rule for links
        for match in URL_RE.finditer(final):
            host = _domain_of(match.group(0))
            if not _host_is_allowed(host, hosts):
                add(
                    Violation(
                        check=CHECK_ORIGINAL_URL_PRESENT,
                        detail=f"link host {host!r} is neither reserved nor preserved",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("URL", match.group(0)),),
                    )
                )

        # B5: no original phone digits
        original_phones = {
            _digits(match.group(0)) for match in PHONE_RE.finditer(original)
        }
        for match in PHONE_RE.finditer(final):
            if _digits(match.group(0)) in original_phones:
                add(
                    Violation(
                        check=CHECK_ORIGINAL_PHONE_PRESENT,
                        detail="a phone number from the source survived",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("PHONE", match.group(0)),),
                    )
                )

        # B6: a sender id must never be copied into the body
        for sender_id in inputs.sender_ids:
            if len(sender_id) >= 6 and contains_value(final, sender_id):
                add(
                    Violation(
                        check=CHECK_ORIGINAL_SENDER_ID_PRESENT,
                        detail="a raw sender_id appears in the message body",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("SENDER_ID", sender_id),),
                    )
                )

        # B7: terms the plan required to be replaced
        for term in inputs.must_replace_terms_by_ordinal.get(ordinal, ()):
            if contains_value(final, term):
                add(
                    Violation(
                        check=CHECK_MUST_REPLACE_TERM_PRESENT,
                        detail="a term marked for replacement survived",
                        ordinal=ordinal,
                        message_id=message_id,
                        fingerprints=(fingerprint("TERM", term),),
                    )
                )

        # D4: preserved requirement terms must keep their exact count
        if safe is not None:
            terms = (*inputs.preserve_terms,)
            before = preserved_term_counts(safe.safe_text, terms)
            after = preserved_term_counts(final, terms)
            for term, count in before.items():
                if count and after.get(term, 0) != count:
                    add(
                        Violation(
                            check=CHECK_PRESERVED_VALUE_LOST,
                            detail=f"preserved term count changed: {count} -> {after.get(term, 0)}",
                            ordinal=ordinal,
                            message_id=message_id,
                            fingerprints=(fingerprint("PRESERVE_TERM", term),),
                        )
                    )

            # D5: ordered-list numbering is layout, not data
            if list(LIST_MARKER_RE.findall(safe.safe_text)) != list(
                LIST_MARKER_RE.findall(final)
            ):
                add(
                    Violation(
                        check=CHECK_LIST_MARKER_DAMAGED,
                        detail="ordered-list numbering changed",
                        ordinal=ordinal,
                        message_id=message_id,
                    )
                )

        # D3: planned slot values must be applied, originals gone
        for slot in inputs.semantic_registry.for_ordinal(ordinal):
            replacement = inputs.plan.slot_by_id().get(slot.slot_id)
            if replacement is None:
                continue
            for original_literal, new_literal in replacement.literal_map.items():
                if original_literal and contains_value(
                    final, original_literal, ignore_case=False
                ):
                    add(
                        Violation(
                            check=CHECK_INCONSISTENT_SLOT_VALUE,
                            detail=f"{slot.slot_id}: original literal survived",
                            ordinal=ordinal,
                            message_id=message_id,
                            fingerprints=(fingerprint("SLOT", original_literal),),
                        )
                    )
                elif new_literal and not contains_value(
                    final, new_literal, ignore_case=False
                ):
                    # Only complain when the original was present in this message.
                    if contains_value(
                        safe.safe_text if safe else original,
                        original_literal,
                        ignore_case=False,
                    ):
                        add(
                            Violation(
                                check=CHECK_INCONSISTENT_SLOT_VALUE,
                                detail=f"{slot.slot_id}: planned value not applied",
                                ordinal=ordinal,
                                message_id=message_id,
                            )
                        )

    # -- D2: one entity, one spelling, project-wide ------------------------- #
    for item in inputs.plan.synthesized():
        entity = entity_by_id.get(item.entity_id)
        if entity is None:
            continue
        spellings: dict[str, int] = {}
        for ordinal in entity.ordinals():
            final = final_texts.get(ordinal)
            if final is None:
                continue
            for _original, replacement in item.pairs():
                count = occurrence_count(final, replacement, ignore_case=False)
                if count:
                    spellings[replacement] = spellings.get(replacement, 0) + count
        expected = {value for _original, value in item.pairs()}
        unexpected_spellings = sorted(set(spellings).difference(expected))
        if unexpected_spellings:
            add(
                Violation(
                    check=CHECK_INCONSISTENT_SYNTHETIC_ENTITY,
                    detail=f"{item.entity_id} appears under unplanned spellings",
                    fingerprints=tuple(
                        fingerprint("SPELLING", value) for value in unexpected_spellings[:5]
                    ),
                )
            )

    return AuditReport(
        project_id=inputs.project_id,
        violations=tuple(violations),
        checks_run=AUDIT_CHECKS,
        message_count=len(ordinals),
    )


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def audit_inputs_to_json(inputs: AuditInputs) -> dict[str, Any]:
    """Serialize the audit's inputs for offline replay and unit testing.

    Contains real PII (shielded originals, plan mappings), so it lives only in
    the run directory and is deleted on success.
    """

    return {
        "project_id": inputs.project_id,
        "safe_messages": [item.to_json() for item in inputs.safe_messages],
        "states": {
            str(ordinal): state.to_json() for ordinal, state in sorted(inputs.states.items())
        },
        "secret_registry": inputs.secret_registry.to_json(),
        "entity_registry": inputs.entity_registry.to_json(),
        "semantic_registry": inputs.semantic_registry.to_json(),
        "plan": inputs.plan.to_json(),
        "preserve_terms": list(inputs.preserve_terms),
        "extra_private_terms": list(inputs.extra_private_terms),
        "sender_id_fingerprints": [
            fingerprint("SENDER_ID", value) for value in inputs.sender_ids
        ],
        "verified_text_hashes": [
            [ordinal, digest] for ordinal, digest in sorted(inputs.verified_text_hashes)
        ],
        "unresolved_message_ids": list(inputs.unresolved_message_ids),
        "must_replace_terms_by_ordinal": {
            str(ordinal): list(terms)
            for ordinal, terms in sorted(inputs.must_replace_terms_by_ordinal.items())
        },
    }

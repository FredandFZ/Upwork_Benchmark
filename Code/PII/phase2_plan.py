"""Phase 2: one coherent project-wide synthetic transformation plan.

The design problem is that "one plan, consistent across the whole project" has
to coexist with projects of 1000+ messages.  The resolution is to chunk so that
every constraint is *intra-chunk*, and to enforce every *global* invariant
locally:

* **Entity chunks are whole identity bundles.**  A person with their address and
  username, or an organization with its domain, repository and links, is never
  split -- so intra-bundle coherence is structural rather than checked.
  Cross-chunk uniqueness is handled by passing ``RESERVED_VALUES`` (everything
  already allocated, in deterministic order) and rejecting collisions by name.
* **Slot chunks are arithmetic closures.**  ``{winner_count, prize, pool}`` is
  decided in a single call, so ``5 x 10000 = 50000`` can become
  ``7 x 12500 = 87500`` coherently.  The validator recomputes every relation
  with :class:`~decimal.Decimal` instead of trusting the model.
* **Assembly is local and deterministic**, so ``plan.json``'s output hash is
  stable whenever the chunks are -- which is what keeps every phase-3 slice hash
  stable, and therefore what makes per-message rewrite checkpoints reusable.

:func:`plan_slice` computes the **transitive closure** of the plan decisions a
message must honour.  That closure is the soundness condition for per-message
checkpointing: without it, a rewrite referencing a replacement that changed
elsewhere would restore as valid and the contradiction would only surface in the
final project-wide audit, with no trail back to its cause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .config import RESERVED_DOMAIN_SUFFIX
from .errors import PlanConsistencyError, marked
from .models import (
    EntityAlias,
    EntityReplacement,
    MessagePlanSlice,
    MessageSemantics,
    PiiEntity,
    PiiEntityRegistry,
    SafeMessage,
    SecretPlanEntry,
    SecretRegistry,
    SemanticRegistry,
    SlotHistoryEntry,
    SlotLiteralReplacement,
    SlotReplacement,
    TransformationPlan,
)
from .phase0b_entities import (
    POLICY_PRESERVE,
    POLICY_PROTECTED,
    POLICY_SYNTHESIZE,
    PUBLIC_ALLOWLIST,
)
from .phase1b_consolidate import evaluate_relation, numeric_value, relation_clusters
from .secret_shield import nominate_secret_spans
from .textutil import (
    EMAIL_RE,
    FAKE_CREDENTIAL_RE,
    INTERNAL_TOKEN_RE,
    LEGACY_PLACEHOLDER_RE,
    PHONE_RE,
    RESERVED_DOMAIN_RE,
    URL_RE,
    WORD_RE,
    canonical_json,
    contains_value,
    find_terms_outside_pii,
    is_bare_numeric_literal,
    private_resource_identifiers,
    similarity_ratio,
)

MODE_ENTITY_CHUNK = "ENTITY_CHUNK"
MODE_SLOT_CLUSTER = "SLOT_CLUSTER"

# Types whose replacement must itself look like that kind of value.
HOSTED_TYPES = frozenset({"EMAIL", "PRIVATE_URL", "MEETING_URL", "PRIVATE_REPOSITORY"})

# A replacement this similar to its original is a light mask, not a replacement.
MAX_SIMILARITY = 0.7

TASK_ENTITIES = (
    "Generate realistic but fictional replacements for the supplied private entities, "
    "keeping every entity inside one identity bundle mutually consistent."
)
TASK_SLOTS = (
    "Generate substantially different replacement values for the supplied requirement "
    "slots, preserving data types, history chains and arithmetic relations."
)

REPAIR_INSTRUCTION_ENTITIES = (
    "The previous response failed local validation. Return one replacement for every "
    "supplied entity_id. A PRESERVE entity must keep its original value unchanged. A "
    "SYNTHESIZE replacement must differ substantially from its original, must not be a "
    "lightly masked variant of it, must not equal any reserved value or any other "
    f"entity's original, and every synthetic private domain must end in "
    f"'{RESERVED_DOMAIN_SUFFIX}'. "
    "Within one bundle, the address local part must derive from the synthetic person name "
    "and every address, private-host link and private-host repository must use that bundle's "
    "synthetic domain. Public-host links are excluded from that bundle-domain rule. For a "
    "link on a PRIVATE host, change the host and keep the path; the reserved suffix does not "
    "excuse keeping the original name in the host. For a link on a PUBLIC host (a block "
    "explorer, a docs site, a vendor page), keep the host and change the private part of the "
    "path instead. Either way the replacement must not carry any other entity's real value: "
    "if the path holds a wallet address, a project name or an invite code that has its own "
    "replacement, apply that replacement inside the link. For an address, change both the "
    "local part and the host. For an entity that reads as a description rather than a value, "
    "restate the whole phrase rather than swapping one word. Never produce a value that "
    "looks like a usable credential. Never keep an opaque private app, document, webhook, "
    "subscription or invitation id inside a URL. A meeting URL must use a reserved .example "
    "host, not a plausible room code on the real service. Every alias must remain a spelling "
    "of the same planned synthetic identity, never a second identity."
)
REPAIR_INSTRUCTION_SLOTS = (
    "The previous response failed local validation. Return one replacement for every "
    "supplied slot_id. Keep the same number of history entries with the same ordinals and "
    "ops, keep the data type and unit, make every new value different from the original, "
    "and choose values that make every supplied relation hold exactly. Return one "
    "literal_replacements record for every supplied literal_occurrence, echoing its "
    "ordinal, message_id, start, end and source_literal as original. A value written in "
    "words is still that type and may be rendered as a number ('free' -> '$25', "
    "'No badges' -> '3 badges'); the reverse is not allowed -- if the original carries a "
    "number, the replacement must carry one too. Never re-value a name listed in "
    "PRESERVED_TERMS: a slot whose value is a public name keeps that value exactly, and a "
    "value that contains one must keep it."
    " A slot authorizes only a value change: preserve the operator, condition, lifecycle, "
    "trigger, environment, actor, object and causal rule around it."
)


@dataclass(frozen=True)
class PlanChunk:
    """Whole identity bundles, never split."""

    index: int
    entity_ids: tuple[str, ...]
    bundle_ids: tuple[str, ...]

    @property
    def chunk_id(self) -> str:
        return f"chunk_{self.index:04d}"


@dataclass(frozen=True)
class SlotCluster:
    """Slots tied by arithmetic, decided in one call."""

    index: int
    slot_ids: tuple[str, ...]

    @property
    def cluster_id(self) -> str:
        return f"cluster_{self.index:04d}"


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def planned_entities(registry: PiiEntityRegistry) -> tuple[PiiEntity, ...]:
    """Entities the plan must decide: everything except shielded secrets."""

    return tuple(
        entity for entity in registry.entities if entity.policy != POLICY_PROTECTED
    )


def bundle_groups(registry: PiiEntityRegistry) -> list[tuple[str | None, tuple[str, ...]]]:
    """Bundles first (in id order), then unbundled entities as singletons."""

    grouped: list[tuple[str | None, tuple[str, ...]]] = []
    planned = {entity.entity_id for entity in planned_entities(registry)}
    for bundle in registry.bundles:
        members = tuple(item for item in bundle.entity_ids if item in planned)
        if members:
            grouped.append((bundle.bundle_id, members))
    bundled = {item for _bundle_id, members in grouped for item in members}
    for entity in planned_entities(registry):
        if entity.entity_id not in bundled:
            grouped.append((None, (entity.entity_id,)))
    return grouped


def bundle_chunks(
    registry: PiiEntityRegistry, *, max_bundles: int, max_chars: int
) -> list[PlanChunk]:
    groups = bundle_groups(registry)
    by_id = registry.by_id()
    chunks: list[PlanChunk] = []
    current_entities: list[str] = []
    current_bundles: list[str] = []
    current_chars = 0
    for bundle_id, members in groups:
        size = sum(
            len(by_id[item].canonical_value) + 80 for item in members if item in by_id
        )
        if current_entities and (
            len(current_bundles) >= max_bundles or current_chars + size > max_chars
        ):
            chunks.append(
                PlanChunk(len(chunks) + 1, tuple(current_entities), tuple(current_bundles))
            )
            current_entities, current_bundles, current_chars = [], [], 0
        current_entities.extend(members)
        if bundle_id is not None:
            current_bundles.append(bundle_id)
        current_chars += size
    if current_entities:
        chunks.append(
            PlanChunk(len(chunks) + 1, tuple(current_entities), tuple(current_bundles))
        )
    return chunks


def slot_clusters(registry: SemanticRegistry, *, max_chars: int) -> list[SlotCluster]:
    """Arithmetic closures as their own clusters; isolated slots batched freely."""

    clusters = relation_clusters(registry)
    tied = [group for group in clusters if len(group) > 1]
    loose = [group[0] for group in clusters if len(group) == 1]

    result: list[SlotCluster] = []
    for group in tied:
        result.append(SlotCluster(len(result) + 1, group))

    by_id = registry.by_id()
    current: list[str] = []
    current_chars = 0
    for slot_id in loose:
        slot = by_id.get(slot_id)
        size = len(canonical_json(slot.to_json())) if slot is not None else 120
        if current and current_chars + size > max_chars:
            result.append(SlotCluster(len(result) + 1, tuple(current)))
            current, current_chars = [], 0
        current.append(slot_id)
        current_chars += size
    if current:
        result.append(SlotCluster(len(result) + 1, tuple(current)))
    return result


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def build_entity_sections(
    chunk: PlanChunk,
    registry: PiiEntityRegistry,
    reserved: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    by_id = registry.by_id()
    bundle_by_id = registry.bundle_by_id()
    return {
        "MODE": MODE_ENTITY_CHUNK,
        "POLICY": {
            "reserved_domain_suffix": RESERVED_DOMAIN_SUFFIX,
            "max_similarity_to_original": MAX_SIMILARITY,
        },
        "PII_ENTITIES": [
            {
                "entity_id": entity_id,
                "entity_type": by_id[entity_id].entity_type,
                "policy": by_id[entity_id].policy,
                "original": by_id[entity_id].canonical_value,
                "surface_forms": list(by_id[entity_id].surface_forms()),
                "bundle_id": by_id[entity_id].bundle_id,
            }
            for entity_id in chunk.entity_ids
            if entity_id in by_id
        ],
        "IDENTITY_BUNDLES": [
            bundle_by_id[bundle_id].to_json()
            for bundle_id in chunk.bundle_ids
            if bundle_id in bundle_by_id
        ],
        "RESERVED_VALUES": {key: list(values) for key, values in sorted(reserved.items())},
    }


def preserved_surface_forms(registry: PiiEntityRegistry) -> frozenset[str]:
    """Every surface form the plan must never alter, casefolded.

    Phase 0B classifies public third parties and public technologies as
    PRESERVE, and ``TYPE_POLICY`` pins that in code so a prompt regression
    cannot resurrect v6's brand replacement.  That guard only ever reached the
    *entity* channel: ``validate_slot_cluster`` is handed the semantic registry
    and has no idea which literals are public, so the same names came back
    through the slot channel and a currency ticker, an L2 and a payment
    provider were all re-valued -- turning requirements into different
    requirements, and making the value simultaneously PRESERVE (as an entity)
    and replaced (as a slot literal), which no rewrite can satisfy.
    """

    forms: set[str] = set()
    for entity in registry.entities:
        if entity.policy != POLICY_PRESERVE:
            continue
        for form in (entity.canonical_value, *entity.surface_forms()):
            if not form or not form.strip():
                continue
            value = form.strip().casefold()
            forms.add(value)
            # A preserved entity is often recorded as a whole link
            # (``https://<explorer>/?``) while what has to be recognised later is
            # the bare host inside some *other* link.  Contribute both, plus the
            # host stripped of its TLD, so a brand recorded as a word still
            # matches the same brand appearing as a domain.
            host = _domain_of(value)
            if host and "." in host:
                forms.add(host)
                labels = _identifying_labels(host)
                if labels:
                    forms.add(".".join(labels))
    return frozenset(forms)


def _host_is_public(host: str, preserved: frozenset[str]) -> bool:
    """Whether this host belongs to a preserved public third party."""

    if not host:
        return False
    if host in preserved:
        return True
    # Walk the labels right to left.  ``docs.google.com`` and ``meet.google.com``
    # are Google; matching only the full label list recognised a brand solely
    # when its sub-domain happened to be in the generic list, so one vendor was
    # caught and an identical one was missed.
    labels = _identifying_labels(host)
    for index in range(len(labels)):
        if ".".join(labels[index:]) in preserved:
            return True
    return False


def _normalize_public_url_replacement(
    original: str, replacement: str, preserved: frozenset[str]
) -> str:
    """Keep a public service endpoint while accepting the model's new path.

    The model used to receive two contradictory rules: public links had to keep
    their real public host, while every synthetic link was also required to use
    a reserved ``.example`` host. Repeated retries therefore could not make the
    answer reliable. The host choice is deterministic, so do not leave it to
    the model: copy scheme and authority from the source public URL and retain
    only the candidate's rewritten path, query and fragment.

    Malformed candidates are left untouched so the normal shape validator can
    reject them with the useful original diagnostic.
    """

    if not _host_is_public(_domain_of(original), preserved):
        return replacement
    source = urlsplit(original)
    candidate = urlsplit(replacement)
    if not source.scheme or not source.netloc or not candidate.scheme or not candidate.netloc:
        return replacement
    return urlunsplit(
        (source.scheme, source.netloc, candidate.path, candidate.query, candidate.fragment)
    )


def _pads_original(original: str, replacement: str) -> bool:
    """The replacement is the original with words bolted on, not a new value.

    When a slot records a public technology name the model is caught between
    "keep the public term" and "every value must change", and satisfies both by
    padding: ``PDF`` -> ``PDF document``, ``Pinata`` -> ``Pinata pinning
    service``.  That is not a new value, and downstream it is unsatisfiable --
    the rewrite naturally says ``PDF``, so the gate sees the original surviving
    while the padded "new value" never appears.
    """

    left, right = original.strip(), replacement.strip()
    if not left or not right or left.casefold() == right.casefold():
        return False
    return contains_value(right, left) or contains_value(left, right)


def _is_only_preserved(value: str, preserved: frozenset[str]) -> bool:
    """The value is a public term and nothing else."""

    return bool(value.strip()) and value.strip().casefold() in preserved


def _preserved_terms_in(value: str, preserved: frozenset[str]) -> set[str]:
    """Preserved surface forms occurring in ``value`` as whole tokens."""

    if not preserved:
        return set()
    tokens = [token.casefold() for token in WORD_RE.findall(value)]
    token_set = set(tokens)
    found = {token for token in tokens if token in preserved}
    # Public acronyms are commonly pluralised in prose (``NFT`` -> ``NFTs``).
    # Treat only an exact trailing-s plural as the same term; substring matching
    # would revive the old false positive where ``base`` matched ``database``.
    found.update(
        term
        for term in preserved
        if " " not in term
        and re.fullmatch(r"[a-z0-9]+", term)
        and f"{term}s" in token_set
    )
    joined = value.strip().casefold()
    if joined in preserved:
        found.add(joined)
    # Multi-word terms ("Google Meet", "Base Mainnet") are not single tokens.
    for term in preserved:
        if " " in term and re.search(
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", value, re.IGNORECASE
        ):
            found.add(term)
    return found


def _restore_preserved_unit(
    source: str,
    candidate: str,
    unit: str | None,
    preserved: frozenset[str],
) -> str:
    """Restore a declared public unit when the candidate has an explicit number.

    A model can correctly re-value a count but paraphrase its unit (for example,
    ``no existing NFT`` -> ``4 digital collectibles``). Retrying a large slot
    cluster cannot make that deterministic. If every dropped public term comes
    from the slot's declared unit, the numeric decision is unambiguous: retain
    it and render it with that unit. Public names outside the unit and values
    without an explicit number still go through the hard validation failure.
    """

    required = _preserved_terms_in(source, preserved)
    if not required or required <= _preserved_terms_in(candidate, preserved):
        return candidate.strip()
    if not unit:
        return candidate.strip()
    unit_tokens = set(re.findall(r"[a-z0-9]+", unit.casefold()))
    if not all(
        term in unit_tokens or (" " not in term and f"{term}s" in unit_tokens)
        for term in required
    ):
        return candidate.strip()
    number = numeric_value(candidate)
    if number is None:
        return candidate.strip()
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{rendered} {unit}".strip()


def build_slot_sections(
    cluster: SlotCluster,
    registry: SemanticRegistry,
    preserved: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    by_id = registry.by_id()
    relations = [
        relation.to_json()
        for relation in registry.relations
        if set(relation.slot_ids) & set(cluster.slot_ids)
    ]
    slots = [by_id[slot_id].to_json() for slot_id in cluster.slot_ids if slot_id in by_id]
    # Name the public terms these slots actually contain, so the model is told
    # rather than corrected.  Enforcement still happens locally.
    present = sorted(
        {
            term
            for slot in slots
            for value in list(slot.get("source_literals") or [])
            + [item.get("new_value") or "" for item in slot.get("history") or []]
            for term in _preserved_terms_in(value, preserved)
        }
    )
    return {
        "MODE": MODE_SLOT_CLUSTER,
        "SLOT_CLUSTER": slots,
        "CONSTRAINTS": relations,
        "PRESERVED_TERMS": present,
    }


# --------------------------------------------------------------------------- #
# Entity chunk validation
# --------------------------------------------------------------------------- #


def _domain_of(value: str) -> str:
    host = value.split("://", 1)[-1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@", 1)[-1]
    return host.split(":", 1)[0].strip("<>").casefold()


def _local_part(value: str) -> str:
    return value.split("@", 1)[0].casefold()


def _retains_original(original: str, replacement: str) -> bool:
    """Whether the replacement keeps the original value intact.

    ``Joseph`` -> ``Joseph Smith`` scores only 0.67 on token similarity yet
    preserves the identifying name completely, so containment is checked
    separately in both directions.
    """

    left = original.strip()
    right = replacement.strip()
    if len(left) < 3 or len(right) < 3:
        return False
    return contains_value(right, left) or contains_value(left, right)


URL_TYPES = frozenset({"PRIVATE_URL", "MEETING_URL", "PRIVATE_REPOSITORY"})

# Sub-domains this generic carry no identity, so a plan is not required to
# invent new ones; ``api.<private>.xyz`` -> ``api.<synthetic>.example`` is the
# desired shape, not a leak.
_GENERIC_LABELS = frozenset(
    {"www", "api", "app", "dev", "staging", "stage", "test", "mail", "smtp", "cdn"}
)


def _identifying_labels(host: str) -> list[str]:
    """Host labels that actually identify, TLD and generic prefixes removed."""

    labels = [label for label in host.split(".") if label]
    if labels and labels[-1] in RESERVED_DOMAIN_SUFFIX.strip(".").split("."):
        labels = labels[:-1]
    elif len(labels) > 1:
        labels = labels[:-1]
    return [label for label in labels if label not in _GENERIC_LABELS]


def _host_masking_failure(original: str, replacement: str) -> str | None:
    """Compare hosts on their identifying labels, character by character.

    Token similarity is blind here: ``WORD_RE`` treats a whole host as one
    token, so ``<private>.xyz`` -> ``<private>.example`` scores 0.0 and sails
    through while the organisation name survives into the published dataset.
    The reserved-suffix rule does not catch it either -- the suffix is correct.
    Characters are the right granularity for a host.
    """

    if not replacement:
        return "replacement has no host"
    if original == replacement:
        return "replacement keeps the original host"
    left = _identifying_labels(original)
    right = _identifying_labels(replacement)
    survivors = sorted(set(left) & set(right))
    if survivors:
        return f"replacement host keeps the identifying label(s) {survivors}"
    joined_left, joined_right = ".".join(left), ".".join(right)
    if joined_left and joined_right:
        ratio = SequenceMatcher(None, joined_left, joined_right, autojunk=False).ratio()
        if ratio > MAX_SIMILARITY:
            return "replacement host is a lightly masked variant of the original host"
    if contains_value(replacement, original):
        return "replacement host still contains the original host"
    return None


def _masking_failure(
    entity_type: str,
    original: str,
    replacement: str,
    preserved: frozenset[str] = frozenset(),
) -> str | None:
    """Whether ``replacement`` only lightly masks ``original``, judged per type.

    Comparing whole strings is wrong for anything with a host.  In
    ``https://api.<private-host>/api/webhook/contract-events`` the only
    identifying part is the host; the path states *which endpoint receives
    contract events*, which is a Requirement the rewrite must carry through.
    Whole-string similarity scores a correct host swap at 0.80 and rejects it,
    so the only way past the gate was to destroy the path — the validator was
    demanding the data be broken.  For hosted types the identity test therefore
    runs on the host, and on the local part as well for addresses, leaving the
    path free to survive.
    """

    if entity_type in URL_TYPES:
        retained_private_ids = set(private_resource_identifiers(original)) & set(
            private_resource_identifiers(replacement)
        )
        if retained_private_ids:
            return "replacement keeps a private resource identifier in the URL"
        if entity_type == "MEETING_URL":
            if _domain_of(original) == _domain_of(replacement):
                return "meeting replacement must move to a reserved synthetic host"
            return _host_masking_failure(_domain_of(original), _domain_of(replacement))
        if _host_is_public(_domain_of(original), preserved):
            # A public host is a requirement, not an identity: a block explorer,
            # a docs site, a vendor page.  Replacing it states that a different
            # service was used, and when the *path* is what carries the private
            # part -- an address, an invite code -- replacing the host while
            # keeping the path is exactly backwards: it disguises the public
            # half and publishes the private one.
            if _domain_of(replacement) != _domain_of(original):
                return "replacement must keep the public host and change the path"
            source = urlsplit(original)
            candidate = urlsplit(replacement)
            if (source.path, source.query, source.fragment) == (
                candidate.path,
                candidate.query,
                candidate.fragment,
            ):
                return "replacement must change the private path, query or fragment"
            return None
        return _host_masking_failure(_domain_of(original), _domain_of(replacement))

    if entity_type in {"EMAIL", "PRIVATE_DOMAIN"}:
        host = _host_masking_failure(_domain_of(original), _domain_of(replacement))
        if host is not None or entity_type == "PRIVATE_DOMAIN":
            return host
        # Both halves of an address identify: keeping the local part leaks the
        # person even under a synthetic domain.
        left, right = _local_part(original), _local_part(replacement)
        if not right:
            return "replacement has no local part"
        if left == right:
            return "replacement keeps the original local part"
        if similarity_ratio(left, right) > MAX_SIMILARITY:
            return "replacement local part is a lightly masked variant of the original"
        return None

    if similarity_ratio(original, replacement) > MAX_SIMILARITY:
        return "replacement is a lightly masked variant of the original"
    if _retains_original(original, replacement):
        return "replacement still contains the original value"
    return None


def _looks_like_credential(value: str) -> bool:
    return bool(
        nominate_secret_spans(value)
        or FAKE_CREDENTIAL_RE.search(value)
        or INTERNAL_TOKEN_RE.search(value)
        or LEGACY_PLACEHOLDER_RE.search(value)
    )


def _type_shape_failure(entity_type: str, replacement: str) -> str | None:
    if entity_type == "EMAIL":
        if not EMAIL_RE.fullmatch(replacement):
            return "replacement is not a syntactically valid address"
    elif entity_type == "PHONE":
        if not PHONE_RE.search(replacement):
            return "replacement is not phone-shaped"
    elif entity_type in {"PRIVATE_URL", "MEETING_URL"}:
        if not URL_RE.match(replacement):
            return "replacement is not a link"
    elif entity_type == "PERSON":
        if any(character.isdigit() for character in replacement) or "@" in replacement:
            return "a person name must not contain digits or '@'"
    elif entity_type == "PRIVATE_DOMAIN":
        if "/" in replacement or "@" in replacement or " " in replacement:
            return "a domain must not contain '/', '@' or spaces"
    return None


def _carried_originals(
    replacement: str, entity_id: str, by_id: Mapping[str, PiiEntity]
) -> set[str]:
    """Other entities whose real value survives inside this replacement.

    Only values long enough to be unambiguous are considered; a short one would
    match by coincidence and reject correct plans.
    """

    carried: set[str] = set()
    for other_id, other in by_id.items():
        if other_id == entity_id or other.policy != POLICY_SYNTHESIZE:
            continue
        value = other.canonical_value.strip()
        if len(value) < 8:
            continue
        if contains_value(replacement, value):
            carried.add(other_id)
    return carried


def validate_entity_chunk(
    payload: Mapping[str, Any],
    chunk: PlanChunk,
    registry: PiiEntityRegistry,
    reserved: Mapping[str, Sequence[str]],
) -> dict[str, EntityReplacement]:
    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    raw = payload.get("replacements")
    if not isinstance(raw, list):
        raise PlanConsistencyError(
            marked("PLAN_SCHEMA_INVALID: response must contain a replacements list"),
            failures=("PLAN_SCHEMA_INVALID",),
        )

    by_id = registry.by_id()
    preserved = preserved_surface_forms(registry)
    wanted = [item for item in chunk.entity_ids if item in by_id]
    reserved_flat = {
        value.casefold() for values in reserved.values() for value in values
    }
    all_originals = {
        entity.canonical_value.casefold(): entity.entity_id
        for entity in registry.entities
    }

    result: dict[str, EntityReplacement] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            fail("PLAN_SCHEMA_INVALID", f"replacements[{index}] must be an object")
            continue
        entity_id = entry.get("entity_id")
        if entity_id not in by_id or entity_id not in chunk.entity_ids:
            fail("PLAN_SCHEMA_INVALID", f"replacements[{index}] has an unknown entity_id")
            continue
        if entity_id in result:
            fail("PLAN_SCHEMA_INVALID", f"{entity_id} appears twice")
            continue
        entity = by_id[entity_id]
        replacement = entry.get("replacement")
        if not isinstance(replacement, str) or not replacement.strip():
            fail("PLAN_SCHEMA_INVALID", f"{entity_id} has no replacement")
            continue
        replacement = replacement.strip()

        if entity.entity_type in URL_TYPES and entity.entity_type != "MEETING_URL":
            replacement = _normalize_public_url_replacement(
                entity.canonical_value, replacement, preserved
            )

        if _looks_like_credential(replacement):
            # Checked before everything else: a generated credential is the most
            # severe failure class, and an earlier rejection must not mask it.
            fail(
                "PLAN_CREDENTIAL_GENERATED",
                f"{entity_id} replacement looks like a usable credential",
            )
            continue

        if entity.policy == POLICY_PRESERVE:
            if replacement != entity.canonical_value:
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{entity_id} is PRESERVE and must keep its original value",
                )
                continue
        else:
            if replacement.casefold() == entity.canonical_value.casefold():
                fail("PLAN_IDENTITY", f"{entity_id} replacement equals its original")
                continue
            masked = _masking_failure(
                entity.entity_type, entity.canonical_value, replacement, preserved
            )
            if masked is not None:
                fail("PLAN_IDENTITY", f"{entity_id} {masked}")
                continue
            carried = _carried_originals(replacement, entity_id, by_id)
            if carried:
                # A composite value -- an explorer link built around a wallet
                # address, an invite URL built around a project name -- must not
                # publish the part it was assembled from.  Left unchecked, the
                # same address had two fates depending on whether it stood alone
                # or sat inside a link, and the real one shipped in the link.
                fail(
                    "PLAN_RESIDUAL_PII",
                    f"{entity_id} replacement still carries {sorted(carried)}'s real value",
                )
                continue
            owner = all_originals.get(replacement.casefold())
            if owner is not None and owner != entity_id:
                fail(
                    "PLAN_COLLISION",
                    f"{entity_id} replacement equals another entity's original",
                )
                continue
            if replacement.casefold() in reserved_flat:
                fail("PLAN_COLLISION", f"{entity_id} replacement is already reserved")
                continue
            shape = _type_shape_failure(entity.entity_type, replacement)
            if shape is not None:
                fail("PLAN_SCHEMA_INVALID", f"{entity_id} {shape}")
                continue
            if entity.entity_type == "PRIVATE_DOMAIN" and not RESERVED_DOMAIN_RE.search(
                replacement
            ):
                fail(
                    "PLAN_REAL_LOOKING_VALUE",
                    f"{entity_id} synthetic domain must end in {RESERVED_DOMAIN_SUFFIX}",
                )
                continue
            public_url = entity.entity_type in URL_TYPES and entity.entity_type != "MEETING_URL" and _host_is_public(
                _domain_of(entity.canonical_value), preserved
            )
            if (
                entity.entity_type in HOSTED_TYPES
                and not public_url
                and not RESERVED_DOMAIN_RE.search(_domain_of(replacement))
            ):
                fail(
                    "PLAN_REAL_LOOKING_VALUE",
                    f"{entity_id} host {_domain_of(replacement)!r} is not a reserved domain",
                )
                continue
        if _looks_like_credential(replacement):
            fail(
                "PLAN_CREDENTIAL_GENERATED",
                f"{entity_id} replacement looks like a usable credential",
            )
            continue

        aliases: list[EntityAlias] = []
        for alias in entry.get("aliases") or []:
            if not isinstance(alias, dict):
                continue
            original = alias.get("original")
            value = alias.get("replacement")
            if (
                isinstance(original, str)
                and isinstance(value, str)
                and original.strip()
                and value.strip()
                and original.strip() in entity.surface_forms()
            ):
                if value.strip().casefold() == original.strip().casefold():
                    fail("PLAN_IDENTITY", f"{entity_id} alias replacement equals its original")
                    continue
                aliases.append(
                    EntityAlias(original=original.strip(), replacement=value.strip())
                )

        result[entity_id] = EntityReplacement(
            entity_id=entity_id,
            entity_type=entity.entity_type,
            policy=entity.policy,
            original=entity.canonical_value,
            replacement=replacement,
            bundle_id=entity.bundle_id,
            aliases=tuple(aliases),
            depends_on=tuple(
                item
                for item in (entry.get("depends_on") or [])
                if isinstance(item, str) and item in by_id
            ),
        )

    missing = [item for item in wanted if item not in result]
    if missing:
        fail("PLAN_INCOMPLETE", f"no replacement for {missing[:20]}")

    failures.extend(_bundle_failures(result, registry, chunk))

    if failures:
        raise PlanConsistencyError(
            marked("phase 2 entity chunk invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def _bundle_failures(
    replacements: Mapping[str, EntityReplacement],
    registry: PiiEntityRegistry,
    chunk: PlanChunk,
) -> list[str]:
    """Intra-bundle coherence: one identity, one domain, one derived local part."""

    failures: list[str] = []
    by_id = registry.by_id()
    preserved = preserved_surface_forms(registry)
    for bundle_id in chunk.bundle_ids:
        bundle = registry.bundle_by_id().get(bundle_id)
        if bundle is None:
            continue
        members = [
            replacements[item]
            for item in bundle.entity_ids
            if item in replacements and replacements[item].policy == POLICY_SYNTHESIZE
        ]
        if not members:
            continue
        domains = {
            _domain_of(item.replacement)
            for item in members
            if item.entity_type in HOSTED_TYPES or item.entity_type == "PRIVATE_DOMAIN"
            if not (
                item.entity_type in URL_TYPES
                and _host_is_public(
                    _domain_of(by_id[item.entity_id].canonical_value), preserved
                )
            )
        }
        domains.discard("")
        if len(domains) > 1:
            failures.append(
                f"PLAN_SCHEMA_INVALID: bundle {bundle_id} spreads across domains "
                f"{sorted(domains)}"
            )
        persons = [item for item in members if item.entity_type == "PERSON"]
        emails = [item for item in members if item.entity_type == "EMAIL"]
        if len(persons) == 1 and emails:
            tokens = {
                token.casefold()
                for token in WORD_RE.findall(persons[0].replacement)
                if len(token) >= 3
            }
            for email in emails:
                local = _local_part(email.replacement)
                if tokens and not any(token in local for token in tokens):
                    failures.append(
                        f"PLAN_SCHEMA_INVALID: bundle {bundle_id} address local part "
                        "does not derive from the synthetic person name"
                    )
        # Every member of a bundle must actually be in this chunk.  Members that
        # *are* in this chunk but were rejected above are not evidence of a split
        # and must not be reported as one: doing so pointed the diagnosis at the
        # chunker while the real fault was three rejected replacements.
        elsewhere = [
            item
            for item in bundle.entity_ids
            if item in by_id
            and by_id[item].policy != POLICY_PROTECTED
            and item not in replacements
            and item not in chunk.entity_ids
        ]
        if elsewhere:
            failures.append(
                f"PLAN_INCOMPLETE: bundle {bundle_id} was split across chunks ({elsewhere[:5]})"
            )
    return failures


# --------------------------------------------------------------------------- #
# Slot cluster validation
# --------------------------------------------------------------------------- #


def validate_slot_cluster(
    payload: Mapping[str, Any],
    cluster: SlotCluster,
    registry: SemanticRegistry,
    preserved: frozenset[str] = frozenset(),
) -> dict[str, SlotReplacement]:
    failures: list[str] = []

    def fail(code: str, detail: str) -> None:
        failures.append(f"{code}: {detail}")

    raw = payload.get("slot_replacements")
    if not isinstance(raw, list):
        raise PlanConsistencyError(
            marked("PLAN_SCHEMA_INVALID: response must contain a slot_replacements list"),
            failures=("PLAN_SCHEMA_INVALID",),
        )

    by_id = registry.by_id()
    result: dict[str, SlotReplacement] = {}

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            fail("PLAN_SCHEMA_INVALID", f"slot_replacements[{index}] must be an object")
            continue
        slot_id = entry.get("slot_id")
        if slot_id not in by_id or slot_id not in cluster.slot_ids:
            fail("PLAN_SCHEMA_INVALID", f"slot_replacements[{index}] unknown slot_id")
            continue
        if slot_id in result:
            fail("PLAN_SCHEMA_INVALID", f"{slot_id} appears twice")
            continue
        slot = by_id[slot_id]
        raw_history = entry.get("history")
        if not isinstance(raw_history, list) or len(raw_history) != len(slot.history):
            fail(
                "PLAN_SCHEMA_INVALID",
                f"{slot_id} must keep exactly {len(slot.history)} history entries",
            )
            continue
        history: list[SlotHistoryEntry] = []
        broken = False
        for position, (source, item) in enumerate(zip(slot.history, raw_history)):
            if not isinstance(item, dict):
                fail("PLAN_SCHEMA_INVALID", f"{slot_id} history[{position}] must be an object")
                broken = True
                break
            new_value = item.get("new_value")
            if not isinstance(new_value, str) or not new_value.strip():
                fail("PLAN_SCHEMA_INVALID", f"{slot_id} history[{position}] has no new_value")
                broken = True
                break
            new_value = _restore_preserved_unit(
                source.new_value, new_value, slot.unit, preserved
            )
            kept = _preserved_terms_in(source.new_value, preserved)
            if kept and not _preserved_terms_in(new_value, preserved) >= kept:
                fail(
                    "PLAN_PRESERVED_TERM_DROPPED",
                    f"{slot_id} history[{position}] drops the public term(s) "
                    f"{sorted(kept)}; those are requirements, not identities",
                )
                broken = True
                break
            # Padding is the model saying "this value cannot be re-valued":
            # it kept a public name and bolted a noun on to look like a change.
            # Take the keeping and drop the filler.  A numeric value gets no
            # such licence -- padding a count is dodging the work, not a signal.
            padded = _pads_original(source.new_value, new_value) and (
                numeric_value(source.new_value) is None
            )
            if padded:
                new_value = source.new_value
            if new_value.strip() == source.new_value:
                if padded or _is_only_preserved(source.new_value, preserved):
                    # A slot whose value *is* a public name has nothing to
                    # synthesize: the requirement is which public tool was
                    # chosen, and changing it states a different requirement.
                    history.append(
                        SlotHistoryEntry(
                            ordinal=source.ordinal,
                            op=source.op,
                            old_value=history[-1].new_value if history else None,
                            new_value=new_value.strip(),
                        )
                    )
                    continue
                fail(
                    "PLAN_IDENTITY",
                    f"{slot_id} history[{position}] keeps the original value",
                )
                broken = True
                break
            if numeric_value(source.new_value) is not None and (
                numeric_value(new_value) is None
            ):
                # Directional on purpose.  Whether a string parses as a number
                # is a proxy for its *rendering*, not its type: a COUNT records
                # "No badges", an AMOUNT records "free", a DURATION records
                # "a few minutes".  Requiring the replacement to match that
                # rendering made the natural re-valuation ("free" -> "$25")
                # look like a type change, and left one slot unsatisfiable --
                # its history held "0 Badges" and "No badges", so no single
                # rendering could satisfy both entries.  The declared
                # ``value_type`` is unchanged either way.
                #
                # The other direction stays a hard failure: dropping a number
                # that was there loses precision the requirement depends on,
                # and would silently break any arithmetic relation the slot
                # takes part in.
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} history[{position}] replaced a number with a "
                    "value that has none",
                )
                broken = True
                break
            history.append(
                SlotHistoryEntry(
                    ordinal=source.ordinal,
                    op=source.op,
                    old_value=history[-1].new_value if history else None,
                    new_value=new_value.strip(),
                )
            )
        if broken:
            continue

        raw_replacements = entry.get("literal_replacements")
        if not isinstance(raw_replacements, list):
            fail("PLAN_SCHEMA_INVALID", f"{slot_id} has no literal_replacements list")
            continue

        expected_occurrences = {
            (item.ordinal, item.start, item.end, item.source_literal): item
            for item in slot.literal_occurrences
        }
        literal_replacements: list[SlotLiteralReplacement] = []
        seen_occurrences: set[tuple[int, int, int, str]] = set()
        for position, raw_replacement in enumerate(raw_replacements):
            if not isinstance(raw_replacement, dict):
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} literal_replacements[{position}] is malformed",
                )
                continue
            ordinal = raw_replacement.get("ordinal")
            start = raw_replacement.get("start")
            end = raw_replacement.get("end")
            key = raw_replacement.get("original")
            value = raw_replacement.get("replacement")
            if (
                isinstance(ordinal, bool)
                or not isinstance(ordinal, int)
                or isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or not isinstance(key, str)
                or not isinstance(value, str)
                or not value.strip()
            ):
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} literal_replacements[{position}] is malformed",
                )
                continue
            occurrence_key = (ordinal, start, end, key)
            occurrence = expected_occurrences.get(occurrence_key)
            if occurrence is None:
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} literal_replacements[{position}] does not name a "
                    "recorded occurrence",
                )
                continue
            if raw_replacement.get("message_id") != occurrence.message_id:
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} literal_replacements[{position}] has the wrong message_id",
                )
                continue
            if occurrence_key in seen_occurrences:
                fail(
                    "PLAN_SCHEMA_INVALID",
                    f"{slot_id} repeats literal occurrence {occurrence_key[:3]}",
                )
                continue
            seen_occurrences.add(occurrence_key)
            value = _restore_preserved_unit(key, value, slot.unit, preserved)
            kept = _preserved_terms_in(key, preserved)
            if _pads_original(key, value) and numeric_value(key) is None:
                planned_value = key
            elif _is_only_preserved(key, preserved):
                # Forced locally rather than rejected: the correct answer is
                # known without asking, and a rejection would cost a retry.
                planned_value = key
            elif kept and not _preserved_terms_in(value, preserved) >= kept:
                fail(
                    "PLAN_PRESERVED_TERM_DROPPED",
                    f"{slot_id} occurrence replacement drops the public term(s) "
                    f"{sorted(kept)}",
                )
                continue
            elif value.strip() == key:
                fail(
                    "PLAN_IDENTITY",
                    f"{slot_id} occurrence replacement keeps a literal unchanged",
                )
                continue
            else:
                planned_value = value.strip()
            literal_replacements.append(
                SlotLiteralReplacement(
                    ordinal=occurrence.ordinal,
                    message_id=occurrence.message_id,
                    start=occurrence.start,
                    end=occurrence.end,
                    original=occurrence.source_literal,
                    replacement=planned_value,
                    match_mode=(
                        "SEMANTIC_ONLY"
                        if is_bare_numeric_literal(occurrence.source_literal)
                        else "EXACT"
                    ),
                )
            )
        if set(expected_occurrences) != seen_occurrences:
            fail(
                "PLAN_SCHEMA_INVALID",
                f"{slot_id} literal_replacements must cover every recorded occurrence "
                "exactly once",
            )
            continue
        for item in literal_replacements:
            if _looks_like_credential(item.replacement):
                fail("PLAN_CREDENTIAL_GENERATED", f"{slot_id} literal looks like a credential")
                break

        result[slot_id] = SlotReplacement(
            slot_id=slot_id,
            value_type=slot.value_type,
            history=tuple(history),
            literal_replacements=tuple(literal_replacements),
        )

    missing = [item for item in cluster.slot_ids if item in by_id and item not in result]
    if missing:
        fail("PLAN_INCOMPLETE", f"no replacement for slots {missing[:20]}")

    # Relations must hold under the *new* values, exactly.
    if not failures:
        failures.extend(_relation_failures(result, cluster, registry))

    if failures:
        raise PlanConsistencyError(
            marked("phase 2 slot cluster invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )
    return result


def _relation_failures(
    replacements: Mapping[str, SlotReplacement],
    cluster: SlotCluster,
    registry: SemanticRegistry,
) -> list[str]:
    failures: list[str] = []
    cluster_ids = set(cluster.slot_ids)
    for relation in registry.relations:
        if not set(relation.slot_ids) & cluster_ids:
            continue
        if not set(relation.slot_ids) <= set(replacements):
            # The relation reaches outside this cluster; it is checked once the
            # plan is assembled.
            continue
        for ordinal in relation.asserted_at_ordinals or (None,):
            values: dict[str, Decimal] = {}
            for slot_id in relation.slot_ids:
                value = _value_at(replacements[slot_id], ordinal)
                parsed = numeric_value(value)
                if parsed is not None:
                    values[slot_id] = parsed
            if len(values) != len(relation.slot_ids):
                continue
            if evaluate_relation(relation.expression, values) is False:
                failures.append(
                    "PLAN_RELATION_BROKEN: "
                    f"{relation.relation_id} does not hold under the new values at "
                    f"ordinal {ordinal}"
                )
                break
    return failures


def _value_at(replacement: SlotReplacement, ordinal: int | None) -> str:
    if not replacement.history:
        return ""
    if ordinal is None:
        return replacement.history[-1].new_value
    current = replacement.history[0].new_value
    for entry in replacement.history:
        if entry.ordinal <= ordinal:
            current = entry.new_value
    return current


# --------------------------------------------------------------------------- #
# Assembly and global validation
# --------------------------------------------------------------------------- #


def reserved_values(replacements: Mapping[str, EntityReplacement]) -> dict[str, list[str]]:
    """Everything already allocated, grouped for the next chunk's prompt."""

    buckets: dict[str, list[str]] = {}
    for item in sorted(replacements.values(), key=lambda value: value.entity_id):
        if item.policy != POLICY_SYNTHESIZE:
            continue
        key = "domains" if item.entity_type == "PRIVATE_DOMAIN" else item.entity_type.lower()
        for value in item.replacements():
            buckets.setdefault(key, []).append(value)
        if item.entity_type in HOSTED_TYPES:
            host = _domain_of(item.replacement)
            if host:
                buckets.setdefault("domains", []).append(host)
    return {key: sorted(set(values)) for key, values in sorted(buckets.items())}


def assemble_plan(
    entity_parts: Mapping[str, EntityReplacement],
    slot_parts: Mapping[str, SlotReplacement],
    secret_registry: SecretRegistry,
    semantic_registry: SemanticRegistry,
    *,
    plan_version: int = 2,
    amendments: Sequence[Mapping[str, Any]] = (),
) -> TransformationPlan:
    """Merge the chunks deterministically.

    Pure and order-independent, so the plan's output hash is stable whenever its
    chunks are -- which is what keeps phase-3 slice hashes reusable.
    """

    entities = tuple(entity_parts[key] for key in sorted(entity_parts))
    slots = tuple(slot_parts[key] for key in sorted(slot_parts))
    secrets = tuple(
        SecretPlanEntry(
            secret_id=entry.secret_id,
            internal_token=entry.internal_token,
            kind=entry.kind,
        )
        for entry in secret_registry.secrets
    )
    checks: list[dict[str, Any]] = []
    for relation in semantic_registry.relations:
        if not set(relation.slot_ids) <= set(slot_parts):
            continue
        values = {
            slot_id: numeric_value(_value_at(slot_parts[slot_id], None))
            for slot_id in relation.slot_ids
        }
        if any(value is None for value in values.values()):
            checks.append(
                {"relation_id": relation.relation_id, "satisfied": None, "evaluated": None}
            )
            continue
        outcome = evaluate_relation(
            relation.expression, {key: value for key, value in values.items() if value}
        )
        checks.append(
            {
                "relation_id": relation.relation_id,
                "satisfied": outcome,
                "evaluated": relation.expression,
            }
        )
    return TransformationPlan(
        plan_version=plan_version,
        entity_replacements=entities,
        slot_replacements=slots,
        secret_replacements=secrets,
        relation_checks=tuple(checks),
        reserved_values={
            key: tuple(values) for key, values in reserved_values(entity_parts).items()
        },
        amendments=tuple(dict(item) for item in amendments),
    )


def validate_plan(
    plan: TransformationPlan,
    *,
    entity_registry: PiiEntityRegistry,
    semantic_registry: SemanticRegistry,
    secret_registry: SecretRegistry,
) -> None:
    """Every global invariant, enforced locally after assembly."""

    failures: list[str] = []

    planned_ids = {entity.entity_id for entity in planned_entities(entity_registry)}
    covered = set(plan.entity_by_id())
    missing = sorted(planned_ids.difference(covered))
    if missing:
        failures.append(f"PLAN_INCOMPLETE: entities without a decision {missing[:20]}")
    unexpected = sorted(covered.difference(planned_ids))
    if unexpected:
        failures.append(f"PLAN_SCHEMA_INVALID: unknown entities in plan {unexpected[:20]}")

    slot_ids = {slot.slot_id for slot in semantic_registry.slots}
    slot_missing = sorted(slot_ids.difference(plan.slot_by_id()))
    if slot_missing:
        failures.append(f"PLAN_INCOMPLETE: slots without a decision {slot_missing[:20]}")

    secret_ids = {entry.secret_id for entry in secret_registry.secrets}
    plan_secret_ids = {entry.secret_id for entry in plan.secret_replacements}
    if secret_ids != plan_secret_ids:
        failures.append("PLAN_INCOMPLETE: secret entries do not match the shield registry")
    for entry in plan.secret_replacements:
        if entry.replacement is not None:
            failures.append(
                f"PLAN_CREDENTIAL_GENERATED: secret {entry.secret_id} carries a value; "
                "phase 6A owns credential rendering"
            )

    # Uniqueness across the whole plan, per type.
    #
    # "Shared replacement" is only a fault when the two entities are *different*
    # real-world things.  Phase 0B routinely splits one referent into several
    # entities -- a project written with and without a space, an acronym and its
    # expansion, the same link with and without a scheme -- and phase 2 then
    # correctly gives them one synthetic identity, cross-registering each other's
    # surface forms as aliases.  Flagging that as a collision demanded the
    # opposite: two different synthetic project names for one real project,
    # which is precisely the cross-message inconsistency phase 6B exists to
    # catch.
    #
    # Two entities that claim the same original surface form denote the same
    # thing, so sharing a replacement is required of them, not forbidden.  Two
    # genuinely distinct entities never overlap this way, so the guard against
    # collapsing distinct identities stays intact.
    surfaces = {
        item.entity_id: {original.casefold() for original, _ in item.pairs()}
        for item in plan.synthesized()
    }
    collisions: list[str] = []
    by_type: dict[str, dict[str, str]] = {}
    for item in plan.synthesized():
        owners = by_type.setdefault(item.entity_type, {})
        for value in item.replacements():
            key = value.casefold()
            other = owners.setdefault(key, item.entity_id)
            if other == item.entity_id:
                continue
            if surfaces[item.entity_id] & surfaces.get(other, set()):
                continue
            # One entry per pair: an alias and its canonical form both collide,
            # which reported the same fault twice.
            message = (
                f"PLAN_COLLISION: {item.entity_type} replacement shared by "
                f"{other} and {item.entity_id}"
            )
            if message not in collisions:
                collisions.append(message)
    failures.extend(collisions)

    # A slot's "synthetic" value must not be some entity's real one.  One slot
    # re-numbered a list of identifiers and picked a number that is itself a
    # real identifier elsewhere in the project, so the plan would have published
    # a true value while presenting it as synthetic.  Entity-vs-entity
    # collisions were already checked; this is the slot side of the same rule.
    real_values = {
        entity.canonical_value.strip(): entity.entity_id
        for entity in entity_registry.entities
        if entity.policy == POLICY_SYNTHESIZE and len(entity.canonical_value.strip()) >= 5
    }
    for slot in plan.slot_replacements:
        candidates = [
            item.replacement for item in slot.literal_replacements
        ] + [
            item.new_value for item in slot.history
        ]
        reported: set[str] = set()
        for value in candidates:
            for real, owner in real_values.items():
                if owner in reported or not contains_value(value or "", real):
                    continue
                reported.add(owner)
                failures.append(
                    f"PLAN_RESIDUAL_PII: slot {slot.slot_id} uses {owner}'s real value "
                    "as a synthetic one"
                )

    originals = {
        entity.canonical_value.casefold(): entity.entity_id
        for entity in entity_registry.entities
    }
    for item in plan.synthesized():
        for value in item.replacements():
            owner = originals.get(value.casefold())
            if owner is not None and owner != item.entity_id:
                failures.append(
                    f"PLAN_COLLISION: {item.entity_id} reuses {owner}'s original value"
                )
        for value in item.replacements():
            if _looks_like_credential(value):
                failures.append(
                    f"PLAN_CREDENTIAL_GENERATED: {item.entity_id} value looks like a credential"
                )

    # Relations must hold across cluster boundaries too.
    all_slots = plan.slot_by_id()
    for relation in semantic_registry.relations:
        if not set(relation.slot_ids) <= set(all_slots):
            continue
        for ordinal in relation.asserted_at_ordinals or (None,):
            values = {}
            for slot_id in relation.slot_ids:
                parsed = numeric_value(_value_at(all_slots[slot_id], ordinal))
                if parsed is not None:
                    values[slot_id] = parsed
            if len(values) != len(relation.slot_ids):
                continue
            if evaluate_relation(relation.expression, values) is False:
                failures.append(
                    f"PLAN_RELATION_BROKEN: {relation.relation_id} fails at ordinal {ordinal}"
                )
                break

    if failures:
        raise PlanConsistencyError(
            marked("transformation plan invalid: " + "; ".join(failures[:10])),
            failures=tuple(item.split(":", 1)[0] for item in failures),
        )


# --------------------------------------------------------------------------- #
# Per-message slice -- the transitive closure
# --------------------------------------------------------------------------- #


def plan_slice(
    plan: TransformationPlan,
    safe: SafeMessage,
    *,
    entity_registry: PiiEntityRegistry,
    semantic_registry: SemanticRegistry,
    semantics: MessageSemantics | None,
    preserve_terms: Sequence[str] = (),
) -> MessagePlanSlice:
    """Every plan decision this message must honour, as a transitive closure.

    The closure is the message's own entities, **plus every entity in the same
    identity bundle** (changing a person must invalidate a message that only
    mentions their address), **plus every slot in the same arithmetic cluster**
    (changing a count must invalidate a message that only mentions the total),
    plus the secret tokens present.  Given that, slice-hash equality really does
    imply the cached rewrite is still correct.
    """

    entity_by_id = plan.entity_by_id()
    bundles = entity_registry.bundle_by_id()

    own = [
        entity.entity_id
        for entity in entity_registry.for_ordinal(safe.ordinal)
        if entity.entity_id in entity_by_id
    ]
    closure: set[str] = set(own)
    for entity_id in own:
        replacement = entity_by_id[entity_id]
        if replacement.bundle_id and replacement.bundle_id in bundles:
            closure.update(
                item
                for item in bundles[replacement.bundle_id].entity_ids
                if item in entity_by_id
            )
        closure.update(item for item in replacement.depends_on if item in entity_by_id)

    slot_by_id = plan.slot_by_id()
    own_slots = [
        slot.slot_id
        for slot in semantic_registry.for_ordinal(safe.ordinal)
        if slot.slot_id in slot_by_id
    ]
    slot_closure: set[str] = set(own_slots)
    for group in relation_clusters(semantic_registry):
        if slot_closure & set(group):
            slot_closure.update(item for item in group if item in slot_by_id)

    relation_constraints = tuple(
        relation.expression
        for relation in semantic_registry.relations
        if set(relation.slot_ids) & slot_closure
    )

    expectations: dict[str, Any] = {}
    if semantics is not None:
        expectations = {
            "speech_act": semantics.speech_act,
            "polarity": semantics.polarity,
            "execution_status": semantics.execution_status,
            "ambiguity_kind": semantics.ambiguity_kind,
            "decisions": [dict(item) for item in semantics.decisions],
            "relations": list(semantics.relations),
            "semantic_facts": [dict(item) for item in semantics.semantic_facts],
        }

    preserved = tuple(
        item.replacement
        for item in plan.preserved()
        if any(
            occurrence.ordinal == safe.ordinal
            for entity in (entity_registry.by_id().get(item.entity_id),)
            if entity is not None
            for occurrence in entity.occurrences
        )
    )

    return MessagePlanSlice(
        ordinal=safe.ordinal,
        message_id=safe.message_id,
        bucket=safe.bucket,
        safe_text_sha256=safe.safe_text_sha256,
        entity_replacements=tuple(
            entity_by_id[entity_id] for entity_id in sorted(closure)
        ),
        slot_replacements=tuple(
            replace(
                slot_by_id[slot_id],
                literal_replacements=slot_by_id[slot_id].replacements_for(safe.ordinal),
            )
            for slot_id in sorted(slot_closure)
        ),
        secret_tokens=safe.secret_tokens,
        preserve_literals=tuple(
            sorted(
                {
                    *preserved,
                    *preserve_terms,
                    *find_terms_outside_pii(safe.safe_text, PUBLIC_ALLOWLIST),
                    *(
                        term
                        for fact in (semantics.semantic_facts if semantics else ())
                        for term in fact.get("must_preserve_terms", [])
                        if isinstance(term, str) and term
                    ),
                }
            )
        ),
        must_replace_terms=(),
        semantic_expectations=expectations,
        relation_constraints=relation_constraints,
        plan_version=plan.plan_version,
    )

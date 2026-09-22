#!/usr/bin/env python3
"""Build deterministic, fully validated offline Phase 2 repair plans.

This is deliberately narrower than the normal LLM-backed planner.  It exists
for projects whose very first Phase 2 entity chunk was rejected, leaving no
checkpoint that the migration repair can reuse.  The generated artifact is
hash-bound to Phase 0B and is accepted by ``pii_apply_offline_plan_repair.py``.

No network or model call is made here.  Both entity and slot payloads are run
through the production Phase 2 validators before the repair JSON is written.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

try:
    from PII import phase2_plan as p2
    from PII._compat import read_json, write_json
    from PII.models import PiiEntity, PiiEntityRegistry, SecretRegistry, SemanticRegistry
    from PII.phase0b_entities import POLICY_PRESERVE, POLICY_SYNTHESIZE
    from PII.textutil import canonical_sha256
    from pii_apply_offline_plan_repair import (
        REPAIR_SCHEMA,
        _entity_payload,
        _slot_payload,
    )
except (ImportError, ModuleNotFoundError):
    from Code.PII import phase2_plan as p2
    from Code.PII._compat import read_json, write_json
    from Code.PII.models import (
        PiiEntity,
        PiiEntityRegistry,
        SecretRegistry,
        SemanticRegistry,
    )
    from Code.PII.phase0b_entities import POLICY_PRESERVE, POLICY_SYNTHESIZE
    from Code.PII.textutil import canonical_sha256
    from Code.pii_apply_offline_plan_repair import (
        REPAIR_SCHEMA,
        _entity_payload,
        _slot_payload,
    )


SUPPORTED_PROJECTS = frozenset(
    {
        "37923084",
        "43796672",
        "43804272",
        "43948285",
        "44159104",
        "44159601",
        "44184953",
        "44186585",
        "44190396",
    }
)

FIRST_NAMES = (
    "Elena",
    "Marcus",
    "Priya",
    "Jonah",
    "Nadia",
    "Caleb",
    "Mira",
    "Theo",
    "Leona",
    "Darius",
    "Amara",
    "Felix",
)
LAST_NAMES = (
    "Hart",
    "Vale",
    "Sen",
    "Marlow",
    "Rowan",
    "Keene",
    "Solis",
    "Bennett",
    "Ibarra",
    "Quinn",
    "Mercer",
    "Lin",
)
WORDS_A = (
    "cobalt",
    "juniper",
    "cedar",
    "silver",
    "maple",
    "amber",
    "willow",
    "coral",
    "violet",
    "sable",
    "lunar",
    "crimson",
)
WORDS_B = (
    "harbor",
    "meadow",
    "atlas",
    "summit",
    "horizon",
    "orchard",
    "lantern",
    "grove",
    "bridge",
    "compass",
    "haven",
    "valley",
)

NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _words(project_id: str, key: str, attempt: int = 0) -> tuple[str, str]:
    value = _seed(project_id, key, attempt)
    return WORDS_A[value % len(WORDS_A)], WORDS_B[(value // len(WORDS_A)) % len(WORDS_B)]


def _safe_domain(
    project_id: str,
    key: str,
    originals: tuple[str, ...],
    used: set[str],
) -> str:
    for attempt in range(100):
        left, right = _words(project_id, key, attempt)
        candidate = f"{left}-{right}.example"
        if candidate in used:
            continue
        if any(
            p2._host_masking_failure(p2._domain_of(original), candidate) is not None
            for original in originals
            if p2._domain_of(original)
        ):
            continue
        used.add(candidate)
        return candidate
    raise RuntimeError(f"could not allocate a safe domain for {project_id}/{key}")


def _person_name(
    project_id: str, entity_id: str, original: str, used: set[str]
) -> str:
    for attempt in range(100):
        value = _seed(project_id, entity_id, attempt)
        candidate = (
            f"{FIRST_NAMES[value % len(FIRST_NAMES)]} "
            f"{LAST_NAMES[(value // len(FIRST_NAMES)) % len(LAST_NAMES)]}"
        )
        if (
            candidate.casefold() not in used
            and p2._masking_failure("PERSON", original, candidate) is None
        ):
            used.add(candidate.casefold())
            return candidate
    raise RuntimeError(f"could not allocate a person name for {entity_id}")


def _public_url(original: str, entity_id: str) -> str:
    host = p2._domain_of(original)
    source = urlsplit(original.strip("<>"))
    scheme = source.scheme if source.scheme in {"http", "https"} else "https"
    prefix = ""
    path_lower = source.path.casefold()
    for marker in ("/share/", "/file/", "/document/", "/folders/", "/design/"):
        if marker in path_lower:
            prefix = marker.rstrip("/")
            break
    return f"{scheme}://{host}{prefix}/sample-{entity_id.casefold()}"


def _private_url(domain: str, entity: PiiEntity) -> str:
    kind = {
        "MEETING_URL": "meet",
        "PRIVATE_REPOSITORY": "repos",
    }.get(entity.entity_type, "resource")
    return f"https://{domain}/{kind}/{entity.entity_id.casefold()}"


def _generic_entity_value(project_id: str, entity: PiiEntity, ordinal: int) -> str:
    left, right = _words(project_id, entity.entity_id)
    label = f"{left.title()} {right.title()}"
    suffix = ordinal + 1
    values = {
        "PROJECT_NAME": f"{label} Initiative {suffix}",
        "PRIVATE_ORGANIZATION": f"{label} Studio {suffix}",
        "LOCATION": f"{label}, Northland {suffix}",
        "PERSONAL_CONTEXT": f"a temporary family commitment during season {suffix}",
        "ACCOUNT_IDENTIFIER": f"ACCT-{8400 + suffix}",
        "PERSONAL_USERNAME": f"{left}_{right}_{suffix}",
        "SOCIAL_ACCOUNT": f"{label} Profile {suffix}",
        "PHONE": f"+1 (202) 555-{1000 + suffix:04d}",
    }
    return values.get(entity.entity_type, f"{label} Reference {suffix}")


def _entity_repairs(
    project_id: str, registry: PiiEntityRegistry
) -> dict[str, dict[str, Any]]:
    preserved = p2.preserved_surface_forms(registry)
    by_id = registry.by_id()
    used_domains: set[str] = set()
    domain_for_group: dict[str, str] = {}

    groups: dict[str, list[PiiEntity]] = {}
    for entity in p2.planned_entities(registry):
        key = entity.bundle_id or f"ENTITY-{entity.entity_id}"
        groups.setdefault(key, []).append(entity)
    for key, members in groups.items():
        hosted_originals = tuple(
            item.canonical_value
            for item in members
            if item.entity_type in p2.HOSTED_TYPES or item.entity_type == "PRIVATE_DOMAIN"
            if not (
                item.entity_type in p2.URL_TYPES
                and item.entity_type != "MEETING_URL"
                and p2._host_is_public(p2._domain_of(item.canonical_value), preserved)
            )
        )
        if hosted_originals:
            domain_for_group[key] = _safe_domain(
                project_id, key, hosted_originals, used_domains
            )

    people: dict[str, str] = {}
    used_people: set[str] = set()
    for position, entity in enumerate(p2.planned_entities(registry)):
        if entity.policy == POLICY_SYNTHESIZE and entity.entity_type == "PERSON":
            people[entity.entity_id] = _person_name(
                project_id, entity.entity_id, entity.canonical_value, used_people
            )

    result: dict[str, dict[str, Any]] = {}
    for position, entity in enumerate(p2.planned_entities(registry)):
        if entity.policy == POLICY_PRESERVE:
            result[entity.entity_id] = {
                "replacement": entity.canonical_value,
                "aliases": [],
                "depends_on": [],
            }
            continue
        if entity.policy != POLICY_SYNTHESIZE:
            continue

        group = entity.bundle_id or f"ENTITY-{entity.entity_id}"
        domain = domain_for_group.get(group)
        if entity.entity_type == "PERSON":
            replacement = people[entity.entity_id]
        elif entity.entity_type == "EMAIL":
            if domain is None:
                raise RuntimeError(f"no synthetic domain for {entity.entity_id}")
            bundle_people = [
                people[item.entity_id]
                for item in groups[group]
                if item.entity_id in people
            ]
            if len(bundle_people) == 1:
                local = re.sub(r"[^a-z]", ".", bundle_people[0].casefold()).strip(".")
                local = re.sub(r"\.+", ".", local)
            else:
                local = f"contact.{entity.entity_id.casefold()}"
            replacement = f"{local}@{domain}"
        elif entity.entity_type == "PRIVATE_DOMAIN":
            if domain is None:
                raise RuntimeError(f"no synthetic domain for {entity.entity_id}")
            replacement = domain
        elif entity.entity_type in p2.URL_TYPES:
            public = (
                entity.entity_type != "MEETING_URL"
                and p2._host_is_public(p2._domain_of(entity.canonical_value), preserved)
            )
            if public:
                replacement = _public_url(entity.canonical_value, entity.entity_id)
            else:
                if domain is None:
                    raise RuntimeError(f"no synthetic domain for {entity.entity_id}")
                replacement = _private_url(domain, entity)
        else:
            replacement = _generic_entity_value(project_id, entity, position)

        # Avoid a rare catalogue collision or a generated value that resembles
        # this particular source.  The deterministic suffix keeps the repair
        # reviewable while still letting the production validator be final.
        if p2._masking_failure(
            entity.entity_type, entity.canonical_value, replacement, preserved
        ) is not None:
            replacement = f"{_generic_entity_value(project_id, entity, position)} Alt"

        aliases: list[dict[str, str]] = []
        for surface in entity.surface_forms():
            if surface == entity.canonical_value:
                continue
            alias_value = replacement
            if entity.entity_type in p2.URL_TYPES and surface.rstrip().endswith("/"):
                alias_value = replacement.rstrip("/") + "/"
            aliases.append({"original": surface, "replacement": alias_value})
        result[entity.entity_id] = {
            "replacement": replacement,
            "aliases": aliases,
            "depends_on": [],
        }
    _apply_project_entity_overrides(project_id, result)
    return result


def _set_entity_replacement(
    decisions: dict[str, dict[str, Any]], entity_id: str, replacement: str
) -> None:
    """Change one audited decision while retaining its source-bound aliases."""

    decision = decisions[entity_id]
    decision["replacement"] = replacement
    for alias in decision.get("aliases", []):
        alias["replacement"] = (
            replacement.rstrip("/") + "/"
            if alias["original"].rstrip().endswith("/")
            else replacement
        )


def _apply_project_entity_overrides(
    project_id: str, decisions: dict[str, dict[str, Any]]
) -> None:
    """Resolve duplicate/nested discoveries in the audited repair set.

    Phase 0B may represent the same URL twice (punctuation variants) or record
    both a site root and a child page.  Independent synthetic values make the
    rewrite contract contradictory: one source span is then required to become
    two different strings.  These explicit, reviewable bindings make duplicate
    entities share one value and keep a child URL beneath its planned root.
    """

    if project_id == "44159104":
        for target, source in (("E0044", "E0011"), ("E0039", "E0030"), ("E0038", "E0034")):
            _set_entity_replacement(
                decisions, target, str(decisions[source]["replacement"])
            )
        contact_root = str(decisions["E0024"]["replacement"]).rstrip("/")
        _set_entity_replacement(decisions, "E0026", f"{contact_root}/contact")

    if project_id == "44190396":
        # Two repository URLs must fit in a SHORT interrogative while retaining
        # the backend/frontend distinction.  The bundle's reserved synthetic
        # domain is sufficient; per-entity IDs add no semantic information.
        domain = p2._domain_of(str(decisions["E0020"]["replacement"]))
        _set_entity_replacement(decisions, "E0020", f"{domain}/backend")
        _set_entity_replacement(decisions, "E0021", f"{domain}/frontend")


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _replace_number(source: str, value: Decimal) -> str:
    match = NUMBER_RE.search(source)
    rendered = _decimal_text(value)
    if not match:
        return rendered
    if "," in match.group(0) and value == value.to_integral_value():
        rendered = f"{int(value):,}"
    return source[: match.start()] + rendered + source[match.end() :]


def _scaled_number(source: str, value_type: str) -> Decimal | None:
    old = p2.numeric_value(source)
    if old is None:
        return None
    if value_type in {"COUNT", "DURATION"}:
        return old + Decimal(2 if old < 10 else 3)
    if value_type in {"PERCENTAGE", "RATE"}:
        return old + Decimal(7)
    if value_type == "DIMENSION":
        return (old * Decimal("1.5") + 1).quantize(Decimal("1"))
    if value_type == "AMOUNT":
        if old == 0:
            return Decimal(25)
        return (old * Decimal("1.25") + 5).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    return old + Decimal(2)


def _date_value(source: str) -> str:
    stripped = source.strip()
    relative = {
        "today": "next Monday",
        "tomorrow": "next Tuesday",
        "now": "next business day",
        "immediately": "within two business days",
        "tonight": "tomorrow evening",
        "this week": "the following week",
        "next week": "in two weeks",
        "this month": "next month",
        "next month": "in two months",
        "asap": "within two business days",
    }
    if stripped.casefold() in relative:
        return relative[stripped.casefold()]
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(stripped, fmt) + timedelta(days=17)
            return parsed.strftime(fmt)
        except ValueError:
            pass
    year = re.search(r"\b(20\d{2})\b", source)
    if year:
        return source[: year.start()] + str(int(year.group(1)) + 2) + source[year.end() :]
    if p2.numeric_value(source) is not None:
        return _replace_number(source, p2.numeric_value(source) + Decimal(2))
    return "the following business week"


def _version_value(source: str) -> str:
    number = p2.numeric_value(source)
    if number is None:
        return "version 3.0"
    return _replace_number(source, number + Decimal(1))


def _filename_value(source: str, key: str) -> str:
    suffix = Path(source.strip()).suffix
    return f"revised-deliverable-{_seed(key) % 900 + 100}{suffix or '.txt'}"


def _other_value(slot: Any, source: str, preserved: frozenset[str]) -> str:
    if p2._is_only_preserved(source, preserved):
        return source
    kept = sorted(p2._preserved_terms_in(source, preserved))
    slot_id = slot.slot_id
    if "HEADLINE" in slot_id:
        base = "A Simpler Way to Share Every Listing"
    elif "FIELD" in slot_id:
        base = "Preferred Contact Detail"
    elif "KEYWORD" in slot_id or "LABEL" in slot_id:
        base = "property guide"
    elif "ROLE" in slot_id:
        base = "content editor"
    elif any(word in slot_id for word in ("TIME", "TIMING", "DEADLINE", "SCHEDULE")):
        base = "within two business days"
    elif any(word in slot_id for word in ("TIER", "EDITION", "PLAN")):
        base = "standard tier"
    elif any(word in slot_id for word in ("FORMAT", "METHOD", "CHANNEL")):
        base = "guided document"
    elif "STATUS" in slot_id:
        base = "approved"
    elif "POSITION" in slot_id:
        base = "lower left"
    elif "SCOPE" in slot_id:
        base = "selected modules"
    elif "PRIORITY" in slot_id:
        base = "secondary priority"
    elif "DESTINATION" in slot_id:
        base = "support profile"
    elif "GRANULARITY" in slot_id:
        base = "per completed session"
    else:
        left, right = _words(slot.slot_id, source)
        base = f"{left} {right} option"
    if kept:
        return " ".join(kept + [base])
    return base


RELATION_VALUES: Mapping[str, Mapping[str, Decimal]] = {
    "37923084": {
        "ENRICHMENT_EMAIL_FOUND_COUNT": Decimal(17),
        "ENRICHMENT_EMAIL_MISSING_COUNT": Decimal(43),
        "ENRICHMENT_CONTACT_TOTAL_COUNT": Decimal(60),
    },
    "43948285": {
        "MAIN_WEBSITE_INVITE_COUNT": Decimal(2),
        "SEPARATE_STORE_INVITE_COUNT": Decimal(3),
        "ACCESS_INVITE_COUNT": Decimal(5),
    },
}


def _render_relation_value(source: str, unit: str | None, value: Decimal) -> str:
    if p2.numeric_value(source) is not None:
        return _replace_number(source, value)
    return f"{_decimal_text(value)} {unit or ''}".strip()


def _slot_value(
    project_id: str,
    slot: Any,
    source: str,
    preserved: frozenset[str],
) -> str:
    relation = RELATION_VALUES.get(project_id, {}).get(slot.slot_id)
    if relation is not None:
        return _render_relation_value(source, slot.unit, relation)
    if p2._is_only_preserved(source, preserved):
        return source
    value_type = slot.value_type
    if value_type == "DATE":
        candidate = _date_value(source)
    elif value_type == "VERSION":
        candidate = _version_value(source)
    elif value_type == "FILENAME":
        candidate = _filename_value(source, f"{project_id}:{slot.slot_id}")
    elif value_type == "IDENTIFIER":
        candidate = f"REF-{_seed(project_id, slot.slot_id, source) % 900000 + 100000}"
    elif value_type == "OTHER":
        number = _scaled_number(source, value_type)
        candidate = (
            _replace_number(source, number)
            if number is not None
            else _other_value(slot, source, preserved)
        )
    else:
        number = _scaled_number(source, value_type)
        if number is None:
            fallback = {
                "COUNT": Decimal(3),
                "DURATION": Decimal(15),
                "AMOUNT": Decimal(25),
                "RATE": Decimal(12),
                "PERCENTAGE": Decimal(35),
                "DIMENSION": Decimal(24),
                "THRESHOLD": Decimal(8),
            }.get(value_type, Decimal(3))
            candidate = f"{_decimal_text(fallback)} {slot.unit or ''}".strip()
        else:
            candidate = _replace_number(source, number)

    kept = sorted(p2._preserved_terms_in(source, preserved))
    if kept and not p2._preserved_terms_in(candidate, preserved) >= set(kept):
        candidate = " ".join(kept + [candidate])
    return candidate.strip()


def _slot_repairs(
    project_id: str,
    semantics: SemanticRegistry,
    preserved: frozenset[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for slot in semantics.slots:
        by_source: dict[str, str] = {}
        values: list[str] = []
        for entry in slot.history:
            key = entry.new_value.casefold()
            value = by_source.setdefault(
                key, _slot_value(project_id, slot, entry.new_value, preserved)
            )
            values.append(value)
        result[slot.slot_id] = values
    return result


def _validate(
    registry: PiiEntityRegistry,
    semantics: SemanticRegistry,
    secret_registry: SecretRegistry,
    entities: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> tuple[int, int]:
    entity_parts: dict[str, Any] = {}
    entity_chunks = p2.bundle_chunks(registry, max_bundles=25, max_chars=24000)
    for chunk in entity_chunks:
        payload = _entity_payload(chunk, entities)
        entity_parts.update(
            p2.validate_entity_chunk(
                payload, chunk, registry, p2.reserved_values(entity_parts)
            )
        )
    slot_parts: dict[str, Any] = {}
    clusters = p2.slot_clusters(semantics, max_chars=24000)
    preserved = p2.preserved_surface_forms(registry)
    for cluster in clusters:
        payload = _slot_payload(cluster, semantics, slots)
        slot_parts.update(
            p2.validate_slot_cluster(payload, cluster, semantics, preserved)
        )
    plan = p2.assemble_plan(entity_parts, slot_parts, secret_registry, semantics)
    p2.validate_plan(
        plan,
        entity_registry=registry,
        semantic_registry=semantics,
        secret_registry=secret_registry,
    )
    return len(entity_parts), len(slot_parts)


def prepare(project_id: str, work_root: Path) -> Path:
    if project_id not in SUPPORTED_PROJECTS:
        raise ValueError(f"project {project_id} is not in the audited repair set")
    run_dir = work_root / project_id
    registry_json = read_json(run_dir / "phase0b_pii_discovery" / "entities.json")
    registry = PiiEntityRegistry.from_json(registry_json)
    semantics = SemanticRegistry.from_json(
        read_json(run_dir / "phase1b_project_consolidation" / "registry.json")
    )
    secret_envelope = read_json(run_dir / "phase0a_secret_shield" / "registry.json")
    secret_registry = SecretRegistry.from_json(secret_envelope["body"])
    entities = _entity_repairs(project_id, registry)
    slots = _slot_repairs(project_id, semantics, p2.preserved_surface_forms(registry))
    entity_count, slot_count = _validate(
        registry, semantics, secret_registry, entities, slots
    )
    repair = {
        "schema_version": REPAIR_SCHEMA,
        "project_id": project_id,
        "source_registry_sha256": canonical_sha256(registry_json),
        "entities": entities,
        "slots": slots,
        "offline_validation": {
            "status": "PASS",
            "entity_count": entity_count,
            "slot_count": slot_count,
            "method": "deterministic_agent_reconstruction",
        },
    }
    path = run_dir / "agent_repairs" / "phase2_plan.json"
    write_json(path, repair)
    return path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", action="append", required=True)
    parser.add_argument("--work-root", type=Path, default=root / "outputs" / "pii_runs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for project_id in args.project_id:
        path = prepare(project_id, args.work_root)
        print(f"[{project_id}] validated offline Phase 2 repair written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

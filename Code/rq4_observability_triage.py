#!/usr/bin/env python3
"""Build private RQ4 validator work items and audit observable surfaces.

This stage intentionally runs before Acceptance Criteria or hidden-validator
authoring.  It prevents a runnable-but-thin repository from being mistaken for
an execution-valid RQ4 environment.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Iterable, Mapping
import zipfile

try:  # Package import in tests; script import in the CLI.
    from . import build_rq4_code_environments as cenv
except ImportError:  # pragma: no cover - exercised by direct CLI execution
    import build_rq4_code_environments as cenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLANS_ROOT = (
    ROOT / "ccfa-workfiles" / "experiments" / "rq4-code-environment" / "projects"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation"
)
BUILD_STATUS = "READY_FOR_CODE_ENV_RECONSTRUCTION"

SCHEMA_VERSION = "rq4-validator-work-item-v1"
REPORT_SCHEMA_VERSION = "rq4-observability-triage-v1"


class TriageError(RuntimeError):
    """The frozen inputs cannot produce a trustworthy triage record."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TriageError(f"cannot read {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise TriageError(f"path escapes workspace: {path}") from exc
    return PurePosixPath(relative).as_posix()


def _feature_map(
    state: Mapping[str, str],
    requirements: Mapping[str, Mapping[str, Any]],
    states: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    features, mappings = cenv._features_for_state(state, requirements, states)
    return {
        str(mapping["requirement_id"]): deepcopy(feature)
        for feature, mapping in zip(features, mappings, strict=True)
    }


CURRENT_SURFACES: dict[str, set[str]] = {
    "web": {"BUILD", "REGRESSION", "CATALOG_API", "STATIC_DOM", "STATIC_TEXT"},
    "mobile": {
        "BUILD",
        "REGRESSION",
        "APP_CONFIG",
        "STATIC_MOBILE_PREVIEW",
        "STATIC_TEXT",
    },
    "docx": {"BUILD", "REGRESSION", "OOXML_PARAGRAPHS", "STATIC_TEXT"},
    "report": {
        "BUILD",
        "REGRESSION",
        "OOXML_PARAGRAPHS",
        "SIMPLE_PDF_TEXT",
        "STATIC_TEXT",
    },
    "kicad": {
        "BUILD",
        "REGRESSION",
        "KICAD_TEXT_LABELS",
        "EMPTY_PCB_OUTLINE",
        "STATIC_TEXT",
    },
}


def _archive_contract_surfaces(archive_path: Path, renderer: str) -> tuple[set[str], dict[str, Any] | None]:
    """Read only the public contract that is actually present in this snapshot."""

    with zipfile.ZipFile(archive_path) as archive:
        try:
            info = archive.getinfo("behavior_contract.json")
        except KeyError:
            return set(CURRENT_SURFACES.get(renderer, set())), None
        if info.file_size > 1024 * 1024:
            raise TriageError(f"oversized behavior contract in {archive_path}")
        try:
            contract = json.loads(archive.read(info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TriageError(f"invalid behavior contract in {archive_path}: {exc}") from exc
    if not isinstance(contract, dict):
        raise TriageError(f"behavior contract is not an object in {archive_path}")

    surfaces = set(CURRENT_SURFACES.get(renderer, set()))
    schema_version = contract.get("schema_version")
    if schema_version == "rq4-public-behavior-contract-v1":
        surfaces.update({"PROJECT_BEHAVIOR_CONTRACT", "DOMAIN_BEHAVIOR", "ROUTES"})
        declared = set(contract.get("observable_surfaces") or [])
        if renderer == "web":
            surfaces.update({"DOM_SEMANTICS", "BROWSER_INTERACTION"})
        elif renderer == "mobile":
            surfaces.update(
                {
                    "NATIVE_OR_EQUIVALENT_APP_MODEL",
                    "RESOURCE_AND_LOCALE_MODEL",
                    "APP_INTERACTION",
                }
            )
            if (
                "platform_build_metadata" in declared
                and contract.get("platform_build_model")
            ):
                surfaces.add("PLATFORM_BUILD_METADATA")
    elif schema_version == "artifact-behavior-contract-v1":
        declared = set(contract.get("observable_surfaces") or [])
        if renderer == "docx":
            if any(value.startswith("styles.") for value in declared):
                surfaces.add("OOXML_STYLES")
            if any(value.startswith(("content_controls.", "fields.")) for value in declared):
                surfaces.add("OOXML_FIELDS_OR_CONTENT_CONTROLS")
            if any(value.startswith(("help.", "fields.")) for value in declared):
                surfaces.add("DOCUMENT_INTERACTION_METADATA")
        elif renderer == "report":
            if any(value.startswith("pdf_coordinates.") for value in declared):
                surfaces.add("PDF_LAYOUT_GEOMETRY")
            if any(value.startswith("package_manifest.") for value in declared):
                surfaces.add("EDITABLE_TEMPLATE_PACKAGE")
            if any(value.startswith("ooxml.") for value in declared):
                surfaces.add("OOXML_STYLES")
        elif renderer == "kicad":
            if any(value.startswith("components.") for value in declared):
                surfaces.add("KICAD_COMPONENTS")
            if any(value.startswith("nets.") for value in declared):
                surfaces.add("KICAD_NETS")
            if any(value.startswith(("geometry.", "footprints.")) for value in declared):
                surfaces.add("KICAD_GEOMETRY")
    else:
        raise TriageError(
            f"unsupported behavior contract schema {schema_version!r} in {archive_path}"
        )
    return surfaces, contract


SUBJECTIVE_PATTERNS = (
    r"\bmodern\b",
    r"\bprofessional\b",
    r"\bpremium\b",
    r"\bpolished\b",
    r"\bcleanest\b",
    r"\blooks? (?:good|great|better)\b",
    r"\bvisually balanced\b",
    r"\bhigh[- ]end\b",
    r"\bmore attractive\b",
    r"\bstronger\b",
    r"\bquality\b",
)

INTERACTION_PATTERNS = (
    r"\bclick",
    r"\bmodal",
    r"\bdialog",
    r"\bform",
    r"\bsubmit",
    r"\blog[ -]?in",
    r"\bsign[ -]?in",
    r"\bupload",
    r"\btab\b",
    r"\bhover",
    r"\bkeyboard",
    r"\bbutton",
    r"\bdropdown",
    r"\bnavigat",
    r"\bredirect",
)

ROUTE_PATTERNS = (
    r"\bpage\b",
    r"\broute\b",
    r"\burl\b",
    r"\blink\b",
    r"\bhomepage\b",
    r"\bdashboard\b",
)


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _required_surfaces(
    renderer: str,
    components: set[str],
    task_text: str,
) -> set[str]:
    required = {"BUILD", "REGRESSION"}
    if renderer == "web":
        # The current template promises a local domain service but only exposes
        # a feature catalogue.  Even a confirmation target with sparse scope
        # tags needs an implementation-level project behavior contract before
        # it can support a non-configuration RQ4 test.
        required.add("PROJECT_BEHAVIOR_CONTRACT")
        if components & {"FRONTEND", "UI_UX"}:
            required.add("DOM_SEMANTICS")
        if _matches_any(task_text, INTERACTION_PATTERNS):
            required.add("BROWSER_INTERACTION")
        if _matches_any(task_text, ROUTE_PATTERNS):
            required.add("ROUTES")
        if components & {
            "AUTH",
            "BACKEND",
            "EMAIL",
            "INFRASTRUCTURE",
            "PAYMENT",
            "SMART_CONTRACT",
        }:
            required.add("DOMAIN_BEHAVIOR")
    elif renderer == "mobile":
        required.update({"NATIVE_OR_EQUIVALENT_APP_MODEL", "RESOURCE_AND_LOCALE_MODEL"})
        if components & {"UI_UX", "ANDROID_APP", "IOS_APP"}:
            required.add("APP_INTERACTION")
        if components & {"BUILD_PIPELINE", "ANDROID_APP", "IOS_APP"}:
            required.add("PLATFORM_BUILD_METADATA")
    elif renderer == "docx":
        required.update({"OOXML_STYLES", "OOXML_FIELDS_OR_CONTENT_CONTROLS"})
        if _matches_any(task_text, (r"\bhover", r"\benter\b", r"\bhelp text", r"\bfield")):
            required.add("DOCUMENT_INTERACTION_METADATA")
    elif renderer == "report":
        required.update({"OOXML_STYLES", "PDF_LAYOUT_GEOMETRY"})
        if _matches_any(task_text, (r"\btemplate", r"\bcanva", r"\beditable")):
            required.add("EDITABLE_TEMPLATE_PACKAGE")
    elif renderer == "kicad":
        required.update({"KICAD_COMPONENTS", "KICAD_NETS", "KICAD_GEOMETRY"})
    else:
        required.add("UNKNOWN_RENDERER")
    return required


def _recommended_validator_types(renderer: str) -> list[str]:
    if renderer == "web":
        return [
            "API_BEHAVIOR",
            "DOM_SEMANTICS",
            "ROUTE_NAVIGATION",
            "BROWSER_INTERACTION",
            "RESPONSIVE_GEOMETRY",
            "EXPLICIT_COMPUTED_STYLE",
            "TASK_SCOPED_ACCESSIBILITY",
        ]
    if renderer == "mobile":
        return [
            "APP_STATE_TRANSITION",
            "RESOURCE_AND_LOCALE",
            "MEDIA_BEHAVIOR",
            "RESPONSIVE_GEOMETRY",
            "PLATFORM_BUILD_METADATA",
        ]
    if renderer == "docx":
        return [
            "OOXML_STYLE",
            "CONTENT_CONTROL_AND_FIELD",
            "DOCUMENT_TEXT",
            "DOCUMENT_LAYOUT",
        ]
    if renderer == "report":
        return [
            "OOXML_STYLE",
            "PDF_TEXT",
            "PDF_LAYOUT_GEOMETRY",
            "PACKAGE_CONTENTS",
        ]
    if renderer == "kicad":
        return [
            "KICAD_COMPONENT",
            "KICAD_NET_CONNECTIVITY",
            "KICAD_FOOTPRINT",
            "KICAD_GEOMETRY",
            "KICAD_CLEARANCE",
        ]
    return []


def _triage_record(
    *,
    renderer: str,
    components: set[str],
    task_text: str,
    pre_features: Mapping[str, Mapping[str, Any]],
    post_features: Mapping[str, Mapping[str, Any]],
    affected_ids: list[str],
    current_surfaces: set[str] | None = None,
) -> dict[str, Any]:
    current = set(
        CURRENT_SURFACES.get(renderer, set())
        if current_surfaces is None
        else current_surfaces
    )
    required = _required_surfaces(renderer, components, task_text)
    missing = sorted(required - current)
    changed_observation = any(
        pre_features.get(requirement_id) != post_features.get(requirement_id)
        for requirement_id in affected_ids
    )
    subjective = _matches_any(task_text, SUBJECTIVE_PATTERNS)
    blockers: list[str] = []
    if not changed_observation:
        blockers.append("NO_CURRENTLY_EXPOSED_PRE_POST_BEHAVIOR_DIFFERENCE")
    if missing:
        blockers.append("CURRENT_CODE_ENVIRONMENT_LACKS_REQUIRED_SURFACE")
    if subjective:
        blockers.append("SUBJECTIVE_CLAUSES_REQUIRE_SEPARATION_OR_EXCLUSION")

    if not changed_observation:
        status = "NO_DETERMINISTIC_OBSERVABLE"
    elif missing:
        status = "ENVIRONMENT_REPAIR_REQUIRED"
    elif subjective:
        status = "SUBJECTIVE_REVIEW_REQUIRED"
    else:
        status = "ELIGIBLE_FOR_VALIDATOR_AUTHORING"
    return {
        "status": status,
        "currently_exposed_pre_post_difference": changed_observation,
        "subjective_clause_detected": subjective,
        "current_surfaces": sorted(current),
        "required_surfaces": sorted(required),
        "missing_surfaces": missing,
        "recommended_validator_types": _recommended_validator_types(renderer),
        "blockers": blockers,
        "decision_authority": "PROPOSED_BY_AGENT_REQUIRES_INDEPENDENT_REVIEW",
    }


def _source_record(path: Path) -> dict[str, str]:
    return {"path": _portable(path), "sha256": _sha256(path)}


def _project_work_items(plan_path: Path, code_environment_root: Path) -> list[dict[str, Any]]:
    plan = cenv._read_json(plan_path)
    project_id = str(plan["project_id"])
    sources = cenv._verify_sources(plan)
    graph = cenv._read_json(sources["requirement_state_graph"])
    normalized = cenv._read_json(sources["normalized_project"])
    _, _, requirements, states = cenv._replay(plan, graph, normalized)
    profile = plan.get("repository_profile")
    if not isinstance(profile, Mapping):
        raise TriageError(f"{project_id}: repository profile is missing")
    renderer = str(profile.get("renderer", ""))

    items: list[dict[str, Any]] = []
    for target in plan.get("targets", []):
        if target.get("plan_status") != BUILD_STATUS:
            continue
        target_id = str(target["target_id"])
        output_contract = target.get("output_contract", {})
        archive_relative = str(output_contract.get("archive_path", ""))
        archive_path = ROOT / Path(*PurePosixPath(archive_relative).parts)
        manifest_path = archive_path.parent / "manifest.json"
        if not archive_path.is_file() or not manifest_path.is_file():
            raise TriageError(f"{target_id}: Code Environment archive/manifest missing")
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, Mapping):
            raise TriageError(f"{target_id}: invalid Code Environment manifest")
        if manifest.get("archive_sha256") != _sha256(archive_path):
            raise TriageError(f"{target_id}: archive hash disagrees with manifest")

        state_refs = target.get("state_refs", {})
        pre_state = cenv._state_map(state_refs.get("pre_task"))
        post_state = cenv._state_map(state_refs.get("post_task"))
        pre_features = _feature_map(pre_state, requirements, states)
        post_features = _feature_map(post_state, requirements, states)
        affected_ids = [str(value) for value in state_refs.get("affected_requirement_ids", [])]
        components = {
            str(component)
            for requirement_id in affected_ids
            for feature in (
                post_features.get(requirement_id) or pre_features.get(requirement_id) or {},
            )
            for component in feature.get("components", [])
        }
        task = deepcopy(target.get("target_task"))
        task_text = str(task.get("text", "")) if isinstance(task, Mapping) else ""
        rq3_source = target.get("source_artifacts", {}).get("rq3_instance", {})
        if not isinstance(rq3_source, Mapping):
            raise TriageError(f"{target_id}: frozen RQ3 source is missing")
        rq3_path = cenv._resolve_source(str(rq3_source.get("path", "")))
        if not rq3_path.is_file() or _sha256(rq3_path) != rq3_source.get(
            "file_sha256"
        ):
            raise TriageError(f"{target_id}: frozen RQ3 source is stale")
        current_surfaces, behavior_contract = _archive_contract_surfaces(
            archive_path, renderer
        )
        triage = _triage_record(
            renderer=renderer,
            components=components,
            task_text=task_text,
            pre_features=pre_features,
            post_features=post_features,
            affected_ids=affected_ids,
            current_surfaces=current_surfaces,
        )
        item = {
            "schema_version": SCHEMA_VERSION,
            "visibility": "RESEARCHER_PRIVATE_NEVER_AGENT_VISIBLE_DURING_BENCHMARK",
            "project_id": project_id,
            "target_id": target_id,
            "input_release": plan.get("input_release"),
            "target_message_id": target["target_message_id"],
            "target_fingerprint": target["target_fingerprint"],
            "task": task,
            "repository_profile": deepcopy(profile),
            "affected_components": sorted(components),
            "affected_requirement_ids": affected_ids,
            "preserved_requirement_ids": [
                str(value)
                for value in state_refs.get("preserved_requirement_ids", [])
            ],
            "affected_transitions": deepcopy(target.get("affected_transition_digest", [])),
            "rq3_gold": {
                "decision_by_condition": {
                    condition: target.get("rq3_gold_decision")
                    for condition in target.get("condition_scope", ["C1", "C2"])
                },
                "source_path": _portable(rq3_path),
                "file_sha256": _sha256(rq3_path),
                "content_sha256": rq3_source.get("content_sha256"),
            },
            "pre_task_state": pre_state,
            "post_task_state": post_state,
            "pre_task_observable_features": {
                requirement_id: deepcopy(pre_features.get(requirement_id))
                for requirement_id in affected_ids
            },
            "post_task_observable_features": {
                requirement_id: deepcopy(post_features.get(requirement_id))
                for requirement_id in affected_ids
            },
            "code_environment": {
                "archive_path": _portable(archive_path),
                "archive_sha256": _sha256(archive_path),
                "manifest_path": _portable(manifest_path),
                "manifest_sha256": _sha256(manifest_path),
                "repository_tree_sha256": manifest.get("repo_sha256"),
                "before_message_id": manifest.get("before_message_id"),
                "behavior_contract": behavior_contract,
            },
            "observability_triage": triage,
            "frontend_evaluation_policy": {
                "deterministic_main_rq4": [
                    "DOM_SEMANTICS",
                    "ROUTE_NAVIGATION",
                    "BROWSER_INTERACTION",
                    "RESPONSIVE_GEOMETRY",
                    "EXPLICIT_COMPUTED_STYLE",
                    "RESOURCE_AND_MEDIA_BEHAVIOR",
                    "TASK_SCOPED_ACCESSIBILITY",
                    "FROZEN_SCREENSHOT_REGION",
                ],
                "subjective_only_excluded_from_main_rq4": True,
                "browser_environment_must_be_frozen": True,
                "default_candidate_viewports": [
                    {"width": 1440, "height": 900, "device_scale_factor": 1},
                    {"width": 768, "height": 1024, "device_scale_factor": 1},
                    {"width": 390, "height": 844, "device_scale_factor": 1},
                ],
                "enable_only_task_relevant_viewports": True,
            },
            "authoring_contract": {
                "acceptance_criteria_status": "NOT_AUTHORED",
                "validator_status": "NOT_AUTHORED",
                "reference_delivery_status": "NOT_AUTHORED",
                "partial_delivery_status": "NOT_AUTHORED",
                "calibration_status": "NOT_RUN",
                "leakage_semantic_audit_status": "NOT_RUN",
                "eligibility_status": "NOT_DECIDED",
                "agent_may_not_self_certify_calibration_or_eligibility": True,
            },
            "source_artifacts": {
                "build_plan": _source_record(plan_path),
                "requirement_state_graph": _source_record(sources["requirement_state_graph"]),
                "normalized_project": _source_record(sources["normalized_project"]),
            },
        }
        items.append(item)
    return items


def build_triage(
    *,
    plans_root: Path,
    output_root: Path,
    code_environment_root: Path,
    project_ids: list[str] | None,
    replace: bool,
) -> dict[str, Any]:
    # Archive paths are frozen in each Build Plan.  Keep the explicit root
    # argument in the public CLI for symmetry with the other RQ4 tools and
    # reject a mismatched caller root before reading any target artifact.
    if code_environment_root.resolve() != (ROOT / "Code Environment").resolve():
        raise TriageError(
            "this release's Build Plans are bound to the canonical Code Environment root"
        )
    plan_paths = sorted(plans_root.glob("*/rq4_build_plan.json"))
    if project_ids is not None:
        wanted = set(project_ids)
        plan_paths = [path for path in plan_paths if path.parent.name in wanted]
        missing = sorted(wanted - {path.parent.name for path in plan_paths})
        if missing:
            raise TriageError(f"missing project plans: {missing}")
    if not plan_paths:
        raise TriageError("no project Build Plans found")
    if output_root.exists() and not replace:
        raise TriageError(f"refusing to overwrite existing triage root: {output_root}")

    staging = output_root.with_name(f".{output_root.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    all_summaries: list[dict[str, Any]] = []
    try:
        for plan_path in plan_paths:
            items = _project_work_items(plan_path, code_environment_root)
            project_id = plan_path.parent.name
            target_root = staging / "projects" / project_id / "targets"
            for item in items:
                _write_json(target_root / item["target_id"] / "work_item.json", item)
            status_counts = Counter(
                item["observability_triage"]["status"] for item in items
            )
            summary = {
                "schema_version": "rq4-observability-project-summary-v1",
                "project_id": project_id,
                "target_count": len(items),
                "status_counts": dict(sorted(status_counts.items())),
                "targets": [
                    {
                        "target_id": item["target_id"],
                        "status": item["observability_triage"]["status"],
                        "missing_surfaces": item["observability_triage"]["missing_surfaces"],
                        "work_item": (
                            f"projects/{project_id}/targets/{item['target_id']}/work_item.json"
                        ),
                    }
                    for item in items
                ],
            }
            _write_json(staging / "projects" / project_id / "summary.json", summary)
            all_summaries.append(summary)

        total = sum(row["target_count"] for row in all_summaries)
        combined = Counter()
        for row in all_summaries:
            combined.update(row["status_counts"])
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "scope": "RQ4_VALIDATOR_AUTHORING_PREFLIGHT",
            "target_count": total,
            "project_count": len(all_summaries),
            "status_counts": dict(sorted(combined.items())),
            "projects": [
                {
                    "project_id": row["project_id"],
                    "target_count": row["target_count"],
                    "status_counts": row["status_counts"],
                    "summary": f"projects/{row['project_id']}/summary.json",
                }
                for row in all_summaries
            ],
            "gate_policy": {
                "eligible_for_validator_authoring_requires": (
                    "ELIGIBLE_FOR_VALIDATOR_AUTHORING"
                ),
                "environment_repair_precedes_validator_authoring": True,
                "subjective_visual_only_is_not_main_rq4": True,
                "agent_generated_artifacts_require_independent_review": True,
                "calibration_and_eligibility_are_deterministic_gates": True,
            },
        }
        _write_json(staging / "observability_triage.json", report)
        # Work items may be refreshed after a deterministic Code Environment
        # rebuild.  Preserve authored evidence byte-for-byte; its embedded
        # source hashes remain stale on purpose until the responsible Agent
        # explicitly rebases and revalidates it against the new work item.
        if output_root.exists():
            for old_target in output_root.glob("projects/*/targets/*"):
                if not old_target.is_dir():
                    continue
                relative = old_target.relative_to(output_root)
                new_target = staging / relative
                if not (new_target / "work_item.json").is_file():
                    continue
                for folder in ("author", "reference", "red_team", "reviews"):
                    source = old_target / folder
                    destination = new_target / folder
                    if source.is_dir() and not destination.exists():
                        shutil.copytree(source, destination)
        if output_root.exists():
            shutil.rmtree(output_root)
        shutil.move(str(staging), str(output_root))
        return report
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans-root", type=Path, default=DEFAULT_PLANS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--code-environment-root", type=Path, default=ROOT / "Code Environment")
    parser.add_argument("--project-id", action="append", dest="project_ids")
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_triage(
            plans_root=args.plans_root,
            output_root=args.output_root,
            code_environment_root=args.code_environment_root,
            project_ids=args.project_ids,
            replace=args.replace,
        )
        print(
            f"RQ4 observability triage: projects={report['project_count']}, "
            f"targets={report['target_count']}, statuses={report['status_counts']}"
        )
        return 0
    except (OSError, TriageError, cenv.BuildError) as exc:
        print(f"RQ4 observability triage failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api_client import summarize_calls
from .assembler import assemble_stage1_annotation
from .config import PipelineConfig, ProjectSource
from .context import (
    chunk_messages,
    evidence_messages,
    focused_inventory,
    merge_evidence_scans,
    messages_with_context,
    requirement_context,
    verification_context,
)
from .filtering import filter_short_requirements, merge_discarded_requirements
from .impact import (
    build_impact_cases,
    impact_case_filename,
    impact_decisions_to_patches,
    resolve_source_event_ids,
    source_ref_key,
)
from .patching import apply_audit_patches, apply_verification, has_valid_requirement_ids
from .preprocessing import message_index, preprocess_project
from .prompt_builder import build_single_pass_messages, build_stage_messages
from .schemas import (
    validate_consistency_audit,
    validate_cross_requirement_impact_audit,
    validate_event_extraction,
    validate_event_verification,
    validate_evidence_scan,
    validate_requirement_discovery,
)
from .storage import id_key, read_json, safe_filename, sha256_text, write_json
from .validation import (
    Stage1ValidationError,
    canonicalize_event_payload_fields,
    canonicalize_event_source_texts,
    validate_intermediate_events,
    validate_stage1_annotation,
)


class Stage1Pipeline:
    def __init__(
        self,
        api_client: Any,
        config: PipelineConfig,
        common_prompt: str,
        call_log_path: Path,
        single_pass_prompt: str | None = None,
        verification_addendum: str = "",
        impact_audit_addendum: str = "",
        value_removal_addendum: str = "",
    ) -> None:
        config.validate()
        self.api = api_client
        self.config = config
        self.common_prompt = common_prompt
        self.single_pass_prompt = single_pass_prompt
        self.verification_addendum = verification_addendum
        self.impact_audit_addendum = impact_audit_addendum
        self.value_removal_addendum = value_removal_addendum
        self.call_log_path = call_log_path

    async def run(self, project: ProjectSource) -> dict[str, Any]:
        project.run_dir.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc).isoformat()
        metadata_path = project.run_dir / "run_metadata.json"
        base_metadata = {
            "project_id": project.project_id,
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "annotation_mode": self.config.annotation_mode,
            "prompt_path": str(self.config.prompt_path),
            "prompt_version": self._prompt_version(),
            "prompt_sha256": sha256_text(self.common_prompt),
            "verification_addendum_path": (
                str(self.config.verification_addendum_path)
                if self.config.verification_addendum_path is not None
                else None
            ),
            "verification_addendum_sha256": sha256_text(self.verification_addendum),
            "impact_audit_addendum_path": (
                str(self.config.impact_audit_addendum_path)
                if self.config.impact_audit_addendum_path is not None
                else None
            ),
            "impact_audit_addendum_sha256": sha256_text(self.impact_audit_addendum),
            "value_removal_addendum_path": (
                str(self.config.value_removal_addendum_path)
                if self.config.value_removal_addendum_path is not None
                else None
            ),
            "value_removal_addendum_sha256": sha256_text(self.value_removal_addendum),
            "upgrade_existing_annotation_path": (
                str(self.config.upgrade_existing_annotation_path)
                if self.config.upgrade_existing_annotation_path is not None
                else None
            ),
            "started_at": started,
            "status": "RUNNING",
        }
        write_json(metadata_path, base_metadata)
        try:
            if self.config.upgrade_existing_annotation_path is not None:
                annotation, metrics = await self._run_incremental_upgrade(
                    project,
                    self.config.upgrade_existing_annotation_path,
                )
            elif self.config.annotation_mode == "single-pass":
                annotation = await self._run_single_pass(project)
                metrics = self._metrics(annotation, [], 0, {"edits": 0, "deletions": 0}, [])
            else:
                annotation, metrics = await self._run_multipass(project)
            project.output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(project.output_path, annotation)
            summary = summarize_calls(self.call_log_path, project.project_id)
            write_json(
                metadata_path,
                {
                    **base_metadata,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "DONE",
                    **summary,
                    "calibration": metrics,
                    "final_output": str(project.output_path),
                },
            )
            return annotation
        except Exception as exc:
            write_json(
                metadata_path,
                {
                    **base_metadata,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "FAILED",
                    "error": str(exc),
                    **summarize_calls(self.call_log_path, project.project_id),
                },
            )
            raise

    async def _run_multipass(self, project: ProjectSource) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized = preprocess_project(project)
        normalized_path = project.run_dir / "normalized_project.json"
        write_json(normalized_path, normalized)
        force_stages = self.config.expanded_force_stages()
        self._check_resume_signature(project, normalized, force_stages)

        evidence = await self._evidence_scan(project, normalized, "evidence_scan" in force_stages)
        inventory = await self._requirement_discovery(
            project,
            normalized,
            evidence,
            "requirement_discovery" in force_stages,
        )
        requirement_ids = {item["requirement_id"] for item in inventory["requirements"]}
        unknown_force = self.config.force_requirements.difference(requirement_ids)
        if unknown_force:
            raise ValueError(f"Unknown --force-requirement ID(s): {', '.join(sorted(unknown_force))}")

        force_target_without_stage = bool(self.config.force_requirements) and not self.config.force_stages
        event_force_ids = (
            set(self.config.force_requirements)
            if "event_extraction" in force_stages or force_target_without_stage
            else set()
        )

        events = await self._event_extraction_all(
            project,
            normalized,
            evidence,
            inventory,
            {},
            force_all="event_extraction" in force_stages and not self.config.force_requirements,
            force_ids=event_force_ids,
        )
        # Keep the complete atomic inventory through both global audits. A
        # two-Event Requirement may receive a third, cross-propagated Event and
        # become benchmark-eligible only after impact analysis.
        discarded_requirements: list[dict[str, Any]] = []
        self._write_discarded_requirements(project, discarded_requirements)
        extraction_findings = self._collect_event_extraction_findings(project, inventory)
        audit_input_hash = sha256_text(
            json.dumps(
                {
                    "inventory": inventory,
                    "events": events,
                    "event_extraction_findings": extraction_findings,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        audited_state_path = project.run_dir / "audited_state.json"
        audit_forced = "consistency_audit" in force_stages or force_target_without_stage
        audited_checkpoint = self._read_dict_checkpoint(audited_state_path)
        audited_checkpoint_has_valid_ids = (
            isinstance(audited_checkpoint, dict)
            and isinstance(audited_checkpoint.get("inventory"), dict)
            and has_valid_requirement_ids(audited_checkpoint["inventory"])
        )
        if (
            self.config.resume
            and isinstance(audited_checkpoint, dict)
            and audited_checkpoint.get("input_sha256") == audit_input_hash
            and audited_checkpoint_has_valid_ids
            and not audit_forced
        ):
            audited_state = audited_checkpoint
            inventory = audited_state["inventory"]
            events = audited_state["events"]
            human_review = audited_state.get("human_review", [])
            audit_patch_count = int(audited_state.get("audit_patch_count", 0))
            audit_affected: set[str] = set()
            print(f"[{project.project_id}] CONSISTENCY_AUDIT checkpoint reused", flush=True)
        else:
            if (
                self.config.resume
                and isinstance(audited_checkpoint, dict)
                and audited_checkpoint.get("input_sha256") == audit_input_hash
                and not audited_checkpoint_has_valid_ids
                and not audit_forced
            ):
                print(
                    f"[{project.project_id}] CONSISTENCY_AUDIT checkpoint ignored: "
                    "Requirement IDs are empty or duplicated",
                    flush=True,
                )
            inventory, events, human_review, audit_patch_count, audit_affected = await self._audit_until_stable(
                project, normalized, evidence, inventory, events, force=audit_forced
            )
            write_json(
                audited_state_path,
                {
                    "input_sha256": audit_input_hash,
                    "inventory": inventory,
                    "events": events,
                    "human_review": human_review,
                    "audit_patch_count": audit_patch_count,
                },
            )

        for requirement_events in events.values():
            canonicalize_event_payload_fields(requirement_events)

        impact_input_hash = sha256_text(
            json.dumps({"inventory": inventory, "events": events}, ensure_ascii=False, sort_keys=True)
        )
        impact_state_path = project.run_dir / "impact_audited_state.json"
        impact_forced = "cross_requirement_impact_audit" in force_stages or force_target_without_stage
        impact_checkpoint = self._read_dict_checkpoint(impact_state_path)
        impact_checkpoint_valid = False
        if (
            self.config.resume
            and isinstance(impact_checkpoint, dict)
            and impact_checkpoint.get("input_sha256") == impact_input_hash
            and not impact_forced
        ):
            try:
                checkpoint_events = impact_checkpoint.get("events")
                if not isinstance(checkpoint_events, dict):
                    raise ValueError("impact checkpoint events must be an object")
                checkpoint_events = self._sort_events(checkpoint_events, normalized)
                for requirement_events in checkpoint_events.values():
                    canonicalize_event_payload_fields(requirement_events)
                    canonicalize_event_source_texts(requirement_events, normalized)
                    validate_intermediate_events(requirement_events, normalized)
                events = checkpoint_events
                impact_checkpoint_valid = True
            except (TypeError, ValueError) as exc:
                print(f"[checkpoint invalid] {impact_state_path}: {exc}; rerunning", flush=True)

        if impact_checkpoint_valid:
            impact_review = impact_checkpoint.get("human_review", [])
            impact_patch_count = int(impact_checkpoint.get("applied_patch_count", 0))
            impact_decision_count = int(impact_checkpoint.get("decision_count", 0))
            impact_affected = set(impact_checkpoint.get("affected_requirement_ids", []))
            impact_report = impact_checkpoint.get("report", {})
            print(f"[{project.project_id}] CROSS_REQUIREMENT_IMPACT_AUDIT checkpoint reused", flush=True)
        else:
            (
                events,
                impact_review,
                impact_patch_count,
                impact_decision_count,
                impact_affected,
                impact_report,
            ) = await self._cross_requirement_impact_until_stable(
                project,
                normalized,
                inventory,
                events,
                force=impact_forced,
                phase="pre_verification",
            )
            write_json(
                impact_state_path,
                {
                    "input_sha256": impact_input_hash,
                    "events": events,
                    "human_review": impact_review,
                    "applied_patch_count": impact_patch_count,
                    "decision_count": impact_decision_count,
                    "affected_requirement_ids": sorted(impact_affected),
                    "report": impact_report,
                },
            )
        human_review.extend(impact_review)

        inventory, events, audit_discards = filter_short_requirements(
            inventory,
            events,
            self.config.min_requirement_events,
            "CROSS_REQUIREMENT_IMPACT_AUDIT",
        )
        discarded_requirements = merge_discarded_requirements(discarded_requirements, audit_discards)
        self._write_discarded_requirements(project, discarded_requirements)

        verification_force_ids = set(self.config.force_requirements).union(audit_affected, impact_affected)
        target_only_verification = bool(self.config.force_requirements) and self.config.force_stages == {
            "event_verification"
        }
        verified_events, verifier_counts, verifier_review = await self._verify_all(
            project,
            normalized,
            inventory,
            events,
            audit_review=human_review,
            force_all="event_verification" in force_stages and not self.config.force_requirements,
            force_ids=verification_force_ids,
            target_only=target_only_verification,
        )
        if self._impact_material_signature(verified_events) != self._impact_material_signature(events):
            (
                verified_events,
                post_impact_review,
                post_impact_patch_count,
                post_impact_decision_count,
                post_impact_affected,
                post_impact_report,
            ) = await self._cross_requirement_impact_until_stable(
                project,
                normalized,
                inventory,
                verified_events,
                force=impact_forced,
                phase="post_verification",
            )
            human_review.extend(post_impact_review)
            impact_patch_count += post_impact_patch_count
            impact_decision_count += post_impact_decision_count
            impact_affected.update(post_impact_affected)
            impact_report = self._merge_impact_reports(impact_report, post_impact_report)
            if post_impact_patch_count:
                post_impact_signature = self._impact_material_signature(verified_events)
                reverified_events, reverify_counts, reverify_review = await self._verify_all(
                    project,
                    normalized,
                    inventory,
                    verified_events,
                    audit_review=human_review,
                    force_all=False,
                    force_ids=post_impact_affected,
                    target_only=False,
                )
                verified_events = reverified_events
                verifier_counts["edits"] += reverify_counts["edits"]
                verifier_counts["deletions"] += reverify_counts["deletions"]
                verifier_review.extend(reverify_review)
                if self._impact_material_signature(verified_events) != post_impact_signature:
                    human_review.append(
                        {
                            "source": "FINAL_GLOBAL_CONSISTENCY_SCAN",
                            "reason": (
                                "Re-verification changed material MODIFY/REMOVE semantics after the final "
                                "cross-Requirement impact pass; inspect the affected lifecycle before Gold acceptance."
                            ),
                            "affected_requirement_ids": sorted(post_impact_affected),
                        }
                    )
        inventory, verified_events, verifier_discards = filter_short_requirements(
            inventory,
            verified_events,
            self.config.min_requirement_events,
            "EVENT_VERIFICATION",
        )
        discarded_requirements = merge_discarded_requirements(discarded_requirements, verifier_discards)
        self._write_discarded_requirements(project, discarded_requirements)
        human_review.extend(verifier_review)
        for unresolved in inventory.get("unresolved_candidates", []):
            human_review.append({"source": "REQUIREMENT_DISCOVERY", "unresolved_candidate": unresolved})
        for requirement in inventory.get("requirements", []):
            if requirement.get("confidence") == "LOW":
                human_review.append(
                    {
                        "source": "REQUIREMENT_DISCOVERY",
                        "requirement_id": requirement.get("requirement_id"),
                        "reason": "Low-confidence Requirement inventory item",
                    }
                )
        write_json(project.run_dir / "human_review.json", {"items": human_review})

        annotation = assemble_stage1_annotation(normalized, inventory, verified_events)
        validate_stage1_annotation(annotation, normalized)
        impact_report = resolve_source_event_ids(impact_report, annotation)
        write_json(project.run_dir / "cross_requirement_impact_audit.json", impact_report)
        write_json(project.run_dir / "final" / project.output_path.name, annotation)
        metrics = self._metrics(
            annotation,
            human_review,
            audit_patch_count,
            verifier_counts,
            discarded_requirements,
            impact_patch_count=impact_patch_count,
            impact_decision_count=impact_decision_count,
        )
        return annotation, metrics

    async def _run_incremental_upgrade(
        self,
        project: ProjectSource,
        existing_annotation_path: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Upgrade an existing Stage 1 annotation without rerunning discovery/extraction."""
        normalized = preprocess_project(project)
        write_json(project.run_dir / "normalized_project.json", normalized)
        existing_annotation = read_json(existing_annotation_path)
        inventory, events = self._provisional_state_from_annotation(
            existing_annotation,
            normalized,
            project.project_id,
        )
        write_json(
            project.run_dir / "incremental_upgrade_input.json",
            {
                "source_annotation": str(existing_annotation_path),
                "source_annotation_version": existing_annotation.get("annotation_version"),
                "source_sha256": sha256_text(
                    json.dumps(existing_annotation, ensure_ascii=False, sort_keys=True)
                ),
                "inventory": inventory,
                "events": events,
            },
        )

        (
            events,
            value_review,
            value_patch_count,
            value_affected,
            value_report,
        ) = await self._audit_existing_value_removals(
            project,
            normalized,
            inventory,
            events,
            force=not self.config.resume,
        )

        (
            events,
            impact_review,
            impact_patch_count,
            impact_decision_count,
            impact_affected,
            impact_report,
        ) = await self._cross_requirement_impact_until_stable(
            project,
            normalized,
            inventory,
            events,
            force=not self.config.resume,
            phase="incremental_upgrade",
        )

        human_review = value_review + impact_review
        affected = set(value_affected).union(impact_affected)
        before_verification_signature = self._impact_material_signature(events)
        verified_events, verifier_counts, verifier_review = await self._verify_all(
            project,
            normalized,
            inventory,
            events,
            audit_review=human_review,
            force_all=False,
            force_ids=affected,
            target_only=False,
            only_ids=affected,
        )
        human_review.extend(verifier_review)

        if self._impact_material_signature(verified_events) != before_verification_signature:
            (
                verified_events,
                post_review,
                post_patch_count,
                post_decision_count,
                post_affected,
                post_report,
            ) = await self._cross_requirement_impact_until_stable(
                project,
                normalized,
                inventory,
                verified_events,
                force=not self.config.resume,
                phase="incremental_post_verification",
            )
            human_review.extend(post_review)
            impact_patch_count += post_patch_count
            impact_decision_count += post_decision_count
            impact_affected.update(post_affected)
            impact_report = self._merge_impact_reports(impact_report, post_report)
            if post_patch_count:
                verified_events, reverify_counts, reverify_review = await self._verify_all(
                    project,
                    normalized,
                    inventory,
                    verified_events,
                    audit_review=human_review,
                    force_all=False,
                    force_ids=post_affected,
                    target_only=False,
                    only_ids=post_affected,
                )
                verifier_counts["edits"] += reverify_counts["edits"]
                verifier_counts["deletions"] += reverify_counts["deletions"]
                human_review.extend(reverify_review)

        inventory, verified_events, discarded_requirements = filter_short_requirements(
            inventory,
            verified_events,
            self.config.min_requirement_events,
            "INCREMENTAL_V06_UPGRADE",
        )
        self._write_discarded_requirements(project, discarded_requirements)
        write_json(project.run_dir / "verified_events.json", verified_events)
        write_json(project.run_dir / "value_removal_audit.json", value_report)
        write_json(project.run_dir / "human_review.json", {"items": human_review})

        annotation = assemble_stage1_annotation(normalized, inventory, verified_events)
        validate_stage1_annotation(annotation, normalized)
        impact_report = resolve_source_event_ids(impact_report, annotation)
        write_json(project.run_dir / "cross_requirement_impact_audit.json", impact_report)
        write_json(project.run_dir / "final" / project.output_path.name, annotation)
        metrics = self._metrics(
            annotation,
            human_review,
            value_patch_count,
            verifier_counts,
            discarded_requirements,
            impact_patch_count=impact_patch_count,
            impact_decision_count=impact_decision_count,
        )
        metrics["incremental_upgrade"] = {
            "source_annotation": str(existing_annotation_path),
            "value_removal_affected_requirements": sorted(value_affected),
            "cross_impact_affected_requirements": sorted(impact_affected),
            "verification_scope": sorted(affected.union(impact_affected)),
        }
        return annotation, metrics

    @staticmethod
    def _provisional_state_from_annotation(
        annotation: dict[str, Any],
        normalized: dict[str, Any],
        project_id: str,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        if not isinstance(annotation, dict):
            raise ValueError("Existing annotation must be a JSON object")
        if annotation.get("benchmark") != "ReqMemBench":
            raise ValueError("Existing annotation benchmark must equal ReqMemBench")
        if annotation.get("annotation_version") not in {"v0.5", "v0.6"}:
            raise ValueError("Incremental upgrade accepts only annotation v0.5 or v0.6")
        if str(annotation.get("project", {}).get("project_id")) != str(project_id):
            raise ValueError("Existing annotation project_id does not match --project-id")
        requirements = annotation.get("requirements")
        if not isinstance(requirements, list):
            raise ValueError("Existing annotation requirements must be an array")

        inventory_requirements: list[dict[str, Any]] = []
        events: dict[str, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ValueError("Existing annotation contains an invalid Requirement")
            requirement_id = requirement.get("requirement_id")
            if not isinstance(requirement_id, str) or not requirement_id or requirement_id in seen:
                raise ValueError("Existing annotation Requirement IDs must be non-empty and unique")
            seen.add(requirement_id)
            inventory_requirements.append(
                {
                    "requirement_id": requirement_id,
                    "title": requirement.get("title"),
                    "family_id": requirement.get("family_id"),
                }
            )
            provisional_events: list[dict[str, Any]] = []
            for event in requirement.get("events", []):
                if not isinstance(event, dict):
                    raise ValueError(f"{requirement_id} contains an invalid Event")
                provisional_events.append(
                    {
                        "source_message": deepcopy(event.get("source_message")),
                        "supporting_message_ids": [],
                        "event_type": event.get("event_type"),
                        "value_updates": deepcopy(event.get("value_updates")),
                        "value_removals": deepcopy(event.get("value_removals")),
                        "scope_updates": deepcopy(event.get("scope_updates")),
                        "ambiguity": deepcopy(event.get("ambiguity")),
                        "execution": deepcopy(event.get("execution")),
                    }
                )
            canonicalize_event_payload_fields(provisional_events)
            canonicalize_event_source_texts(provisional_events, normalized)
            validate_intermediate_events(provisional_events, normalized)
            events[requirement_id] = provisional_events

        project = annotation.get("project", {})
        inventory = {
            "sessions": deepcopy(project.get("sessions", [])),
            "requirement_families": deepcopy(annotation.get("requirement_families", [])),
            "requirements": inventory_requirements,
            "unresolved_candidates": [],
        }
        if not has_valid_requirement_ids(inventory):
            raise ValueError("Existing annotation Requirement IDs are invalid")
        return inventory, events

    async def _audit_existing_value_removals(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        inventory: dict[str, Any],
        events: dict[str, list[dict[str, Any]]],
        *,
        force: bool,
    ) -> tuple[
        dict[str, list[dict[str, Any]]],
        list[dict[str, Any]],
        int,
        set[str],
        dict[str, Any],
    ]:
        modify_ids = {
            requirement_id
            for requirement_id, requirement_events in events.items()
            if any(event.get("event_type") == "MODIFY" for event in requirement_events)
        }
        if not modify_ids:
            report = {
                "run_mode": "CONSISTENCY_AUDIT",
                "audit_scope": "VALUE_REMOVALS_ONLY",
                "patches": [],
                "affected_requirement_ids": [],
            }
            return events, [], 0, set(), report

        current_events = {
            requirement_id: deepcopy(events[requirement_id])
            for requirement_id in sorted(modify_ids)
        }
        current_inventory = {
            "requirement_families": deepcopy(inventory.get("requirement_families", [])),
            "requirements": [
                deepcopy(requirement)
                for requirement in inventory.get("requirements", [])
                if requirement.get("requirement_id") in modify_ids
            ],
        }
        path = project.run_dir / "incremental_value_removal_audit.json"
        meta_path = path.with_suffix(".meta.json")
        input_hash = sha256_text(
            json.dumps(
                {
                    "inventory": current_inventory,
                    "events": current_events,
                    "addendum_sha256": sha256_text(self.value_removal_addendum),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        def validator(value: dict[str, Any]) -> None:
            validate_consistency_audit(value)
            for patch in value.get("patches", []):
                operation = patch.get("operation")
                if operation not in {"EDIT_EVENT", "HUMAN_REVIEW"}:
                    raise ValueError("Value-removal audit may only return EDIT_EVENT or HUMAN_REVIEW")
                if operation == "HUMAN_REVIEW":
                    continue
                targets = patch.get("targets", {})
                if targets.get("requirement_id") not in modify_ids:
                    raise ValueError("Value-removal audit targeted a Requirement outside its input scope")
                locator = targets.get("event_locator", {})
                if locator.get("event_type") != "MODIFY":
                    raise ValueError("Value-removal audit may edit only MODIFY Events")
                replacement = patch.get("replacement")
                if not isinstance(replacement, dict) or replacement.get("event_type") != "MODIFY":
                    raise ValueError("Value-removal audit EDIT_EVENT requires a MODIFY replacement")
                if "value_removals" not in replacement:
                    raise ValueError("Value-removal audit replacement must include value_removals")
            trial = apply_audit_patches(inventory, events, value.get("patches", []))
            trial_events = self._sort_events(trial.events, normalized)
            for requirement_events in trial_events.values():
                canonicalize_event_payload_fields(requirement_events)
                canonicalize_event_source_texts(requirement_events, normalized)
                validate_intermediate_events(requirement_events, normalized)

        checkpoint = self._load_valid_checkpoint(
            path,
            force or not self._checkpoint_hash_matches(meta_path, input_hash),
            validator,
        )
        if checkpoint is None:
            print(
                f"[{project.project_id}] VALUE_REMOVAL_AUDIT started: "
                f"{len(modify_ids)} Requirement(s) with MODIFY Events",
                flush=True,
            )
            checkpoint = await self.api.call(
                project_id=project.project_id,
                run_mode="CONSISTENCY_AUDIT",
                target_requirement="VALUE_REMOVALS_ONLY",
                messages=build_stage_messages(
                    self.common_prompt,
                    "CONSISTENCY_AUDIT",
                    {
                        "PROJECT_METADATA": self._project_metadata(normalized),
                        "CURRENT_INVENTORY": current_inventory,
                        "CURRENT_EVENTS": current_events,
                    },
                    stage_instructions=self.value_removal_addendum,
                ),
                validator=validator,
            )
            write_json(path, checkpoint)
            write_json(meta_path, {"input_sha256": input_hash})

        applied = apply_audit_patches(inventory, events, checkpoint.get("patches", []))
        updated_events = self._sort_events(applied.events, normalized)
        for requirement_events in updated_events.values():
            canonicalize_event_payload_fields(requirement_events)
            canonicalize_event_source_texts(requirement_events, normalized)
            validate_intermediate_events(requirement_events, normalized)
        report = {
            "run_mode": "CONSISTENCY_AUDIT",
            "audit_scope": "VALUE_REMOVALS_ONLY",
            "modify_requirement_ids": sorted(modify_ids),
            "patches": deepcopy(checkpoint.get("patches", [])),
            "applied_patch_count": applied.applied_count,
            "affected_requirement_ids": sorted(applied.affected_requirements),
        }
        print(
            f"[{project.project_id}] VALUE_REMOVAL_AUDIT done: "
            f"{len(checkpoint.get('patches', []))} patch(es), {applied.applied_count} applied",
            flush=True,
        )
        return (
            updated_events,
            applied.human_review,
            applied.applied_count,
            applied.affected_requirements,
            report,
        )

    async def _run_single_pass(self, project: ProjectSource) -> dict[str, Any]:
        normalized = preprocess_project(project)
        write_json(project.run_dir / "normalized_project.json", normalized)
        prompt = self.single_pass_prompt or self.common_prompt
        print(f"[{project.project_id}] SINGLE_PASS started", flush=True)
        raw = await self.api.call(
            project_id=project.project_id,
            run_mode="SINGLE_PASS",
            messages=build_single_pass_messages(prompt, normalized),
        )
        inventory = {
            "sessions": raw.get("project", {}).get("sessions", []),
            "requirement_families": raw.get("requirement_families", []),
            "requirements": [
                {
                    "requirement_id": item.get("requirement_id"),
                    "title": item.get("title"),
                    "family_id": item.get("family_id"),
                }
                for item in raw.get("requirements", [])
            ],
        }
        events = {item.get("requirement_id"): item.get("events", []) for item in raw.get("requirements", [])}
        for requirement_events in events.values():
            canonicalize_event_payload_fields(requirement_events)
        annotation = assemble_stage1_annotation(normalized, inventory, events)
        validate_stage1_annotation(annotation, normalized)
        write_json(project.run_dir / "final" / project.output_path.name, annotation)
        return annotation

    def _check_resume_signature(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        force_stages: set[str],
    ) -> None:
        path = project.run_dir / "pipeline_config.json"
        signature = {
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "prompt_sha256": sha256_text(self.common_prompt),
            "normalized_sha256": sha256_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True)),
            "evidence_chunk_size": self.config.evidence_chunk_size,
            "evidence_chunk_overlap": self.config.evidence_chunk_overlap,
            "context_window": self.config.context_window,
            "event_context_mode": self.config.event_context_mode,
            "max_requirement_context_messages": self.config.max_requirement_context_messages,
            "min_requirement_events": self.config.min_requirement_events,
            "max_audit_rounds": self.config.max_audit_rounds,
            "max_impact_audit_rounds": self.config.max_impact_audit_rounds,
            "max_impact_candidates_per_event": self.config.max_impact_candidates_per_event,
            "impact_audit_addendum_sha256": sha256_text(self.impact_audit_addendum),
        }
        if self.config.resume and path.is_file() and "evidence_scan" not in force_stages:
            existing = read_json(path)
            comparable_existing = deepcopy(existing)
            comparable_signature = deepcopy(signature)
            if "cross_requirement_impact_audit" in force_stages:
                for key in (
                    "impact_audit_addendum_sha256",
                    "max_impact_audit_rounds",
                    "max_impact_candidates_per_event",
                ):
                    comparable_existing.pop(key, None)
                    comparable_signature.pop(key, None)
            if "consistency_audit" in force_stages:
                comparable_existing.pop("max_audit_rounds", None)
                comparable_signature.pop("max_audit_rounds", None)
            if not self._resume_signature_compatible(comparable_existing, comparable_signature):
                raise ValueError(
                    "Checkpoint configuration/source changed. Use --no-resume for a clean semantic rerun, "
                    "or --force-stage evidence_scan to invalidate all downstream checkpoints."
                )
        write_json(path, signature)

    async def _evidence_scan(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        force: bool,
    ) -> dict[str, Any]:
        chunks = chunk_messages(
            normalized["messages"], self.config.evidence_chunk_size, self.config.evidence_chunk_overlap
        )
        valid_ids = {id_key(message["message_id"]) for message in normalized["messages"]}
        results: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            path = project.run_dir / "evidence_chunks" / f"chunk_{index:04d}.json"
            checkpoint = self._load_valid_checkpoint(
                path,
                force,
                lambda value: validate_evidence_scan(value, valid_ids),
            )
            if checkpoint is not None:
                results.append(checkpoint)
                print(f"[{project.project_id}] EVIDENCE_SCAN {index}/{len(chunks)} checkpoint reused", flush=True)
                continue
            print(f"[{project.project_id}] EVIDENCE_SCAN {index}/{len(chunks)} started", flush=True)
            result = await self.api.call(
                project_id=project.project_id,
                run_mode="EVIDENCE_SCAN",
                messages=build_stage_messages(
                    self.common_prompt,
                    "EVIDENCE_SCAN",
                    {
                        "PROJECT_METADATA": self._project_metadata(normalized),
                        "MESSAGES": chunk,
                    },
                ),
                validator=lambda value: validate_evidence_scan(value, valid_ids),
            )
            write_json(path, result)
            results.append(result)
            print(
                f"[{project.project_id}] EVIDENCE_SCAN {index}/{len(chunks)} done: "
                f"{len(result['candidates'])} candidates",
                flush=True,
            )
        merged = merge_evidence_scans(results)
        write_json(project.run_dir / "evidence_scan.json", merged)
        return merged

    async def _requirement_discovery(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        evidence: dict[str, Any],
        force: bool,
    ) -> dict[str, Any]:
        path = project.run_dir / "requirement_discovery.json"
        valid_ids = {id_key(message["message_id"]) for message in normalized["messages"]}

        def validator(value: dict[str, Any]) -> None:
            validate_requirement_discovery(value)
            for requirement in value.get("requirements", []):
                if any(id_key(message_id) not in valid_ids for message_id in requirement.get("anchor_message_ids", [])):
                    raise ValueError("Requirement discovery returned an unknown anchor_message_id")

        checkpoint = self._load_valid_checkpoint(path, force, validator)
        if checkpoint is not None:
            print(f"[{project.project_id}] REQUIREMENT_DISCOVERY checkpoint reused", flush=True)
            return checkpoint
        selected = evidence_messages(normalized["messages"], evidence, self.config.context_window)
        print(f"[{project.project_id}] REQUIREMENT_DISCOVERY started", flush=True)
        result = await self.api.call(
            project_id=project.project_id,
            run_mode="REQUIREMENT_DISCOVERY",
            messages=build_stage_messages(
                self.common_prompt,
                "REQUIREMENT_DISCOVERY",
                {
                    "PROJECT_METADATA": self._project_metadata(normalized),
                    "EVIDENCE_INDEX": evidence,
                    "MESSAGES": selected,
                },
            ),
            validator=validator,
        )
        write_json(path, result)
        print(
            f"[{project.project_id}] REQUIREMENT_DISCOVERY done: "
            f"{len(result['requirements'])} requirements, {len(result['requirement_families'])} families",
            flush=True,
        )
        return result

    async def _event_extraction_all(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        evidence: dict[str, Any],
        inventory: dict[str, Any],
        base_events: dict[str, list[dict[str, Any]]],
        *,
        force_all: bool,
        force_ids: set[str],
        only_ids: set[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        requirements = [
            item for item in inventory.get("requirements", []) if only_ids is None or item["requirement_id"] in only_ids
        ]
        output = deepcopy(base_events)
        completed = 0

        async def extract(requirement: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            nonlocal completed
            requirement_id = requirement["requirement_id"]
            path = project.run_dir / "events" / f"{safe_filename(requirement_id)}.json"

            def validator(value: dict[str, Any]) -> None:
                validate_event_extraction(value, requirement_id)
                canonicalize_event_payload_fields(value["events"])
                corrections = canonicalize_event_source_texts(value["events"], normalized)
                if corrections:
                    print(
                        f"[{project.project_id}] EVENT_EXTRACTION {requirement_id}: "
                        f"canonicalized {corrections} source text value(s)",
                        flush=True,
                    )
                validate_intermediate_events(value["events"], normalized)

            force = force_all or requirement_id in force_ids or only_ids is not None
            checkpoint = self._load_valid_checkpoint(path, force, validator)
            if checkpoint is None:
                local_context, relevant_evidence = requirement_context(
                    normalized,
                    evidence,
                    inventory,
                    requirement,
                    self.config.event_context_mode,
                    self.config.context_window,
                    self.config.max_requirement_context_messages,
                )
                print(f"[{project.project_id}] EVENT_EXTRACTION {requirement_id} started", flush=True)
                checkpoint = await self.api.call(
                    project_id=project.project_id,
                    run_mode="EVENT_EXTRACTION",
                    target_requirement=requirement_id,
                    messages=build_stage_messages(
                        self.common_prompt,
                        "EVENT_EXTRACTION",
                        {
                            "PROJECT_METADATA": self._project_metadata(normalized),
                            "CURRENT_INVENTORY": focused_inventory(
                                inventory,
                                requirement,
                                include_family_siblings=True,
                            ),
                            "TARGET_REQUIREMENT": requirement,
                            "EVIDENCE_INDEX": {"candidates": relevant_evidence},
                            "LOCAL_CONTEXT": local_context,
                        },
                    ),
                    validator=validator,
                )
                write_json(path, checkpoint)
            completed += 1
            print(
                f"[{project.project_id}] EVENT_EXTRACTION {completed}/{len(requirements)} "
                f"{requirement_id} done: {len(checkpoint['events'])} events",
                flush=True,
            )
            return requirement_id, checkpoint["events"]

        pairs = await asyncio.gather(*(extract(requirement) for requirement in requirements))
        output.update(dict(pairs))
        current_ids = {item["requirement_id"] for item in inventory.get("requirements", [])}
        return {requirement_id: events for requirement_id, events in output.items() if requirement_id in current_ids}

    async def _audit_until_stable(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        evidence: dict[str, Any],
        inventory: dict[str, Any],
        events: dict[str, list[dict[str, Any]]],
        *,
        force: bool,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]], int, set[str]]:
        human_review: list[dict[str, Any]] = []
        patch_count = 0
        affected_all: set[str] = set()
        for round_number in range(1, self.config.max_audit_rounds + 1):
            path = project.run_dir / f"consistency_audit_round_{round_number}.json"
            meta_path = path.with_suffix(".meta.json")
            extraction_findings = self._collect_event_extraction_findings(project, inventory)
            input_hash = sha256_text(
                json.dumps(
                    {
                        "inventory": inventory,
                        "events": events,
                        "event_extraction_findings": extraction_findings,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

            def audit_validator(value: dict[str, Any]) -> None:
                validate_consistency_audit(value)
                trial = apply_audit_patches(inventory, events, value.get("patches", []))
                if not has_valid_requirement_ids(trial.inventory):
                    raise ValueError("Audit patches produced empty or duplicate Requirement IDs")
                trial_events = self._sort_events(trial.events, normalized)
                for requirement_events in trial_events.values():
                    canonicalize_event_payload_fields(requirement_events)
                    canonicalize_event_source_texts(requirement_events, normalized)
                    validate_intermediate_events(requirement_events, normalized)

            checkpoint = self._load_valid_checkpoint(
                path,
                force or not self._checkpoint_hash_matches(meta_path, input_hash),
                audit_validator,
            )
            if checkpoint is None:
                print(
                    f"[{project.project_id}] CONSISTENCY_AUDIT round {round_number}/"
                    f"{self.config.max_audit_rounds} started",
                    flush=True,
                )
                checkpoint = await self.api.call(
                    project_id=project.project_id,
                    run_mode="CONSISTENCY_AUDIT",
                    messages=build_stage_messages(
                        self.common_prompt,
                        "CONSISTENCY_AUDIT",
                        {
                            "PROJECT_METADATA": self._project_metadata(normalized),
                            "CURRENT_INVENTORY": inventory,
                            "CURRENT_EVENTS": events,
                            "EVIDENCE_INDEX": {
                                "event_extraction_findings": extraction_findings,
                            },
                        },
                    ),
                    validator=audit_validator,
                )
                write_json(path, checkpoint)
                write_json(meta_path, {"input_sha256": input_hash})
            patch_count += len(checkpoint.get("patches", []))
            applied = apply_audit_patches(inventory, events, checkpoint.get("patches", []))
            inventory, events = applied.inventory, applied.events
            for requirement_events in events.values():
                canonicalize_event_payload_fields(requirement_events)
                canonicalize_event_source_texts(requirement_events, normalized)
            human_review.extend(applied.human_review)
            affected_all.update(applied.affected_requirements)
            print(
                f"[{project.project_id}] CONSISTENCY_AUDIT round {round_number} done: "
                f"{len(checkpoint.get('patches', []))} patches, {applied.applied_count} applied",
                flush=True,
            )
            if not applied.boundary_changed:
                break
            events = await self._event_extraction_all(
                project,
                normalized,
                evidence,
                inventory,
                events,
                force_all=False,
                force_ids=applied.affected_requirements,
                only_ids=applied.affected_requirements,
            )
            if round_number == self.config.max_audit_rounds:
                human_review.append(
                    {
                        "source": "CONSISTENCY_AUDIT",
                        "reason": "Requirement boundaries still changed in the final configured audit round.",
                        "affected_requirement_ids": sorted(applied.affected_requirements),
                    }
                )
        events = self._sort_events(events, normalized)
        for requirement_events in events.values():
            canonicalize_event_payload_fields(requirement_events)
            validate_intermediate_events(requirement_events, normalized)
        self._collect_event_extraction_findings(project, inventory)
        return inventory, events, human_review, patch_count, affected_all

    async def _cross_requirement_impact_until_stable(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        inventory: dict[str, Any],
        events: dict[str, list[dict[str, Any]]],
        *,
        force: bool,
        phase: str,
    ) -> tuple[
        dict[str, list[dict[str, Any]]],
        list[dict[str, Any]],
        int,
        int,
        set[str],
        dict[str, Any],
    ]:
        human_review: list[dict[str, Any]] = []
        applied_patch_count = 0
        decision_count = 0
        affected_all: set[str] = set()
        processed_pairs: set[tuple[tuple[str, str, str, int], str]] = set()
        records: list[dict[str, Any]] = []
        round_summaries: list[dict[str, Any]] = []

        for round_number in range(1, self.config.max_impact_audit_rounds + 1):
            all_cases = build_impact_cases(
                inventory,
                events,
                normalized,
                max_candidates_per_event=self.config.max_impact_candidates_per_event,
            )
            cases: list[dict[str, Any]] = []
            for case in all_cases:
                source_key = source_ref_key(case["source_event_ref"])
                candidates = [
                    candidate
                    for candidate in case["candidates"]
                    if (source_key, candidate["candidate_requirement_id"]) not in processed_pairs
                ]
                if candidates:
                    filtered_case = deepcopy(case)
                    filtered_case["candidates"] = candidates
                    cases.append(filtered_case)
            if not cases:
                round_summaries.append(
                    {
                        "round": round_number,
                        "source_case_count": 0,
                        "candidate_pair_count": 0,
                        "decision_count": 0,
                        "applied_patch_count": 0,
                    }
                )
                break

            async def audit_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                source_ref = case["source_event_ref"]
                candidate_ids = {
                    candidate["candidate_requirement_id"] for candidate in case["candidates"]
                }
                path = (
                    project.run_dir
                    / "impact_audit"
                    / phase
                    / f"round_{round_number:02d}"
                    / impact_case_filename(case)
                )
                meta_path = path.with_suffix(".meta.json")
                input_hash = sha256_text(json.dumps(case, ensure_ascii=False, sort_keys=True))

                def validator(value: dict[str, Any]) -> None:
                    validate_cross_requirement_impact_audit(value, source_ref, candidate_ids)
                    for decision in value.get("decisions", []):
                        if decision.get("decision") not in {"ADD_EVENT", "EDIT_EVENT"}:
                            continue
                        proposed = decision.get("new_event", {})
                        proposed_source = proposed.get("source_message", {})
                        if id_key(proposed_source.get("message_id")) != id_key(source_ref.get("message_id")):
                            raise ValueError("Propagated new_event must cite the source impact message")
                        source_message = case["source_event"].get("source_message", {})
                        if (
                            proposed_source.get("speaker") != source_message.get("speaker")
                            or proposed_source.get("text") != source_message.get("text")
                        ):
                            raise ValueError("Propagated new_event must copy the exact source impact message")
                        if decision.get("decision") == "EDIT_EVENT" and id_key(
                            (decision.get("event_locator") or {}).get("message_id")
                        ) != id_key(source_ref.get("message_id")):
                            raise ValueError("EDIT_EVENT must target the candidate's same-source-message MODIFY")
                    patches, patch_review = impact_decisions_to_patches(case, value, events)
                    if any(item.get("application_error") for item in patch_review):
                        raise ValueError("Impact decisions contain an inapplicable HIGH-confidence patch")
                    trial = apply_audit_patches(inventory, events, patches)
                    trial_events = self._sort_events(trial.events, normalized)
                    for requirement_events in trial_events.values():
                        canonicalize_event_payload_fields(requirement_events)
                        canonicalize_event_source_texts(requirement_events, normalized)
                        validate_intermediate_events(requirement_events, normalized)

                checkpoint = self._load_valid_checkpoint(
                    path,
                    force or not self._checkpoint_hash_matches(meta_path, input_hash),
                    validator,
                )
                if checkpoint is None:
                    print(
                        f"[{project.project_id}] CROSS_REQUIREMENT_IMPACT_AUDIT "
                        f"round {round_number} {source_ref['requirement_id']}/"
                        f"{source_ref['message_id']} started: {len(candidate_ids)} candidate(s)",
                        flush=True,
                    )
                    checkpoint = await self.api.call(
                        project_id=project.project_id,
                        run_mode="CROSS_REQUIREMENT_IMPACT_AUDIT",
                        target_requirement=str(source_ref["requirement_id"]),
                        messages=build_stage_messages(
                            self.common_prompt,
                            "CROSS_REQUIREMENT_IMPACT_AUDIT",
                            {
                                "PROJECT_METADATA": self._project_metadata(normalized),
                                "IMPACT_SOURCE": {
                                    key: value
                                    for key, value in case.items()
                                    if key != "candidates"
                                },
                                "IMPACT_CANDIDATES": case["candidates"],
                                "LOCAL_CONTEXT": messages_with_context(
                                    normalized["messages"],
                                    [source_ref["message_id"]],
                                    self.config.context_window,
                                ),
                            },
                            stage_instructions=self.impact_audit_addendum,
                        ),
                        validator=validator,
                    )
                    write_json(path, checkpoint)
                    write_json(meta_path, {"input_sha256": input_hash})
                return case, checkpoint

            audited_cases = await asyncio.gather(*(audit_case(case) for case in cases))
            round_applied = 0
            round_decisions = 0
            for case, audit in audited_cases:
                source_key = source_ref_key(case["source_event_ref"])
                for candidate in case["candidates"]:
                    processed_pairs.add((source_key, candidate["candidate_requirement_id"]))
                decisions = audit.get("decisions", [])
                round_decisions += len(decisions)
                decision_count += len(decisions)
                patches, local_review = impact_decisions_to_patches(case, audit, events)
                human_review.extend(local_review)
                applied = apply_audit_patches(inventory, events, patches)
                trial_events = self._sort_events(applied.events, normalized)
                try:
                    for requirement_events in trial_events.values():
                        canonicalize_event_payload_fields(requirement_events)
                        canonicalize_event_source_texts(requirement_events, normalized)
                        validate_intermediate_events(requirement_events, normalized)
                except (Stage1ValidationError, TypeError, ValueError) as exc:
                    for patch in patches:
                        failed_patch = deepcopy(patch)
                        failed_patch["source"] = "CROSS_REQUIREMENT_IMPACT_AUDIT"
                        failed_patch["application_error"] = str(exc)
                        human_review.append(failed_patch)
                    records.append(
                        {
                            "round": round_number,
                            "phase": phase,
                            "source_event_ref": deepcopy(case["source_event_ref"]),
                            "candidate_requirement_ids": [
                                candidate["candidate_requirement_id"] for candidate in case["candidates"]
                            ],
                            "decisions": deepcopy(decisions),
                            "applied_patch_count": 0,
                            "application_error": str(exc),
                        }
                    )
                    continue
                events = trial_events
                round_applied += applied.applied_count
                applied_patch_count += applied.applied_count
                affected_all.update(applied.affected_requirements)
                human_review.extend(applied.human_review)
                records.append(
                    {
                        "round": round_number,
                        "phase": phase,
                        "source_event_ref": deepcopy(case["source_event_ref"]),
                        "candidate_requirement_ids": [
                            candidate["candidate_requirement_id"] for candidate in case["candidates"]
                        ],
                        "decisions": deepcopy(decisions),
                        "applied_patch_count": applied.applied_count,
                    }
                )

            events = self._sort_events(events, normalized)
            for requirement_events in events.values():
                canonicalize_event_payload_fields(requirement_events)
                canonicalize_event_source_texts(requirement_events, normalized)
                validate_intermediate_events(requirement_events, normalized)
            candidate_pair_count = sum(len(case["candidates"]) for case in cases)
            round_summaries.append(
                {
                    "round": round_number,
                    "source_case_count": len(cases),
                    "candidate_pair_count": candidate_pair_count,
                    "decision_count": round_decisions,
                    "applied_patch_count": round_applied,
                }
            )
            print(
                f"[{project.project_id}] CROSS_REQUIREMENT_IMPACT_AUDIT round {round_number} done: "
                f"{candidate_pair_count} pair decision(s), {round_applied} patch(es) applied",
                flush=True,
            )
            if round_applied == 0:
                break

        if round_summaries and round_summaries[-1]["applied_patch_count"] > 0:
            remaining = build_impact_cases(
                inventory,
                events,
                normalized,
                max_candidates_per_event=self.config.max_impact_candidates_per_event,
            )
            remaining_pairs = []
            for case in remaining:
                source_key = source_ref_key(case["source_event_ref"])
                for candidate in case["candidates"]:
                    pair = (source_key, candidate["candidate_requirement_id"])
                    if pair not in processed_pairs:
                        remaining_pairs.append(
                            {
                                "source_event_ref": deepcopy(case["source_event_ref"]),
                                "candidate_requirement_id": candidate["candidate_requirement_id"],
                            }
                        )
            if remaining_pairs:
                human_review.append(
                    {
                        "source": "CROSS_REQUIREMENT_IMPACT_AUDIT",
                        "reason": "New candidate pairs remain after the configured convergence rounds.",
                        "remaining_pairs": remaining_pairs,
                    }
                )

        report = {
            "run_mode": "CROSS_REQUIREMENT_IMPACT_AUDIT",
            "phase": phase,
            "rounds": round_summaries,
            "decision_count": decision_count,
            "applied_patch_count": applied_patch_count,
            "affected_requirement_ids": sorted(affected_all),
            "records": records,
        }
        return events, human_review, applied_patch_count, decision_count, affected_all, report

    async def _verify_all(
        self,
        project: ProjectSource,
        normalized: dict[str, Any],
        inventory: dict[str, Any],
        events: dict[str, list[dict[str, Any]]],
        *,
        audit_review: list[dict[str, Any]],
        force_all: bool,
        force_ids: set[str],
        target_only: bool,
        only_ids: set[str] | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[dict[str, Any]]]:
        requirements = [
            requirement
            for requirement in inventory.get("requirements", [])
            if only_ids is None or requirement.get("requirement_id") in only_ids
        ]
        completed = 0

        async def verify(requirement: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            nonlocal completed
            requirement_id = requirement["requirement_id"]
            provisional = events.get(requirement_id, [])
            target_inventory = focused_inventory(
                inventory,
                requirement,
                include_family_siblings=False,
            )
            audit_review_items = self._audit_review_items_for_requirement(
                audit_review,
                requirement_id,
            )
            path = project.run_dir / "verification" / f"{safe_filename(requirement_id)}.json"
            meta_path = path.with_suffix(".meta.json")
            addendum_hash = sha256_text(self.verification_addendum)
            input_hash = sha256_text(
                json.dumps(
                    {
                        "target_inventory": target_inventory,
                        "provisional_events": provisional,
                        "audit_review_items": audit_review_items,
                        "verification_addendum_sha256": addendum_hash,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            meta_matches = self._checkpoint_hash_matches(meta_path, input_hash)
            refresh_for_hash = self._verification_hash_requires_refresh(
                meta_matches=meta_matches,
                target_only=target_only,
                requirement_id=requirement_id,
                force_ids=force_ids,
            )
            def validator(value: dict[str, Any]) -> None:
                validate_event_verification(value, requirement_id, provisional)
                trial_events, _, _ = apply_verification(provisional, value)
                canonicalize_event_payload_fields(trial_events)
                canonicalize_event_source_texts(trial_events, normalized)
                validate_intermediate_events(trial_events, normalized)
            checkpoint = self._load_valid_checkpoint(
                path,
                force_all
                or requirement_id in force_ids
                or refresh_for_hash,
                validator,
            )
            if checkpoint is None:
                print(f"[{project.project_id}] EVENT_VERIFICATION {requirement_id} started", flush=True)
                checkpoint = await self.api.call(
                    project_id=project.project_id,
                    run_mode="EVENT_VERIFICATION",
                    target_requirement=requirement_id,
                    messages=build_stage_messages(
                        self.common_prompt,
                        "EVENT_VERIFICATION",
                        {
                            "PROJECT_METADATA": self._project_metadata(normalized),
                            "EVIDENCE_INDEX": {
                                "audit_review_items": audit_review_items,
                            },
                            "CURRENT_INVENTORY": target_inventory,
                            "TARGET_REQUIREMENT": requirement,
                            "CURRENT_EVENTS": {requirement_id: provisional},
                            "LOCAL_CONTEXT": verification_context(
                                normalized,
                                provisional,
                                self.config.context_window,
                                self.config.max_requirement_context_messages,
                            ),
                        },
                        stage_instructions=self.verification_addendum,
                    ),
                    validator=validator,
                )
                write_json(path, checkpoint)
                write_json(
                    meta_path,
                    {
                        "input_sha256": input_hash,
                        "verification_addendum_sha256": addendum_hash,
                        "audit_review_item_count": len(audit_review_items),
                    },
                )
            completed += 1
            print(
                f"[{project.project_id}] EVENT_VERIFICATION {completed}/{len(requirements)} "
                f"{requirement_id} done",
                flush=True,
            )
            return requirement_id, checkpoint

        verifications = dict(await asyncio.gather(*(verify(requirement) for requirement in requirements)))
        verified: dict[str, list[dict[str, Any]]] = deepcopy(events) if only_ids is not None else {}
        counts = {"edits": 0, "deletions": 0}
        review: list[dict[str, Any]] = []
        for requirement in requirements:
            requirement_id = requirement["requirement_id"]
            result, local_counts, local_review = apply_verification(
                events.get(requirement_id, []), verifications[requirement_id]
            )
            canonicalize_event_payload_fields(result)
            canonicalize_event_source_texts(result, normalized)
            verified[requirement_id] = result
            counts["edits"] += local_counts["edits"]
            counts["deletions"] += local_counts["deletions"]
            review.extend(local_review)
        verified = self._sort_events(verified, normalized)
        for requirement_events in verified.values():
            validate_intermediate_events(requirement_events, normalized)
        write_json(project.run_dir / "verified_events.json", verified)
        return verified, counts, review

    def _load_valid_checkpoint(self, path: Path, force: bool, validator: Any) -> dict[str, Any] | None:
        if force or not self.config.resume or not path.is_file():
            return None
        try:
            value = read_json(path)
            validator(value)
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[checkpoint invalid] {path}: {exc}; rerunning", flush=True)
            return None

    @staticmethod
    def _read_dict_checkpoint(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            value = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _resume_signature_compatible(existing: Any, current: dict[str, Any]) -> bool:
        if not isinstance(existing, dict):
            return False
        legacy_optional = {
            "max_requirement_context_messages",
            "min_requirement_events",
            "min_instance_events",
        }
        runtime_only = {"reasoning_effort", "min_requirement_events", "min_instance_events"}
        for key, value in existing.items():
            if key in runtime_only:
                continue
            if key not in current or current[key] != value:
                return False
        for key in current:
            if key in runtime_only or key in legacy_optional:
                continue
            if key not in existing:
                return False
        return True

    @classmethod
    def _checkpoint_hash_matches(cls, path: Path, expected: str) -> bool:
        value = cls._read_dict_checkpoint(path)
        return bool(value and value.get("input_sha256") == expected)

    @staticmethod
    def _project_metadata(normalized: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": normalized["project_id"],
            "project_title": normalized.get("project_title"),
            "metadata": normalized.get("project_metadata", {}),
        }

    @staticmethod
    def _audit_review_items_for_requirement(
        items: list[dict[str, Any]],
        requirement_id: str,
    ) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for item in items:
            related_ids: set[str] = set()
            direct_id = item.get("requirement_id")
            if isinstance(direct_id, str):
                related_ids.add(direct_id)
            targets = item.get("targets")
            if isinstance(targets, dict):
                for key in ("requirement_id", "from_requirement_id", "to_requirement_id"):
                    value = targets.get(key)
                    if isinstance(value, str):
                        related_ids.add(value)
                values = targets.get("requirement_ids", [])
                if isinstance(values, list):
                    related_ids.update(value for value in values if isinstance(value, str))
            affected = item.get("affected_requirement_ids", [])
            if isinstance(affected, list):
                related_ids.update(value for value in affected if isinstance(value, str))
            if requirement_id in related_ids:
                matched.append(deepcopy(item))
        return matched

    @staticmethod
    def _verification_hash_requires_refresh(
        *,
        meta_matches: bool,
        target_only: bool,
        requirement_id: str,
        force_ids: set[str],
    ) -> bool:
        if meta_matches:
            return False
        return not (target_only and requirement_id not in force_ids)

    def _prompt_version(self) -> str | None:
        marker = "**Prompt version:**"
        version: str | None = None
        for line in self.common_prompt.splitlines():
            stripped = line.strip()
            if stripped.startswith(marker):
                value = stripped[len(marker) :].strip().strip("`").strip()
                version = value or None
        return version

    @staticmethod
    def _collect_event_extraction_findings(
        project: ProjectSource,
        inventory: dict[str, Any],
    ) -> dict[str, Any]:
        routing_warnings: list[dict[str, Any]] = []
        missing_candidates: list[dict[str, Any]] = []
        for requirement in inventory.get("requirements", []):
            requirement_id = requirement.get("requirement_id")
            if not requirement_id:
                continue
            path = project.run_dir / "events" / f"{safe_filename(requirement_id)}.json"
            checkpoint = Stage1Pipeline._read_dict_checkpoint(path)
            if checkpoint is None:
                continue
            for warning in checkpoint.get("routing_warnings", []):
                routing_warnings.append(
                    {
                        "source_requirement_id": requirement_id,
                        **deepcopy(warning),
                    }
                )
            for candidate in checkpoint.get("missing_requirement_candidates", []):
                missing_candidates.append(
                    {
                        "source_requirement_id": requirement_id,
                        **deepcopy(candidate),
                    }
                )
        report = {
            "routing_warning_count": len(routing_warnings),
            "missing_requirement_candidate_count": len(missing_candidates),
            "routing_warnings": routing_warnings,
            "missing_requirement_candidates": missing_candidates,
        }
        write_json(project.run_dir / "event_extraction_findings.json", report)
        return report

    def _write_discarded_requirements(
        self,
        project: ProjectSource,
        items: list[dict[str, Any]],
    ) -> None:
        write_json(
            project.run_dir / "discarded_requirements.json",
            {
                "minimum_events": self.config.min_requirement_events,
                "discarded_count": len(items),
                "items": items,
            },
        )

    @staticmethod
    def _sort_events(
        events: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        _, order = message_index(normalized)
        result: dict[str, list[dict[str, Any]]] = {}
        for requirement_id, requirement_events in events.items():
            indexed = list(enumerate(requirement_events))
            indexed.sort(
                key=lambda pair: (
                    order.get(id_key(pair[1].get("source_message", {}).get("message_id")), len(order)),
                    pair[0],
                )
            )
            result[requirement_id] = [event for _, event in indexed]
        return result

    @staticmethod
    def _impact_material_signature(events: dict[str, list[dict[str, Any]]]) -> str:
        material: dict[str, list[dict[str, Any]]] = {}
        for requirement_id, requirement_events in events.items():
            values: list[dict[str, Any]] = []
            for event in requirement_events:
                if event.get("event_type") not in {"MODIFY", "REMOVE"}:
                    continue
                values.append(
                    {
                        "message_id": event.get("source_message", {}).get("message_id"),
                        "event_type": event.get("event_type"),
                        "value_updates": event.get("value_updates"),
                        "value_removals": event.get("value_removals"),
                        "scope_updates": event.get("scope_updates"),
                    }
                )
            material[requirement_id] = values
        return sha256_text(json.dumps(material, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _merge_impact_reports(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        phases: list[str] = []
        for report in (first, second):
            phase = report.get("phase")
            if isinstance(phase, str) and phase not in phases:
                phases.append(phase)
            for nested in report.get("phases", []):
                if isinstance(nested, str) and nested not in phases:
                    phases.append(nested)
        affected = set(first.get("affected_requirement_ids", []))
        affected.update(second.get("affected_requirement_ids", []))
        return {
            "run_mode": "CROSS_REQUIREMENT_IMPACT_AUDIT",
            "phases": phases,
            "rounds": deepcopy(first.get("rounds", [])) + deepcopy(second.get("rounds", [])),
            "decision_count": int(first.get("decision_count", 0)) + int(second.get("decision_count", 0)),
            "applied_patch_count": int(first.get("applied_patch_count", 0))
            + int(second.get("applied_patch_count", 0)),
            "affected_requirement_ids": sorted(affected),
            "records": deepcopy(first.get("records", [])) + deepcopy(second.get("records", [])),
        }

    def _metrics(
        self,
        annotation: dict[str, Any],
        human_review: list[dict[str, Any]],
        audit_patch_count: int,
        verifier_counts: dict[str, int],
        discarded_requirements: list[dict[str, Any]],
        *,
        impact_patch_count: int = 0,
        impact_decision_count: int = 0,
    ) -> dict[str, Any]:
        requirements = annotation.get("requirements", [])
        events = [event for requirement in requirements for event in requirement.get("events", [])]
        event_distribution = Counter(event.get("event_type") for event in events)
        length_distribution = Counter(len(requirement.get("events", [])) for requirement in requirements)
        return {
            "requirements": len(requirements),
            "families": len(annotation.get("requirement_families", [])),
            "events": len(events),
            "event_type_distribution": dict(sorted(event_distribution.items())),
            "lifecycle_length_distribution": {
                str(length): count for length, count in sorted(length_distribution.items())
            },
            "ambiguous_cases": event_distribution.get("AMBIGUOUS", 0),
            "audit_patches": audit_patch_count,
            "cross_requirement_impact_decisions": impact_decision_count,
            "cross_requirement_impact_patches": impact_patch_count,
            "verifier_edits": verifier_counts.get("edits", 0),
            "verifier_deletions": verifier_counts.get("deletions", 0),
            "human_review_items": len(human_review),
            "discarded_short_requirements": len(discarded_requirements),
        }

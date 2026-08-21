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
    requirement_context,
    verification_context,
)
from .filtering import filter_short_requirements, merge_discarded_requirements
from .patching import apply_audit_patches, apply_verification, has_valid_requirement_ids
from .preprocessing import message_index, preprocess_project
from .prompt_builder import build_single_pass_messages, build_stage_messages
from .schemas import (
    validate_consistency_audit,
    validate_event_extraction,
    validate_event_verification,
    validate_evidence_scan,
    validate_requirement_discovery,
)
from .storage import id_key, read_json, safe_filename, sha256_text, write_json
from .validation import canonicalize_event_source_texts, validate_intermediate_events, validate_stage1_annotation


class Stage1Pipeline:
    def __init__(
        self,
        api_client: Any,
        config: PipelineConfig,
        common_prompt: str,
        call_log_path: Path,
        single_pass_prompt: str | None = None,
        verification_addendum: str = "",
    ) -> None:
        config.validate()
        self.api = api_client
        self.config = config
        self.common_prompt = common_prompt
        self.single_pass_prompt = single_pass_prompt
        self.verification_addendum = verification_addendum
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
            "started_at": started,
            "status": "RUNNING",
        }
        write_json(metadata_path, base_metadata)
        try:
            if self.config.annotation_mode == "single-pass":
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
        inventory, events, discarded_requirements = filter_short_requirements(
            inventory,
            events,
            self.config.min_requirement_events,
            "EVENT_EXTRACTION",
        )
        self._write_discarded_requirements(project, discarded_requirements)
        if discarded_requirements:
            print(
                f"[{project.project_id}] LIFECYCLE_FILTER discarded {len(discarded_requirements)} Requirement(s) "
                f"with fewer than {self.config.min_requirement_events} events; "
                f"{len(inventory.get('requirements', []))} retained",
                flush=True,
            )
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

        inventory, events, audit_discards = filter_short_requirements(
            inventory,
            events,
            self.config.min_requirement_events,
            "CONSISTENCY_AUDIT",
        )
        discarded_requirements = merge_discarded_requirements(discarded_requirements, audit_discards)
        self._write_discarded_requirements(project, discarded_requirements)

        verification_force_ids = set(self.config.force_requirements).union(audit_affected)
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
        write_json(project.run_dir / "final" / project.output_path.name, annotation)
        metrics = self._metrics(
            annotation,
            human_review,
            audit_patch_count,
            verifier_counts,
            discarded_requirements,
        )
        return annotation, metrics

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
        }
        if self.config.resume and path.is_file() and "evidence_scan" not in force_stages:
            existing = read_json(path)
            if not self._resume_signature_compatible(existing, signature):
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
            validate_intermediate_events(requirement_events, normalized)
        self._collect_event_extraction_findings(project, inventory)
        return inventory, events, human_review, patch_count, affected_all

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
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[dict[str, Any]]]:
        requirements = inventory.get("requirements", [])
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
        verified: dict[str, list[dict[str, Any]]] = {}
        counts = {"edits": 0, "deletions": 0}
        review: list[dict[str, Any]] = []
        for requirement in requirements:
            requirement_id = requirement["requirement_id"]
            result, local_counts, local_review = apply_verification(
                events.get(requirement_id, []), verifications[requirement_id]
            )
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
        for line in self.common_prompt.splitlines():
            stripped = line.strip()
            if stripped.startswith(marker):
                value = stripped[len(marker) :].strip().strip("`").strip()
                return value or None
        return None

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

    def _metrics(
        self,
        annotation: dict[str, Any],
        human_review: list[dict[str, Any]],
        audit_patch_count: int,
        verifier_counts: dict[str, int],
        discarded_requirements: list[dict[str, Any]],
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
            "verifier_edits": verifier_counts.get("edits", 0),
            "verifier_deletions": verifier_counts.get("deletions", 0),
            "human_review_items": len(human_review),
            "discarded_short_requirements": len(discarded_requirements),
        }

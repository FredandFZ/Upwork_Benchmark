#!/usr/bin/env python3
"""Generate the researcher-side RQ4 Code Environment reconstruction plan."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


AGGREGATE_SCHEMA_VERSION = "rq4-code-environment-build-plan-v1"
PROJECT_SCHEMA_VERSION = "rq4-code-environment-project-build-plan-v1"
BUILD_STATUS = "READY_FOR_CODE_ENV_RECONSTRUCTION"
EXCLUDED_STATUS = "EXCLUDED_RQ3_NOT_ACT"
DEFAULT_PROJECT_ALLOWLIST = (
    "42204309",
    "43214420",
    "43255761",
    "43772711",
    "43804272",
    "44035087",
    "44036410",
)


class RQ4BuildPlanError(ValueError):
    """The frozen RQ3 release cannot produce a safe RQ4 build plan."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4BuildPlanError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4BuildPlanError(f"{path} must contain a JSON object")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _portable(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RQ4BuildPlanError(f"path is outside repository root: {path}") from exc


def _source(path: Path, root: Path) -> dict[str, Any]:
    return {"path": _portable(path, root), "file_sha256": _file_sha256(path)}


def _transition_digest(transitions: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for requirement_id, raw in transitions.items():
        if not isinstance(raw, Mapping):
            raise RQ4BuildPlanError(
                f"transition for {requirement_id} must be an object"
            )
        provenance = raw.get("state_provenance", {})
        delta = raw.get("delta", {})
        after = raw.get("after")
        after = after if isinstance(after, Mapping) else {}
        scope = after.get("scope")
        scope = scope if isinstance(scope, Mapping) else {}
        records.append(
            {
                "requirement_id": requirement_id,
                "event_ids": list(raw.get("event_ids", [])),
                "event_types": list(raw.get("event_types", [])),
                "before_state_id": provenance.get("before_state_id"),
                "after_state_id": provenance.get("after_state_id"),
                "change_type": delta.get("change_type"),
                "changed_fields": list(delta.get("changed_fields", [])),
                "changed_paths": list(delta.get("changed_paths", [])),
                "removed_paths": list(delta.get("removed_paths", [])),
                "after_lifecycle_status": after.get("lifecycle_status"),
                "after_components": list(scope.get("components") or []),
                "after_contexts": list(scope.get("contexts") or []),
            }
        )
    return records


def _target_suffix(target_id: str, project_id: str) -> str:
    prefix = f"{project_id}_"
    if not target_id.startswith(prefix):
        raise RQ4BuildPlanError(
            f"target {target_id!r} does not belong to project {project_id!r}"
        )
    return target_id[len(prefix) :]


def _target_row(
    *,
    root: Path,
    project_id: str,
    code_environment_root: Path,
    target_manifest: Mapping[str, Any],
    rq3: Mapping[str, Any],
    rq3_path: Path,
    task_gold: Mapping[str, Any],
    build_sequence: int | None,
) -> dict[str, Any]:
    target_id = str(rq3["target_id"])
    target_message_id = rq3["target_message_id"]
    gold = rq3.get("construction_gold", {})
    if gold.get("status") != "FINAL_UPDATE_OR_CLARIFY_GOLD":
        raise RQ4BuildPlanError(f"{target_id} RQ3 Gold is not frozen")
    final = gold.get("final_gold_by_condition", {})
    c1 = final.get("C1")
    c2 = final.get("C2")
    if not isinstance(c1, Mapping) or c1 != c2:
        raise RQ4BuildPlanError(f"{target_id} C1/C2 RQ3 Gold diverges")
    decision = c1.get("decision")
    if decision not in {"ACT", "CLARIFY"}:
        raise RQ4BuildPlanError(f"{target_id} has invalid RQ3 decision")
    if task_gold.get("target_id") != target_id:
        raise RQ4BuildPlanError(f"{target_id} Task Gold join failed")
    pre = task_gold.get("pre_task_gold_state", {})
    post = task_gold.get("post_task_gold_state", {})
    if pre.get("boundary", {}).get("before_message_id") != target_message_id:
        raise RQ4BuildPlanError(f"{target_id} pre-task boundary mismatch")
    transitions = gold.get("affected_requirement_transitions", {})
    if not isinstance(transitions, Mapping) or not transitions:
        raise RQ4BuildPlanError(f"{target_id} has no affected transition")

    suffix = _target_suffix(target_id, project_id)
    target_dir = (
        code_environment_root
        / project_id
        / "targets"
        / f"{suffix}_before_{target_message_id}"
    )
    is_build = decision == "ACT"
    row: dict[str, Any] = {
        "target_id": target_id,
        "target_message_id": target_message_id,
        "target_fingerprint": rq3.get("target_fingerprint"),
        "turns": rq3.get("turns"),
        "difficulty": rq3.get("difficulty"),
        "target_task": rq3.get("target_task"),
        "rq3_gold_decision": decision,
        "condition_scope": ["C1", "C2"] if is_build else [],
        "plan_status": BUILD_STATUS if is_build else EXCLUDED_STATUS,
        "build_sequence": build_sequence,
        "exclusion_reason": None if is_build else "RQ3_NOT_ACT",
        "code_environment_status": (
            "NOT_BUILT_FOR_CURRENT_RELEASE" if is_build else "NOT_APPLICABLE"
        ),
        "eligibility_status": (
            "PENDING_CODE_ENV_VALIDATION_AND_VALIDATOR"
            if is_build
            else "EXCLUDED_RQ3_NOT_ACT"
        ),
        "output_contract": (
            {
                "target_directory": _portable(target_dir, root),
                "archive_path": _portable(target_dir / "pre_repo.zip", root),
                "manifest_path": _portable(target_dir / "manifest.json", root),
                "before_message_id": target_message_id,
                "workspace_policy": "FRESH_ISOLATED_EXTRACTION_PER_RUN",
            }
            if is_build
            else None
        ),
        "source_artifacts": {
            "rq3_instance": {
                **_source(rq3_path, root),
                "content_sha256": _canonical_sha256(rq3),
            }
        },
        "state_refs": {
            "pre_task": list(pre.get("requirement_states", [])),
            "post_task": list(post.get("requirement_states", [])),
            "affected_requirement_ids": list(
                gold.get("affected_requirement_ids", [])
            ),
            "preserved_requirement_ids": list(
                task_gold.get("preserved_requirement_ids", [])
            ),
        },
        "affected_transition_digest": _transition_digest(transitions),
    }
    if is_build:
        row["builder_gates"] = {
            "pre_state_matches_gold": "REQUIRED",
            "post_transition_trace_matches_gold": "REQUIRED",
            "build_passes": "REQUIRED",
            "regression_passes": "REQUIRED",
            "archive_safety_passes": "REQUIRED",
            "future_state_leakage_absent": "REQUIRED",
            "validator_and_reference_delivery_absent": "REQUIRED",
            "deterministic_observable_triage": "REQUIRED_AFTER_RECONSTRUCTION",
        }
    return row


def build_plan(
    *,
    stage2_root: Path,
    stage1_runs_root: Path,
    stage1_annotations_root: Path,
    code_environment_root: Path,
    repository_root: Path,
    project_allowlist: tuple[str, ...] = DEFAULT_PROJECT_ALLOWLIST,
    project_allowlist_source: Mapping[str, Any] | None = None,
    repository_profiles: Mapping[str, Any],
    repository_profiles_source: Mapping[str, Any],
) -> dict[str, Any]:
    projects: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    input_releases: dict[str, str] = {}
    allowed_projects = set(project_allowlist)
    if not allowed_projects or len(allowed_projects) != len(project_allowlist):
        raise RQ4BuildPlanError("project allowlist must be non-empty and unique")

    for project_dir in sorted(path for path in stage2_root.iterdir() if path.is_dir()):
        manifest_path = project_dir / "rq_instance_manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _read(manifest_path)
        targets = manifest.get("targets", [])
        if not isinstance(targets, list) or not targets:
            continue
        project_id = str(manifest["project_id"])
        if project_id not in allowed_projects:
            continue
        input_releases[project_id] = str(manifest["input_release"])

        gold_path = project_dir / "gold_states.json"
        graph_path = project_dir / "requirement_state_graph.json"
        gold = _read(gold_path)
        task_gold_by_target = {
            str(row["target_id"]): row
            for row in gold.get("task_gold_states", [])
            if isinstance(row, Mapping)
        }
        profile = repository_profiles.get(project_id)
        if not isinstance(profile, Mapping):
            raise RQ4BuildPlanError(f"{project_id} has no repository profile")
        normalized_path = stage1_runs_root / project_id / "normalized_project.json"
        annotation_path = (
            stage1_annotations_root / f"{project_id}_stage1_annotation.json"
        )
        validation_path = (
            project_dir / "target_time_selection" / "gold_state_validation.json"
        )
        for required_path in (normalized_path, annotation_path, validation_path):
            if not required_path.is_file():
                raise RQ4BuildPlanError(
                    f"{project_id} required source is missing: {required_path}"
                )
        target_rows: list[dict[str, Any]] = []
        build_sequence = 0
        for target in sorted(targets, key=lambda row: int(row["target_message_id"])):
            target_id = str(target["target_id"])
            ref = target.get("instances", {}).get("RQ3")
            if not isinstance(ref, Mapping):
                raise RQ4BuildPlanError(f"{target_id} has no RQ3 reference")
            rq3_path = project_dir / str(ref["file"])
            rq3 = _read(rq3_path)
            final = rq3["construction_gold"]["final_gold_by_condition"]["C1"]
            if final["decision"] == "ACT":
                build_sequence += 1
                sequence: int | None = build_sequence
            else:
                sequence = None
            row = _target_row(
                root=repository_root,
                project_id=project_id,
                code_environment_root=code_environment_root,
                target_manifest=target,
                rq3=rq3,
                rq3_path=rq3_path,
                task_gold=task_gold_by_target.get(target_id, {}),
                build_sequence=sequence,
            )
            target_rows.append(row)
            status_counts[row["plan_status"]] += 1
            decision_counts[row["rq3_gold_decision"]] += 1

        projects.append(
            {
                "project_id": project_id,
                "project_title": manifest.get("project_title"),
                "input_release": manifest.get("input_release"),
                "chronological_reconstruction_required": True,
                "project_sources": {
                    "rq_instance_manifest": _source(manifest_path, repository_root),
                    "gold_states": _source(gold_path, repository_root),
                    "requirement_state_graph": _source(graph_path, repository_root),
                    "normalized_project": _source(
                        normalized_path, repository_root
                    ),
                    "stage1_annotation": _source(
                        annotation_path, repository_root
                    ),
                    "gold_state_validation": _source(
                        validation_path, repository_root
                    ),
                    "repository_profiles": dict(repository_profiles_source),
                },
                "repository_profile": dict(profile),
                "target_count": len(target_rows),
                "build_target_count": sum(
                    row["plan_status"] == BUILD_STATUS for row in target_rows
                ),
                "excluded_target_count": sum(
                    row["plan_status"] == EXCLUDED_STATUS for row in target_rows
                ),
                "targets": target_rows,
            }
        )

    discovered_projects = {project["project_id"] for project in projects}
    missing_projects = allowed_projects - discovered_projects
    if missing_projects:
        raise RQ4BuildPlanError(
            "allowlisted projects are missing frozen targets: "
            + ", ".join(sorted(missing_projects))
        )

    plan = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "source_input_releases": input_releases,
        "plan_scope": "RQ4_CODE_ENVIRONMENT_RECONSTRUCTION",
        "source_of_truth": "FROZEN_RQ3_FINAL_GOLD",
        "project_applicability": {
            "selection_source": "USER_CURATED_PROJECT_ALLOWLIST",
            "included_project_ids": list(project_allowlist),
            "excluded_project_policy": "NOT_IN_RQ4_BUILD_SCOPE",
            "rationale": (
                "Only projects whose final deliverable is suitable for a runnable, "
                "locally deterministic Code Environment are included."
            ),
            "source_artifact": dict(project_allowlist_source or {}),
        },
        "unit_of_reconstruction": "PROJECT_CHRONOLOGICAL_REPLAY",
        "snapshot_policy": (
            "Freeze a pre-task Code Environment only at selected targets whose "
            "final C1/C2 RQ3 Gold decision is ACT. Replay every intervening State "
            "Graph event, including non-target messages and selected targets excluded "
            "from RQ4, before freezing the next snapshot."
        ),
        "construction_policy": "FROM_SCRATCH_NEW_RELEASE_ONLY",
        "builder_contract": {
            "ordered_stages": [
                "SOURCE_AND_BOUNDARY_AUDIT",
                "PROJECT_BASELINE_RECONSTRUCTION",
                "CHRONOLOGICAL_STATE_REPLAY",
                "ACT_TARGET_PRE_STATE_SNAPSHOT",
                "POST_TRANSITION_TRACE_CHECK",
                "BUILD_AND_REGRESSION_VALIDATION",
                "ARCHIVE_AND_MANIFEST_FREEZE",
                "RQ4_REPOSITORY_LEAKAGE_AUDIT",
            ],
            "required_project_outputs": [
                "Code Environment/<project_id>/reports/target_index.json",
                "Code Environment/<project_id>/reports/validation_report.json",
                "Code Environment/<project_id>/reports/reconstruction_report.md",
            ],
            "required_target_outputs": [
                "Code Environment/<project_id>/targets/<target_dir>/pre_repo.zip",
                "Code Environment/<project_id>/targets/<target_dir>/manifest.json",
            ],
            "safe_replacement_policy": (
                "Build each project in a project-scoped staging directory. Do not read "
                "or reuse any previous Code Environment. Promote the validated project "
                "atomically so targets/*/manifest.json "
                "and reports/target_index.json contain exactly the plan build targets."
            ),
            "manifest_required_fields": [
                "target_id",
                "before_message_id",
                "repository_classification",
                "contract_layer",
                "web_api_layer",
                "active_code_feature_count",
                "tracked_requirement_count",
                "temporal_fixture",
                "requirements_to_code",
                "target_event_ids",
                "target_event_types",
                "target_summary",
                "pre_state_verified_against_gold",
                "post_state_verified_against_gold",
                "repo_sha256",
            ],
            "forbidden_in_agent_visible_repository": [
                "future_or_post_task_state",
                "acceptance_criteria",
                "hidden_validators",
                "reference_delivery",
                "evaluator_only_requirement_state_event_metadata",
                ".git",
                "secrets",
            ],
            "handoff_completion_condition": (
                "Every build-queue target has a boundary-matched manifest and safe "
                "pre_repo.zip; project validation reports pass; no RQ4 instance is "
                "declared execution-ready by the builder."
            ),
        },
        "post_build_gates_not_owned_by_builder": [
            "ACCEPTANCE_CRITERIA_DESIGN",
            "HIDDEN_VALIDATOR_IMPLEMENTATION_AND_INDEPENDENT_REVIEW",
            "PRE_REFERENCE_PARTIAL_DELIVERY_CALIBRATION",
            "FINAL_RQ4_ELIGIBILITY",
            "RQ4_INSTANCE_MATERIALIZATION",
        ],
        "summary": {
            "project_count": len(projects),
            "selected_target_count": sum(project["target_count"] for project in projects),
            "build_target_count": status_counts[BUILD_STATUS],
            "excluded_rq3_not_act_count": status_counts[EXCLUDED_STATUS],
            "rq3_decision_distribution": dict(decision_counts),
        },
        "projects": projects,
    }
    return plan


def _project_plan(
    aggregate_plan: Mapping[str, Any], project: Mapping[str, Any]
) -> dict[str, Any]:
    """Materialize one independently consumable build plan per project."""
    targets = list(project["targets"])
    decisions = Counter(str(row["rq3_gold_decision"]) for row in targets)
    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "plan_scope": aggregate_plan["plan_scope"],
        "source_of_truth": aggregate_plan["source_of_truth"],
        "project_id": project["project_id"],
        "project_title": project.get("project_title"),
        "input_release": project.get("input_release"),
        "project_applicability": {
            "selection_source": aggregate_plan["project_applicability"][
                "selection_source"
            ],
            "included_project_id": project["project_id"],
            "excluded_project_policy": aggregate_plan["project_applicability"][
                "excluded_project_policy"
            ],
            "rationale": aggregate_plan["project_applicability"]["rationale"],
            "source_artifact": aggregate_plan["project_applicability"][
                "source_artifact"
            ],
        },
        "unit_of_reconstruction": aggregate_plan["unit_of_reconstruction"],
        "snapshot_policy": aggregate_plan["snapshot_policy"],
        "construction_policy": aggregate_plan["construction_policy"],
        "builder_contract": aggregate_plan["builder_contract"],
        "post_build_gates_not_owned_by_builder": aggregate_plan[
            "post_build_gates_not_owned_by_builder"
        ],
        "chronological_reconstruction_required": project[
            "chronological_reconstruction_required"
        ],
        "project_sources": project["project_sources"],
        "repository_profile": project["repository_profile"],
        "summary": {
            "selected_target_count": len(targets),
            "build_target_count": project["build_target_count"],
            "excluded_rq3_not_act_count": project["excluded_target_count"],
            "rq3_decision_distribution": dict(decisions),
        },
        "targets": targets,
    }


def _builder_prompt() -> str:
    project_plan_path = "<project_plan_path>"
    project_ids = "<project_plan.project_id>"
    return f"""# RQ4 Code Environment Reconstruction Agent Prompt

你是 ReqMemBench 的 researcher-side Code Environment Reconstruction Agent。你的任务是依据冻结的
RQ4 Build Plan，为后续 RQ4 Phase B 构造真实可运行、边界正确且不泄漏 Gold 的 pre-task repository。

## 权威输入与范围

- Build Plan：调用方必须显式提供单个项目的 `{project_plan_path}`
- 执行前校验：`python Code/validate_rq4_build_plan.py --plan {project_plan_path}`
- 唯一允许构造 RQ4 Code Environment 的项目：`{project_ids}`
- 本次只处理一个项目；禁止同时加载或构建其他项目
- 冻结 target 数、实际 build queue 和 RQ3=`CLARIFY` 排除数以该 plan 的 `summary` 为准

JSON Build Plan 是队列、顺序、source hash、target boundary 和输出路径的唯一权威来源。只处理
`plan_status=READY_FOR_CODE_ENV_RECONSTRUCTION` 的 target。不得为
`EXCLUDED_RQ3_NOT_ACT` target 生成 snapshot，也不得自行添加其他项目或 target。

## 目标产物

对每个 build target 生成：

- Build Plan `output_contract.archive_path` 指定的 `pre_repo.zip`；
- Build Plan `output_contract.manifest_path` 指定的 `manifest.json`。

对每个项目生成：

- `Code Environment/<project_id>/reports/target_index.json`；
- `Code Environment/<project_id>/reports/validation_report.json`；
- `Code Environment/<project_id>/reports/reconstruction_report.md`；
- 重建所需且可复现的 `tools/` 脚本。

## 核心语义边界

1. `before_message_id` 等于 target message ID，表示 repository 必须严格停留在该消息发生之前。
2. target message 所要求的变化不能提前出现在 `pre_repo.zip`；它只能用于私有的 post-transition
   trace verification。
3. 必须按项目时间顺序回放完整 Requirement State Graph。两个 build target 之间的所有 Event 都要
   应用，包括非 target 消息和被 RQ3=`CLARIFY` 排除的 selected target。
4. 每个 build snapshot 必须反映该时间点全部相关历史状态，而不能只实现当前 affected
   Requirement。被移除、暂停、恢复、失败或已验证工作的生命周期和执行状态也必须正确体现。
5. 如果 target 报告已有 runtime failure，pre-task repository 应能确定性复现该旧失败，同时基础
   Build 和与该失败无关的 regression 仍应通过。

## Repository 质量要求

- 构造可实际安装、构建、启动或解析的 repository/artifact workflow，不得只把 Gold attributes
  原样写入 JSON 后声称可执行。
- 根据项目最终交付选择合理的技术栈。Web/API/contract 项目应提供本地可运行服务或函数接口；
  文档、模板或设计工件项目应提供确定性的生成、解析和结构检查脚本。
- 尽量离线运行；固定依赖版本和 lockfile，不依赖外部 API、在线语义模型、真实密钥或不稳定网络。
- 为项目保留最小但真实的 build 与 regression suite。它们用于证明环境有效，不得编码当前
  target 的未来答案。
- 同一项目的 snapshots 应来自一个可复现的 chronological reconstruction pipeline，而不是互相
  无关地手写多份 repository。

## 每个项目的执行步骤

1. 运行 Build Plan validator。任何 source hash 失败都必须停止并报告，不能继续使用过期计划。
2. 读取 plan 冻结的 Stage 1 normalized project、Stage 1 annotation、Gold State、State Graph、
   Gold validation、repository profile 和各 target 的冻结 RQ3 instance。
3. 在项目专属 staging 目录重建基础 repository；不要直接覆盖当前 canonical Code Environment。
4. 按 State Graph 顺序应用每个 Event，在计划指定的 ACT target 前冻结 snapshot。
5. 对 snapshot 执行 build、startup/parse smoke check 与已有 regression tests。
6. 私下应用当前 target transition，确认 reconstruction 能表达 RQ3 Gold 的 after-state；随后丢弃
   该 post-state 工作副本，归档的仍然只能是 pre-state。
7. 生成 manifest，逐项核对 target ID、boundary、Event IDs/types、State 映射和 tree SHA-256。
8. 对 `pre_repo.zip` 执行 CRC、路径穿越、symlink、`.git`、secret 和 RQ4 Gold leakage 检查。
9. 完成一个项目的全部 target 后，生成 target index、validation report 和 reconstruction report。
10. 仅当整个项目全部通过时，才把 staging 项目原子提升到 canonical 路径。

## Manifest 与索引契约

每个 manifest 至少包含 Build Plan 中 `builder_contract.manifest_required_fields` 列出的字段。
`target_index.json` 必须是 manifest 记录的数组，并满足：

- target 集合与该项目 Build Plan 中的 build target 完全相等；
- 不包含旧 target、CLARIFY target 或其他项目；
- `before_message_id`、`target_event_ids`、`target_event_types`、`repo_sha256` 与对应 manifest 完全一致；
- target 按时间顺序排列。

`validation_report.json` 的顶层 `overall` 只有全部环境检查通过时才能写为 `pass`。失败 target 必须
保留真实命令、exit code、必要的输出尾部和失败原因，不能伪造通过结果或静默跳过。

## 严禁泄漏到 Agent-visible repository

- target 的 future/post-task state；
- Acceptance Criteria、hidden validator、validator ID/path；
- Reference Delivery 或 reference patch；
- evaluator-only Requirement/State/Event ID、Gold 文件或 Build Plan；
- `.git`、凭据、token、真实用户数据；
- 能直接揭示当前 target 正确实现的测试或注释。

研究侧 manifest 可以保存 Requirement/State/Event provenance，但这些文件不能进入
`pre_repo.zip`。

## 从零构建与旧环境隔离

不得读取、复制、解压、比较或参考任何先前 `Code Environment/` 中的代码、工具链、archive、
manifest、hash 或报告。技术栈和行为表面只能来自当前项目 plan 的 `repository_profile` 以及其中
冻结的新 Stage 1/2 来源。每个项目必须在 staging 中从零构造并重新验证；canonical
`targets/*/manifest.json` 与 `target_index.json` 只能包含当前计划 target。

## 不属于本任务的工作

不要执行以下事项：

- 修改 RQ1、RQ2、RQ3 Gold 或 Build Plan；
- 设计或暴露 Acceptance Criteria；
- 编写 hidden validator 或 Reference Delivery；
- 决定最终 RQ4 eligibility；
- 生成 RQ4 instance；
- 运行正式 benchmark Agent。

这些步骤将在 Code Environment 构建通过后由独立 gate 完成。

## 完成条件

只有同时满足以下条件才报告完成：

1. Build Plan 中全部 build target 均有 boundary-correct 的
   `manifest.json` 和安全的 `pre_repo.zip`；
2. 当前项目的 build/regression validation 全部通过；
3. 每个项目 canonical target 集合与计划完全一致；
4. archive/tree/file hashes 已冻结且索引一致；
5. 所有 leakage/secret/archive safety checks 通过；
6. 已列出任何未完成项目或 target，且没有把它们伪装为完成。
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage2-root", type=Path, default=root / "outputs_new" / "stage2"
    )
    parser.add_argument(
        "--stage1-runs-root",
        type=Path,
        default=root / "outputs_new" / "stage1_runs",
    )
    parser.add_argument(
        "--stage1-annotations-root",
        type=Path,
        default=root / "outputs_new" / "stage1_annotations",
    )
    parser.add_argument(
        "--code-environment-root", type=Path, default=root / "Code Environment"
    )
    parser.add_argument(
        "--plans-root",
        type=Path,
        default=(
            root
            / "ccfa-workfiles"
            / "experiments"
            / "rq4-code-environment"
            / "projects"
        ),
        help="Directory containing <project_id>/rq4_build_plan.json files.",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=root / "prompt" / "rq4_code_environment_builder.md",
    )
    parser.add_argument(
        "--project-allowlist",
        type=Path,
        default=root / "Code" / "config" / "rq4_project_allowlist.json",
    )
    parser.add_argument(
        "--repository-profiles",
        type=Path,
        default=root / "Code" / "config" / "rq4_repository_profiles.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    root = Path(__file__).resolve().parents[1]
    try:
        allowlist = _read(args.project_allowlist)
        if allowlist.get("schema_version") != "rq4-project-allowlist-v1":
            raise RQ4BuildPlanError("invalid RQ4 project allowlist schema")
        project_ids = allowlist.get("project_ids")
        if not isinstance(project_ids, list) or not all(
            isinstance(value, str) and value for value in project_ids
        ):
            raise RQ4BuildPlanError("RQ4 project allowlist has invalid project_ids")
        profiles_document = _read(args.repository_profiles)
        profiles = profiles_document.get("profiles")
        if (
            profiles_document.get("schema_version")
            != "rq4-repository-profiles-v1"
            or not isinstance(profiles, Mapping)
        ):
            raise RQ4BuildPlanError("invalid RQ4 repository profiles")
        aggregate_plan = build_plan(
            stage2_root=args.stage2_root,
            stage1_runs_root=args.stage1_runs_root,
            stage1_annotations_root=args.stage1_annotations_root,
            code_environment_root=args.code_environment_root,
            repository_root=root,
            project_allowlist=tuple(project_ids),
            project_allowlist_source=_source(args.project_allowlist, root),
            repository_profiles=profiles,
            repository_profiles_source=_source(args.repository_profiles, root),
        )
        if not args.validate_only:
            for project in aggregate_plan["projects"]:
                project_plan = _project_plan(aggregate_plan, project)
                plan_path = (
                    args.plans_root
                    / str(project_plan["project_id"])
                    / "rq4_build_plan.json"
                )
                _write(
                    plan_path,
                    json.dumps(project_plan, ensure_ascii=False, indent=2) + "\n",
                )
            _write(args.prompt, _builder_prompt())
        print(json.dumps(aggregate_plan["summary"], ensure_ascii=False, indent=2))
        return 0
    except (OSError, RQ4BuildPlanError) as exc:
        print(f"RQ4 Build Plan generation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

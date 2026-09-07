# ReqMemBench RQ1–RQ4 实例构建设计

## 1. 文档目标与边界

本文只说明 `Code/stage2/rq_instances.py` 如何把 Stage 2 的上游产物构造成
`outputs/stage2/<project_id>/RQ1/`–`RQ4/` 四个文件夹，以及每类实例 JSON 的实际结构。

本文重点回答四个问题：

1. 每个 target 为什么会进入某个 RQ 文件夹；
2. 构造器从 Gold State、State Graph、历史消息和 Code Environment 中提取什么；
3. RQ1、RQ2、RQ3、RQ4 的 `construction_gold` 分别怎样生成；
4. 单实例文件、文件夹 `index.json` 和项目 `rq_instance_manifest.json` 怎样形成。

本文不定义 Agent 运行协议、Agent 公共输出、评分指标、实验聚合或执行评估流程。这些内容
不属于 RQ 实例构造。构建命令、参数和报错处理见
[`Code/insturctions/README_stage2_rq_instances.md`](../Code/insturctions/README_stage2_rq_instances.md)。

当前构造器生成的是 researcher-side construction record。它包含内部 Requirement、
Event、State ID 和 `construction_gold`，不能原样作为 Agent 输入。

---

## 2. 从上游产物到四个 RQ 文件夹

### 2.1 输入

构造器读取以下输入：

| 输入 | 构造用途 |
|---|---|
| `outputs/stage2/<project_id>/gold_states.json` | target、`primary_rq_targets`、Task Events、affected Requirements、Pre/Post State references |
| `outputs/stage2/<project_id>/requirement_state_graph.json` | 展开 State、取得 Event trajectory、Event type 和 provenance |
| `outputs/stage1_runs/<project_id>/normalized_project.json` | target 前完整脱敏历史、稳定消息顺序、speaker 和 text |
| `Code Environment/<project_id>/` | 仅为 RQ4 关联 target 对应的 `pre_repo.zip`、manifest、checksum 和 reconstruction validation |

三份 JSON 输入的 `project_id` 必须一致，Gold State schema 必须是 `task-gold-v2`。

### 2.2 总体构造流程

```text
gold_states.json.task_gold_states[]
                    |
                    | 逐个 target
                    v
        校验 target、消息顺序和 Pre/Post boundary
                    |
                    +--> 从 State Graph 展开 Pre/Post 完整状态
                    |
                    +--> 推导历史相关 Requirement 与 evidence trajectory
                    |
                    +--> 提取 affected Requirement 的 target Events
                    |
                    +--> 检查 Post State 中的 OPEN ambiguity
                    |
                    +--> RQ4 额外关联 Code Environment
                    |
                    v
        读取 task_gold.primary_rq_targets
                    |
        +-----------+-----------+-----------+-----------+
        |                       |                       |
      含 RQ1                  含 RQ2                  ...
        |                       |
        v                       v
RQ1/<target>_RQ1.json   RQ2/<target>_RQ2.json
        |
        +--> 各 RQ 文件夹的 index.json
                    |
                    +--> 项目 rq_instance_manifest.json
```

### 2.3 文件夹收录规则

`task_gold.primary_rq_targets` 是文件夹收录的唯一入口：

```python
for task_gold in gold_states["task_gold_states"]:
    for rq_id in ("RQ1", "RQ2", "RQ3", "RQ4"):
        if rq_id in task_gold["primary_rq_targets"]:
            构造 <target_id>_<rq_id>.json
```

因此：

- 一个 target 可以同时出现在多个 RQ 文件夹；
- 一个 target 不会因为存在于 Gold State 就自动生成四个 RQ 文件；
- `primary_rq_targets` 中没有某个 RQ，就不会生成该 target/RQ pair；
- 每个 pair 只生成一个 JSON，`instance_id = <target_id>_<rq_id>`；
- 各文件夹中的实例按 `target_message_id` 的规范化对话位置排序。

项目 `42204309` 的当前实际结果是：

| 文件夹 | 实例数 | 来源 |
|---|---:|---|
| `RQ1/` | 21 | 25 个 Task Gold 中有 21 个包含 `RQ1` |
| `RQ2/` | 25 | 25 个 Task Gold 全部包含 `RQ2` |
| `RQ3/` | 18 | 18 个 Task Gold 包含 `RQ3` |
| `RQ4/` | 16 | 16 个 Task Gold 包含 `RQ4` |
| 合计 | 80 | target/RQ pair 数，不是唯一 target 数 |

---

## 3. 四类实例共享的构造过程

### 3.1 Target 与时间边界

对每条 Task Gold：

1. 用 `target_task.source_message_id` 在 normalized messages 中定位 target；
2. 校验 target 的 `speaker`、`text` 与消息目录一致；
3. 取 target 之前的全部消息作为 `history_pool.messages`；
4. 校验 `history_turn_count == turns == target 前消息数`；
5. 校验 `conversation_turn_index == turns + 1`；
6. 校验 Pre boundary 是 `before_message_id == target_message_id`；
7. 校验 Post boundary 是 `through_message_id == target_message_id`。

消息 ID 只是稳定标识，可以是整数或字符串；时间顺序必须来自 normalized messages 的数组
位置，不能用 message ID 的数值大小推断。

### 3.2 State 展开

Gold State 只保存：

```json
{
  "requirement_id": "REQ_*",
  "state_id": "REQ_*_S001"
}
```

实例构造器使用 State Graph 将其展开为：

```json
{
  "requirement_id": "REQ_*",
  "requirement_title": "...",
  "family_id": "...",
  "state_id": "REQ_*_S001",
  "attributes": {},
  "scope": {
    "persistence": "PROJECT_PERSISTENT",
    "components": [],
    "contexts": []
  },
  "lifecycle_status": "ACTIVE",
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": []
}
```

Pre/Post snapshot 中的每个 `state_id` 必须存在，并且必须属于同一
`requirement_id`。展开失败时整个 target 构建失败。

### 3.3 相关 Requirement 与历史证据

构造器先做可确定的 direct relevance 推导：

```text
directly_affected_historical_requirement_ids
    = affected_requirement_ids ∩ Pre-task Requirements

new_requirement_ids
    = affected_requirement_ids - Pre-task Requirements

relevant_requirement_ids
    = directly_affected_historical_requirement_ids
      + 已审核的 inherited constraints
```

当前自动构造阶段只确定 direct historical Requirements。继承约束
`inherited_constraint_requirement_ids` 初始为空，并以 review status 标记待后续补充。

对每个直接相关的历史 Requirement，构造器生成：

- `current_support_event_ids`：支持 Pre-task 当前状态的 Events；
- `current_support_message_ids`：上述 Events 对应的消息；
- `trajectory_event_ids`：target 前该 Requirement 的完整 Event trajectory；
- `core_message_ids`：完整 trajectory 对应的有序消息；
- `context_message_ids`：初始为空；
- `context_review_status`：标记 contextual message 尚待确认。

### 3.4 历史池与条件引用

每个实例保存相同的 `history_pool`，其中只含 target 之前的脱敏消息。每条消息固定为：

```json
{
  "message_id": 1,
  "created_ts": "...",
  "speaker": "client",
  "text": "...",
  "milestone": null
}
```

`condition_inputs` 是构造产物中的历史 ID 引用：

- `C1`：空历史；
- `C2`：`history_pool` 中的全部消息 ID；
- `C3`：相关 Requirement trajectory 对应的有序消息 ID。

RQ1 只把 C2 标为 available；RQ2–RQ4 把 C1、C2、C3 都标为 available。本文只说明
这些字段怎样构造，不讨论运行或评估方式。

---

## 4. 单实例公共 schema

RQ1–RQ4 共享 `rq-instance-v1` 顶层结构。RQ4 比其他三类多一个
`code_environment` 字段。为保持与实际 JSON 一致，下面保留 `response_contract` 和
`visibility` 的字段位置，但不展开其 Agent 运行或输出语义。

```json
{
  "schema_version": "rq-instance-v1",
  "instance_id": "42204309_T001_RQ1",
  "project_id": "42204309",
  "project_title": "...",
  "rq_id": "RQ1",
  "rq_name": "Relevant Requirement Selection",
  "target_id": "42204309_T001",
  "task_gold_id": "42204309_T001_GOLD",
  "target_message_id": 114,
  "turns": 1,
  "history_turn_count": 1,
  "difficulty": "SHORT",
  "selection_basis": {
    "source": "task_gold.primary_rq_targets",
    "final_rq_eligibility": "PENDING_RQ_SPECIFIC_REVIEW"
  },
  "question": "...",
  "target_task": {
    "source_message_id": 114,
    "speaker": "client",
    "text": "..."
  },
  "history_pool": {
    "boundary": "STRICTLY_BEFORE_TARGET_MESSAGE",
    "contains_target_message": false,
    "message_count": 1,
    "messages": [
      {
        "message_id": 1,
        "created_ts": "...",
        "speaker": "client",
        "text": "...",
        "milestone": null
      }
    ]
  },
  "condition_inputs": {
    "C1": {
      "available": false,
      "history_mode": "NO_HISTORY",
      "history_message_ids": [],
      "history_message_count": 0,
      "review_status": "NOT_APPLICABLE"
    },
    "C2": {
      "available": true,
      "history_mode": "FULL_HISTORY",
      "history_message_ids": [1],
      "history_message_count": 1,
      "review_status": "DETERMINISTIC"
    },
    "C3": {
      "available": false,
      "history_mode": "ORACLE_RELEVANT_HISTORY",
      "history_message_ids": [1],
      "history_message_count": 1,
      "review_status": "PENDING_CONTEXT_AND_INHERITED_CONSTRAINT_REVIEW"
    }
  },
  "response_contract": {},
  "visibility": {
    "record_kind": "RESEARCHER_SIDE_CONSTRUCTION_INSTANCE",
    "runner_must_hide": [
      "construction_gold",
      "source_artifacts",
      "selection_basis"
    ],
    "runner_materialization_status": "NOT_IMPLEMENTED_IN_THIS_STAGE"
  },
  "source_artifacts": {
    "gold_states": {
      "path": "outputs/stage2/42204309/gold_states.json",
      "sha256": "..."
    },
    "requirement_state_graph": {
      "path": "outputs/stage2/42204309/requirement_state_graph.json",
      "sha256": "..."
    },
    "normalized_project": {
      "path": "outputs/stage1_runs/42204309/normalized_project.json",
      "sha256": "..."
    },
    "code_environment": {
      "path": "Code Environment/42204309"
    }
  },
  "construction_gold": {}
}
```

公共字段约束：

| 字段 | 约束 |
|---|---|
| `schema_version` | 固定为 `rq-instance-v1` |
| `instance_id` | 固定为 `<target_id>_<rq_id>` |
| `rq_id` | `RQ1`、`RQ2`、`RQ3`、`RQ4` 之一 |
| `turns` | target 前的规范化消息数 |
| `history_turn_count` | 必须等于 `turns` |
| `difficulty` | `0–25 -> SHORT`，`26–50 -> MEDIUM`，`>50 -> LONG` |
| `history_pool.message_count` | 必须等于 `messages` 数量和 `turns` |
| `target_message_id` | 不得出现在 `history_pool` 中 |
| `construction_gold` | 必填；具体结构由 RQ 类型决定 |

---

## 5. RQ1 实例如何构建

### 5.1 收录条件

当 Task Gold 的 `primary_rq_targets` 包含 `RQ1` 时，生成：

```text
outputs/stage2/<project_id>/RQ1/<target_id>_RQ1.json
```

### 5.2 构造步骤

1. 从 `affected_requirement_ids` 中找出 Pre-task snapshot 已存在的 Requirements；
2. 将 target 首次引入、Pre-task 不存在的 Requirements 单独放入 `new_requirement_ids`；
3. 对每个历史 Requirement 从 State Graph 提取当前支持 Events；
4. 提取该 Requirement 在 target 前的完整 Event trajectory；
5. 将 Event IDs 映射为有序 message IDs；
6. 形成 `evidence` 映射；
7. inherited constraints 和 contextual messages 保持为空并标为待审核。

RQ1 文件的核心不是重复保存完整 State，而是保存“哪些历史 Requirements 相关，以及相关
证据来自哪些 Event/message”。

### 5.3 RQ1 `construction_gold` schema

```json
{
  "status": "PROVISIONAL_REQUIRES_RELEVANCE_REVIEW",
  "relevant_requirement_ids": [
    "REQ_BADGE_CATALOG_AND_PRESENTATION"
  ],
  "directly_affected_historical_requirement_ids": [
    "REQ_BADGE_CATALOG_AND_PRESENTATION"
  ],
  "inherited_constraint_requirement_ids": [],
  "new_requirement_ids": [
    "REQ_BADGE_AWARD_ACCURACY"
  ],
  "evidence": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "current_support_event_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E002"
      ],
      "current_support_message_ids": [101],
      "trajectory_event_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E001",
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E002"
      ],
      "core_message_ids": [85, 101],
      "context_message_ids": [],
      "context_review_status": "PENDING_CONTEXT_MESSAGE_REVIEW"
    }
  },
  "derivation_scope": "DIRECT_AFFECTED_ONLY",
  "review_status": "PENDING_INHERITED_CONSTRAINT_AND_CONTEXT_REVIEW"
}
```

其中 `evidence` 是以 `requirement_id` 为动态 key 的对象；每个 key 的 value 固定使用上述
六个字段。

---

## 6. RQ2 实例如何构建

### 6.1 收录条件

当 `primary_rq_targets` 包含 `RQ2` 时，生成：

```text
outputs/stage2/<project_id>/RQ2/<target_id>_RQ2.json
```

### 6.2 构造步骤

1. 复用 RQ1 阶段得到的 `relevant_requirement_ids`；
2. 对每个 relevant historical Requirement 读取 Pre-task `state_id`；
3. 从 State Graph 展开完整语义状态；
4. 按 `requirement_id` 写入 `states`；
5. 新 Requirements 单列在 `new_requirement_ids`，不伪造其 Pre-task State。

RQ2 保存的是 target 到来前已经成立的状态，不使用 Post-task State 代替当前状态。

### 6.3 RQ2 `construction_gold` schema

```json
{
  "status": "PROVISIONAL_REQUIRES_RELEVANCE_REVIEW",
  "gold_requirement_ids": [
    "REQ_BADGE_CATALOG_AND_PRESENTATION"
  ],
  "new_requirement_ids": [
    "REQ_BADGE_AWARD_ACCURACY"
  ],
  "states": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
      "requirement_title": "Badge Catalog and Presentation",
      "family_id": "ACHIEVEMENT_SYSTEM",
      "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
      "attributes": {},
      "scope": {
        "persistence": "PROJECT_PERSISTENT",
        "components": ["FRONTEND", "UI_UX"],
        "contexts": ["BADGES"]
      },
      "lifecycle_status": "ACTIVE",
      "ambiguity": null,
      "execution": null,
      "supporting_event_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E002"
      ]
    }
  },
  "state_dimensions": [
    "selection",
    "attributes",
    "lifecycle",
    "scope",
    "ambiguity",
    "execution"
  ],
  "review_status": "PENDING_INHERITED_CONSTRAINT_AND_CONTEXT_REVIEW"
}
```

`states` 同样以 `requirement_id` 为动态 key。每个 State 对象固定包含
`requirement_id`、`requirement_title`、`family_id`、`state_id`、`attributes`、`scope`、
`lifecycle_status`、`ambiguity`、`execution` 和 `supporting_event_ids`。

---

## 7. RQ3 实例如何构建

### 7.1 收录条件

当 `primary_rq_targets` 包含 `RQ3` 时，生成：

```text
outputs/stage2/<project_id>/RQ3/<target_id>_RQ3.json
```

### 7.2 构造步骤

1. 只检查 affected Requirements 的 Post-task State；
2. 从 `ambiguity` 映射中收集 `status == "OPEN"` 的条目；
3. 将它们写为 `blocking_ambiguity_candidates`，但不直接宣布为最终 blocking Gold；
4. 存在候选时，项目级 decision candidate 为 `CLARIFY`，否则为 `ACT`；
5. C1 的证据充分性无法由当前确定性输入直接决定，因此 value 为 `null`；
6. 多 Requirement task 的 `safe_subactions` 初始为空。

RQ3 构造的结果是“待审核的决策候选”，不是执行评估结果。

### 7.3 RQ3 `construction_gold` schema

```json
{
  "status": "PENDING_HUMAN_DECISION_REVIEW",
  "project_decision_candidate": {
    "value": "CLARIFY",
    "is_final_gold": false,
    "basis": "OPEN ambiguity exists on a directly affected Requirement"
  },
  "decision_candidates_by_condition": {
    "C1": {
      "value": null,
      "status": "PENDING_EVIDENCE_SUFFICIENCY_REVIEW"
    },
    "C2": {
      "value": "CLARIFY",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    },
    "C3": {
      "value": "CLARIFY",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    }
  },
  "blocking_ambiguity_candidates": [
    {
      "requirement_id": "REQ_PRIZE_CLAIM_FLOW",
      "ambiguity_event_id": "REQ_PRIZE_CLAIM_FLOW_E003",
      "dimension": "VALUE",
      "description": "...",
      "source_event_id": "REQ_PRIZE_CLAIM_FLOW_E003",
      "blocking_status": "PENDING_MATERIALITY_REVIEW"
    }
  ],
  "safe_subactions": [],
  "safe_subactions_review_status": "PENDING_MULTI_REQUIREMENT_REVIEW",
  "relevance_review_status": "PENDING_INHERITED_CONSTRAINT_AND_CONTEXT_REVIEW",
  "review_note": "..."
}
```

没有 OPEN ambiguity 时：

```json
{
  "project_decision_candidate": {
    "value": "ACT",
    "is_final_gold": false,
    "basis": "No OPEN ambiguity exists on a directly affected Requirement"
  },
  "blocking_ambiguity_candidates": []
}
```

其余字段仍然保留。

---

## 8. RQ4 实例如何构建

### 8.1 收录条件

当 `primary_rq_targets` 包含 `RQ4` 时，生成：

```text
outputs/stage2/<project_id>/RQ4/<target_id>_RQ4.json
```

RQ4 实例在公共 schema 基础上额外要求 `code_environment`。

### 8.2 Requirement transition 构造

构造器先验证：

```text
task_event_ids 的 Event owner 集合
    == affected_requirement_ids

每个 task Event 的 source_message_id
    == target_message_id
```

然后对每个 affected Requirement：

1. 读取 Pre-task expanded State；新 Requirement 的 before 为 `null`；
2. 读取 Post-task expanded State；
3. 比较 `attributes`、`scope`、`lifecycle_status`、`ambiguity`、`execution`；
4. 生成 `state_delta.change_type` 和 `changed_fields`；
5. 根据 Event type 和 State delta 派生 action/operation candidate。

派生优先级：

| 条件 | `action_candidate` | `operation_candidate` |
|---|---|---|
| Event 含 `REMOVE` 或 Post lifecycle 为 `REMOVED` | `REMOVE` | `REMOVE` |
| Event 含 `RUNTIME_FAILURE` | `MODIFY` | `REPAIR` |
| Event 含 `DEFER` | `MODIFY` | `DEFER` |
| Event 含 `RESUME` | `MODIFY` | `RESUME` |
| Pre State 不存在 | `IMPLEMENT` | `IMPLEMENT` |
| Pre/Post 语义字段发生变化 | `MODIFY` | `APPLY_STATE_TRANSITION` |
| 以上均不满足 | `PRESERVE` | `VERIFY_OR_NO_CODE_CHANGE` |

### 8.3 `code_environment` schema

构造器不解压 `pre_repo.zip`，只验证并记录归档与 reconstruction metadata：

```json
{
  "available": true,
  "archive_path": "Code Environment/42204309/targets/T001_before_114/pre_repo.zip",
  "manifest_path": "Code Environment/42204309/targets/T001_before_114/manifest.json",
  "manifest_sha256": "...",
  "archive_sha256": "...",
  "repository_tree_sha256": "...",
  "before_message_id": 114,
  "repository_classification": "simulated-executable-pre-state",
  "contract_layer": "observed-toolchain-plus-simulated-state-model",
  "web_api_layer": "simulated-from-chat-and-state-graph",
  "active_code_feature_count": 18,
  "tracked_requirement_count": 21,
  "requirements_to_code": [
    {
      "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
      "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
      "lifecycle": "ACTIVE",
      "components": ["FRONTEND", "UI_UX"],
      "implementation_mode": "simulated_executable",
      "code_paths": ["apps/web/public/app.js"]
    }
  ],
  "temporal_fixture": null,
  "archive_inspection": {
    "archive_sha256": "...",
    "archive_validation": "PASS",
    "member_path_validation": "PASS",
    "crc_validation": "PASS",
    "contains_git_metadata": false,
    "contains_symlinks": false,
    "file_count": 1,
    "directory_count": 0,
    "compressed_member_bytes": 1,
    "uncompressed_member_bytes": 1
  },
  "reconstruction_validation": {
    "overall": "pass",
    "validation_report_path": "...",
    "validation_report_sha256": "...",
    "target_index_path": "...",
    "target_index_sha256": "..."
  },
  "workspace_policy": "EXTRACT_TO_FRESH_ISOLATED_WORKSPACE_PER_RUN",
  "extracted_during_instance_construction": false
}
```

### 8.4 RQ4 `construction_gold` schema

```json
{
  "status": "PROVISIONAL_NOT_EXECUTION_READY",
  "task_action_candidates_by_condition": {
    "C1": {
      "value": null,
      "status": "PENDING_EVIDENCE_SUFFICIENCY_REVIEW"
    },
    "C2": {
      "value": "APPLY_CHANGES",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    },
    "C3": {
      "value": "APPLY_CHANGES",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    }
  },
  "requirement_action_candidates": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
      "action_candidate": "MODIFY",
      "operation_candidate": "APPLY_STATE_TRANSITION",
      "event_types": ["MODIFY"],
      "before_state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
      "after_state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S003",
      "state_delta": {
        "change_type": "MODIFIED",
        "changed_fields": ["attributes"]
      },
      "open_ambiguity_present": false,
      "review_status": "DETERMINISTIC_TRANSITION_CANDIDATE"
    }
  },
  "affected_requirement_transitions": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "before": {
        "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
        "requirement_title": "Badge Catalog and Presentation",
        "family_id": "ACHIEVEMENT_SYSTEM",
        "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null,
        "supporting_event_ids": []
      },
      "after": {
        "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
        "requirement_title": "Badge Catalog and Presentation",
        "family_id": "ACHIEVEMENT_SYSTEM",
        "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S003",
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null,
        "supporting_event_ids": []
      },
      "delta": {
        "change_type": "MODIFIED",
        "changed_fields": ["attributes"]
      }
    }
  },
  "inherited_constraint_actions": {},
  "inherited_constraint_review_status": "PENDING_INHERITED_CONSTRAINT_AND_CONTEXT_REVIEW",
  "acceptance_criteria": [],
  "validator_ids": [],
  "execution_ready": false,
  "execution_readiness_blockers": [
    "FINAL_BLOCKING_AMBIGUITY_DECISION_REQUIRED",
    "INHERITED_CONSTRAINT_REVIEW_REQUIRED",
    "ACCEPTANCE_CRITERIA_REQUIRED",
    "HIDDEN_VALIDATORS_REQUIRED"
  ]
}
```

`requirement_action_candidates` 和 `affected_requirement_transitions` 都以
`requirement_id` 为动态 key。存在 OPEN ambiguity 时，C2/C3 的 action candidate 会从
`APPLY_CHANGES` 变为 `CLARIFY`。

`acceptance_criteria`、`validator_ids` 和 `execution_ready` 只是当前 construction record
中的完整性状态；本文不讨论后续执行或评估。

---

## 9. `RQ1/`–`RQ4/` 文件夹如何落盘

`build_rq_instances()` 返回四个 collection：

```python
{
    "RQ1": [rq1_instance, ...],
    "RQ2": [rq2_instance, ...],
    "RQ3": [rq3_instance, ...],
    "RQ4": [rq4_instance, ...],
}
```

CLI 对每个 collection 执行：

```text
创建 outputs/stage2/<project_id>/<rq_id>/
    |
    +--> 每个 instance 写为 <instance_id>.json
    |
    +--> 汇总并写入 index.json
```

最终目录：

```text
outputs/stage2/<project_id>/
├── rq_instance_manifest.json
├── RQ1/
│   ├── index.json
│   └── <target_id>_RQ1.json
├── RQ2/
│   ├── index.json
│   └── <target_id>_RQ2.json
├── RQ3/
│   ├── index.json
│   └── <target_id>_RQ3.json
└── RQ4/
    ├── index.json
    └── <target_id>_RQ4.json
```

### 9.1 每个文件夹的 `index.json`

四个 index 都使用 `rq-instance-index-v1`：

```json
{
  "schema_version": "rq-instance-index-v1",
  "project_id": "42204309",
  "rq_id": "RQ1",
  "rq_name": "Relevant Requirement Selection",
  "instance_count": 21,
  "difficulty_distribution": {
    "SHORT": 0,
    "MEDIUM": 0,
    "LONG": 21
  },
  "turn_statistics": {
    "minimum": 113,
    "maximum": 784,
    "median": 594
  },
  "instances": [
    {
      "instance_id": "42204309_T001_RQ1",
      "target_id": "42204309_T001",
      "target_message_id": 114,
      "turns": 113,
      "difficulty": "LONG",
      "file": "42204309_T001_RQ1.json"
    }
  ]
}
```

`instances` 是文件夹中当前有效实例的权威列表。生成器重复运行时会覆盖同名实例和
`index.json`，但不会自动删除未被新 index 引用的其他文件。

### 9.2 项目 `rq_instance_manifest.json`

项目 manifest 使用 `rq-instance-manifest-v1`，汇总四个 collection：

```json
{
  "schema_version": "rq-instance-manifest-v1",
  "project_id": "42204309",
  "construction_scope": "RQ_INSTANCES_ONLY_NO_EVALUATION",
  "layout": {
    "project_directory": "outputs/stage2/42204309",
    "rq_directories": ["RQ1", "RQ2", "RQ3", "RQ4"],
    "one_json_file_per_target_rq_pair": true
  },
  "turns_policy": {
    "definition": "number of normalized messages strictly before target_message_id",
    "difficulty_bins": {
      "SHORT": "0-25",
      "MEDIUM": "26-50",
      "LONG": ">50"
    }
  },
  "inclusion_policy": "Create a target/RQ pair when the finalized Task Gold lists the RQ in primary_rq_targets; final RQ-specific eligibility remains pending.",
  "rq_counts": {
    "RQ1": 21,
    "RQ2": 25,
    "RQ3": 18,
    "RQ4": 16
  },
  "total_instance_count": 80,
  "source_artifacts": {},
  "construction_boundaries": {
    "evaluation_implemented": false,
    "rq4_archives_extracted": false,
    "human_review_required": true
  }
}
```

manifest 的 `rq_counts` 必须与四个 `index.json.instance_count` 一致，
`total_instance_count` 必须等于四类实例数之和。

---

## 10. 构造阶段必须通过的校验

以下校验直接决定四个 RQ 文件夹能否生成：

- Gold State、State Graph、normalized messages 的 `project_id` 一致；
- Gold State schema 为 `task-gold-v2`；
- target ID 唯一，`primary_rq_targets` 非空、无重复且只含 RQ1–RQ4；
- target message 存在，speaker/text、turn 数和 conversation position 一致；
- Pre/Post boundary 都与 target message 对齐；
- State reference 存在，State 与 Requirement owner 一致；
- Task Event 存在、来自 target message，Event owner 集合等于 affected Requirements；
- `history_pool` 不含 target，C1/C2/C3 的 message IDs 和计数结构合法；
- 每个构造出的实例使用 `rq-instance-v1`，`construction_gold` 必填；
- RQ4 必须找到对应 Code Environment；
- RQ4 manifest 的 `before_message_id` 与 target 一致；
- project reconstruction validation 必须为 `pass`；
- `pre_repo.zip` 必须通过 CRC、路径穿越、符号链接和 `.git` 检查；
- RQ4 构造阶段不得解压归档。

任一硬校验失败时，生成器停止并报告 target/字段位置，不写一组看似成功但内容不完整的
RQ 实例。

---

## 11. 构造结果的职责边界

本阶段的最终结果只有：

1. `RQ1/`–`RQ4/` 中的 researcher-side instance JSON；
2. 每个文件夹的 `index.json`；
3. 项目级 `rq_instance_manifest.json`。

这些文件说明每个 target/RQ pair 从哪些上游事实构造而来、保存哪些 provisional Gold，
以及哪些人工判断仍未完成。Agent 如何运行、如何返回答案、如何执行代码、如何评分和如何
聚合实验结果不属于本文。

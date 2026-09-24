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

四类 instance 必须遵守以下能力边界：

\[
History
\xrightarrow{RQ1} Relevant\ Evidence
\xrightarrow{RQ2} G(t^-)
\xrightarrow{RQ3} G(t^+)\ \text{or Clarify}
\xrightarrow{RQ4} Code.
\]

其中 RQ2 只构造 Pre-task State Gold；RQ3 才构造 Post-task transition 或 blocking
clarification Gold。不能在 RQ2 中混入 Requirement Selection，也不能让 RQ3 只保存一个没有
Post-state/clarification 依据的 `ACT/CLARIFY` 标签。

当前实现已经生成 RQ1/RQ2/RQ3 v3 response contracts，并复用已有的 Pre/Post State references、
expanded States 与 affected Requirement transitions。RQ1 同时生成确定性的 Atom/Evidence Gold；
任何仍使用旧 contract 的历史 JSON 都必须重新生成，不能与当前 schema 混用。

---

## 2. 从上游产物到四个 RQ 文件夹

### 2.1 输入

构造器读取以下输入：

| 输入 | 构造用途 |
|---|---|
| `outputs/stage2/<project_id>/gold_states.json` | target、Task Events、affected Requirements、Pre/Post State references；历史遗留的 `primary_rq_targets` 不参与实例收录 |
| `outputs/stage2/<project_id>/requirement_state_graph.json` | 展开 State、取得 Event trajectory、Event type 和 provenance |
| `outputs/stage1_runs/<project_id>/normalized_project.json` | target 前完整脱敏历史、稳定消息顺序、speaker 和 text |
| `Code Environment/<project_id>/` | 仅为 RQ4 关联 target 对应的 `pre_repo.zip`、manifest、checksum 和 reconstruction validation |

三份 JSON 输入的 `project_id` 必须一致，Gold State schema 必须是 `task-gold-v2`。

这里的 Code Environment 只是 RQ4 的 researcher-side 构造输入。RQ1、RQ2、RQ3 的实例与公共
输入不得附带 `pre_repo.zip`、解压后的 repository、archive path、代码文件树或 build/test 输出。
`pre_repo.zip` 只能在 RQ1–RQ3 response 冻结之后，由 RQ4 execution gate 定位和开放。

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
                    +--> 检查同一 target 是否有 Code Environment
                    |
                    v
            确定性派生 applicable_rqs
                    |
        +-----------+-----------+-----------+-----------+
        |                       |                       |
      适用 RQ1                适用 RQ2                ...
        |                       |
        v                       v
RQ1/<target>_RQ1.json   RQ2/<target>_RQ2.json
        |
        +--> 各 RQ 文件夹的 index.json
                    |
                    +--> 项目 rq_instance_manifest.json
```

### 2.3 文件夹收录规则

构造器不再读取 `primary_rq_targets` 作为门控，而是从已经校验的 State、Event 和 Code
Environment 确定性派生 candidate `applicable_rqs`：

```python
for task_gold in gold_states["task_gold_states"]:
    relevant_history = relevant_requirement_ids 非空
    affected_transition = target_event_refs 非空
    has_c_env = 同一 target_id 的 Code Environment 存在

    applicable_rqs = []
    if relevant_history:
        applicable_rqs += ["RQ1", "RQ2"]
    if affected_transition:
        applicable_rqs += ["RQ3"]
    if affected_transition and has_c_env:
        applicable_rqs += ["RQ4"]
```

因此：

- 一个 target 可以同时出现在多个 RQ 文件夹；
- RQ1 与 RQ2 使用同一历史相关性条件，因此二者总是成对收录；
- RQ3 只要求当前 task 有可验证的 affected Requirement/Event transition，ACT 和 CLARIFY 都可进入；
- RQ4 candidate 只要求 affected transition 与同一 target 的 C_env；是否可评分在 RQ3 Gold
  冻结后逐 condition 判定；
- 旧 Gold State 中即使仍保留 `primary_rq_targets`，该字段也不会改变收录结果；
- 每个实例顶层保存相同 target 的完整 `applicable_rqs`，不再保存 `diagnostic_rq_tags`；
- 每个 pair 只生成一个 JSON，`instance_id = <target_id>_<rq_id>`；
- 各文件夹中的实例按 `target_message_id` 的规范化对话位置排序。

项目 `42204309` 的当前实际结果是：

| 文件夹 | 实例数 | 来源 |
|---|---:|---|
| `RQ1/` | 25 | 25 个 target 都有 relevant historical Requirement |
| `RQ2/` | 25 | 与 RQ1 使用同一收录集合 |
| `RQ3/` | 25 | 25 个 target 都有 affected target transition |
| `RQ4/` | 17 | 17 个 target 同时具有 affected transition 与同一 target 的 C_env；均为候选实例 |
| 合计 | 92 | target/RQ pair 数，不是唯一 target 数 |

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
```

RQ1 将“一张 Requirement Graph 等于一个 Independent Gold Atom”和 `DIRECT_AFFECTED_ONLY`
作为冻结的操作性定义。继承/保留约束不进入 RQ1 Gold，
`inherited_constraint_requirement_ids` 固定为空，不进行后续人工补充。

对每个直接相关的历史 Requirement，构造器生成：

- `current_support_event_ids`：支持 Pre-task 当前状态的 Events；
- `current_support_message_ids`：上述 Events 的 source 与 target 前 supporting messages 的有序并集；
- `trajectory_event_ids`：target 前该 Requirement 的完整 Event trajectory；
- `trajectory_message_ids`：完整 trajectory 的 source 与 target 前 supporting messages 的有序并集；
- `family_trajectory_message_ids`：同 `family_id` 的全部 Pre-task Requirement trajectories；无
  family 时等于本 Requirement trajectory；
- `core_message_ids`：与 current-support messages 相同，作为兼容字段；
- `required_evidence_groups`：每个 current-support Event 对应一个确定性 group，组内包含该
  Event 在 target 前可见的 source/supporting message alternatives；重叠 groups 会合并；
- `neutral_context_message_ids`：family trajectory 中不属于本 Atom current support 的消息；
- `context_review_status=DETERMINISTIC_FAMILY_TRAJECTORY_CONTEXT`。

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

- `C1`：`history_pool` 中的全部消息 ID（Full History）；
- `C2`：相关 Requirement trajectory 对应的有序消息 ID（Oracle Relevant History）。

构造器不再生成 No-History condition。该输入不符合“接手进行中的项目”的 benchmark 单位，
也不能进入 RQ1–RQ4 的正式实例、分母或主结果。

各 RQ 的 availability 不相同：

| RQ | C1 | C2 |
|---|---|---|
| RQ1 | available | unavailable |
| RQ2 | available | available |
| RQ3 | available | available |
| RQ4 candidate | available | available |

所有正式条件都提供 target 之前的项目历史。RQ1 只在 C1 下运行，因为其任务本身就是从完整历史中
识别相关 Requirement 与证据；C2 由 RQ1 Gold 构造，不能反过来作为 RQ1 输入。RQ2–RQ4 则比较
完整历史与 Oracle 相关历史。本文只说明这些字段怎样构造，不讨论运行或评估方式。

RQ4 在这里的 `available` 只表示该 condition 可以拥有候选输入，不表示它已经可以评分。正式
RQ4 eligibility 必须在 RQ3 Gold 冻结后逐 condition 判定；不满足 gate 的候选实例不产生
`PASS`/`FAIL`。

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
  "applicable_rqs": ["RQ1", "RQ2", "RQ3", "RQ4"],
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
      "available": true,
      "history_mode": "FULL_HISTORY",
      "history_message_ids": [1],
      "history_message_count": 1,
      "review_status": "DETERMINISTIC"
    },
    "C2": {
      "available": false,
      "history_mode": "ORACLE_RELEVANT_HISTORY",
      "history_message_ids": [1],
      "history_message_count": 1,
      "review_status": "DETERMINISTIC_DIRECT_TRAJECTORY_ONLY"
    }
  },
  "response_contract": {},
  "visibility": {
    "record_kind": "RESEARCHER_SIDE_CONSTRUCTION_INSTANCE",
    "runner_must_hide": [
      "construction_gold",
      "source_artifacts"
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
| `applicable_rqs` | 由确定性规则派生；必须包含当前实例的 `rq_id`，无重复且只含 RQ1–RQ4 |
| `turns` | target 前的规范化消息数 |
| `history_turn_count` | 必须等于 `turns` |
| `difficulty` | `0–25 -> SHORT`，`26–50 -> MEDIUM`，`>50 -> LONG` |
| `history_pool.message_count` | 必须等于 `messages` 数量和 `turns` |
| `target_message_id` | 不得出现在 `history_pool` 中 |
| `construction_gold` | 必填；具体结构由 RQ 类型决定 |

RQ4 不要求 Agent 返回 `decision` 或 `planned_actions`。其 `response_contract` 只声明最终
repository 是被评分产物；结构化文字回复不参与正式评分。

---

## 5. RQ1 实例如何构建

### 5.1 收录条件

当 `relevant_requirement_ids` 至少包含一个 target 前已存在的历史 Requirement 时生成：

```text
outputs/stage2/<project_id>/RQ1/<target_id>_RQ1.json
```

### 5.2 构造步骤

1. 从 `affected_requirement_ids` 中找出 Pre-task snapshot 已存在的 Requirements；
2. 将 target 首次引入、Pre-task 不存在的 Requirements 单独放入 `new_requirement_ids`；
3. 对每个历史 Requirement 从 State Graph 提取当前支持 Events；
4. 提取该 Requirement 以及同 family Requirements 在 target 前的完整 Event trajectories；
5. 将每个 Event 的 source 与 target 前可见的 `supporting_message_ids` 映射为有序 message IDs；
6. 每个 current-support Event 形成一个 `required_evidence_group`，共享 message 的 groups 合并；
7. 将 family trajectory 中不属于本 Atom current support 的消息构造成
   `neutral_context_message_ids`；
8. 按“一张 Requirement Graph 等于一个 Independent Gold Atom”构造
   `gold_requirement_atoms`；
9. 使用 `DIRECT_AFFECTED_ONLY` 冻结 Gold，不追加 inherited/preserved Requirements，也不进入
   Human Review。

RQ1 文件的核心不是重复保存完整 State，而是保存“哪些历史 Requirements 相关，以及相关
证据来自哪些 Event/message”。

### 5.3 RQ1 `construction_gold` schema

```json
{
  "status": "DETERMINISTIC_RQ1_GOLD",
  "gold_unit": "INDEPENDENT_REQUIREMENT_ATOM",
  "atomization_rule": "ONE_REQUIREMENT_GRAPH_EQUALS_ONE_GOLD_ATOM",
  "relevant_requirement_ids": [
    "REQ_BADGE_CATALOG_AND_PRESENTATION"
  ],
  "gold_requirement_atoms": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "canonical_summary": "Badge Catalog and Presentation",
      "requirement_title": "Badge Catalog and Presentation",
      "family_id": "ACHIEVEMENT_SYSTEM",
      "required_evidence_groups": [
        {
          "group_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_EG001",
          "acceptable_message_ids": [99, 101]
        }
      ],
      "neutral_context_message_ids": [85],
      "trajectory_message_ids": [85, 99, 101],
      "family_trajectory_message_ids": [72, 85, 99, 101]
    }
  },
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
      "current_support_message_ids": [99, 101],
      "trajectory_event_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E001",
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E002"
      ],
      "trajectory_message_ids": [85, 99, 101],
      "family_trajectory_message_ids": [72, 85, 99, 101],
      "core_message_ids": [99, 101],
      "required_evidence_groups": [
        {
          "group_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_EG001",
          "acceptable_message_ids": [99, 101]
        }
      ],
      "context_message_ids": [72, 85],
      "neutral_context_message_ids": [72, 85],
      "context_review_status": "DETERMINISTIC_FAMILY_TRAJECTORY_CONTEXT"
    }
  },
  "derivation_scope": "DIRECT_AFFECTED_ONLY",
  "review_status": "DETERMINISTIC_DIRECT_AFFECTED_ONLY"
}
```

`required_evidence_groups` 是正式 Evidence Recall 的 Gold 单位。当前自动构造把同一 Event 的
source/supporting messages 作为同组 alternatives；覆盖其中任一 ID 仍只计一个 TP。
`neutral_context_message_ids` 既不计 TP 也不计 FP。完整本 Requirement trajectory 继续用于 C2，
family trajectory 用于扩大确定性的 neutral 边界与审计，但二者都不会全部强制成为 Evidence FN。

RQ1 response contract 为 `rq1-agent-response-v3`。RQ1 的最小 projection 只要求：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "...",
      "evidence_message_ids": [101]
    }
  ]
}
```

统一 Agent response 可以在顶层同时包含 `decision`、`post_task_states`、`clarifications`，并在
每个 Requirement 中包含 `pre_task_state`；这些是声明白名单中的字段，不会被 RQ1 scorer 拒绝。
scorer 验证后投影出上面的三个 RQ1 字段。未声明字段仍严格拒绝。不再要求冗余的
`selected_history_message_ids`。`requirement_ref` 必须唯一且不能使用内部 `REQ_*` ID，evidence
IDs 必须来自 C1 history。

---

## 6. RQ2 实例如何构建

### 6.1 收录条件

当 `relevant_requirement_ids` 非空时生成：

```text
outputs/stage2/<project_id>/RQ2/<target_id>_RQ2.json
```

RQ2 与 RQ1 使用同一 target 集合，正式 condition 包括 C1/C2，且两者都必须提供历史。

### 6.2 构造目标与边界

RQ2 构造：

\[
Relevant\ Historical\ Requirements \rightarrow G(t^-).
\]

它只保存 target 到来前已经成立的状态，具体边界由 Task Gold 的
`pre_task_state.before_message_id == target_message_id` 确定。

RQ2 不构造或评价：

- relevant Requirement 的 selection 正误；
- 当前 target 首次引入的新 Requirement 的虚构 Pre-state；
- target Event 产生的 Post-task change；
- `ACT/CLARIFY` decision；
- code action。

### 6.3 Requirement 集合如何形成

构造器依次执行：

1. 从 RQ1 construction Gold 读取确定性 `relevant_requirement_ids`；
2. 保留其中在 Pre-task snapshot 已经存在的 historical Requirements；
3. 不添加 inherited/preserved Requirements；
4. 把 target 首次引入、Pre-task 不存在的 Requirements 放入 `new_requirement_ids`；
5. 断言 `gold_requirement_ids` 与 `new_requirement_ids` 不重叠；
6. 只为 `gold_requirement_ids` 构造 `states`。

`gold_requirement_ids` 是 RQ2 可以评分的 Gold 范围，但 Agent 最终只会在与这些 Gold
Requirements 成功对齐的 matched subset 上获得 RQ2 state score。selection 的 FN/FP 留在
RQ1，不通过构造伪造第二次惩罚。

### 6.4 Pre-task State 展开

对每个 `gold_requirement_id`：

1. 在 Task Gold 的 Pre-task snapshot 中读取 `state_id`；
2. 从 Requirement State Graph 定位该 State；
3. 展开 `attributes`、`scope`、`lifecycle_status`、`ambiguity` 和 `execution`；其中
   `ambiguity` 规范化为 `null` 或 record array，不再以 Event ID 作动态 key；
4. 把 title/family/state/event provenance 单独保存，供 evaluator 对齐和审计，不混入可评分
   State；
5. 校验所有 `supporting_event_ids` 的 source message 均严格早于 target；
6. 禁止读取 Post-task State 的新值回填 Pre-task State。

当前 task 文本只用于决定哪些 historical Requirements 相关，不是 RQ2 的状态来源。例如
target 说 “Change prize to 500”，RQ2 Gold 必须仍保存修改前的 `prize_amount_usd`，而不是
`500`。

### 6.5 Typed field scoring spec

仅保存原始 State JSON 不足以稳定评价复杂 attributes。每个 RQ2 instance 还必须为可评分
field 保存 comparator metadata。默认规则如下：

| 数据角色 | comparator |
|---|---|
| boolean | `BOOLEAN_EXACT` |
| 闭合 enum（lifecycle、persistence、status、dimension） | `NORMALIZED_EXACT` |
| integer / amount / threshold | `NUMBER_EXACT` |
| unordered collection | `SET_F1` |
| nested object | `RECURSIVE_FIELDS`，默认 closed-world |
| unordered record array | `UNORDERED_RECORD_F1`，最大权一对一匹配 |
| natural-language Requirement fact | `SEMANTIC_FACT`，API Judge 只返回离散等价关系 |
| Gold 明确允许误差的数值 | `NUMERIC_TOLERANCE`，必须保存 tolerance |
| 未标注/不可靠的 unknown null | `SKIP`，`score=false` |

构造器可以根据 JSON 类型生成初始 comparator candidate，但以下内容必须人工审核：

- array 是 set 还是 ordered sequence；
- free text 应拆成哪些 atomic facts；
- 数值是否允许 tolerance；
- `null` 表示不适用、未知还是明确为空；未知不得用 `NULL_EXACT` 给常量预测器送分；
- 哪些 field 因 Gold 不可靠而排除评分。

构造器必须通过 enum path 白名单分配 comparator，不能使用“凡 string 均走语义 Judge”的
类型启发式。任何 `source_event_id`、Event ID、State ID 或 Requirement ID 路径都必须
`score=false`，并在 schema validation 中禁止进入可评分 State。

未完成 comparator review 的 instance 可以生成，但必须保持 provisional，不能用于正式 RQ2
分数。

### 6.6 RQ2 `response_contract`

目标 contract 使用显式的 `pre_task_state`，避免把它误解为 target 之后的 current state：

```text
Question:
For each relevant historical requirement, reconstruct only the state that was
valid immediately before the current client task. Do not apply the current task.
```

```json
{
  "schema_version": "rq2-agent-response-v3",
  "required_fields": ["requirements"],
  "required_requirement_item_fields": [
    "requirement_ref",
    "requirement_summary",
    "evidence_message_ids",
    "pre_task_state"
  ],
  "pre_task_state_fields": [
    "attributes",
    "scope",
    "lifecycle_status",
    "ambiguity",
    "execution"
  ],
  "ambiguity_representation": "NULL_OR_ARRAY_OF_RECORDS",
  "complete_state_closed_world": true,
  "unexpected_state_fields_are_false_positives": true,
  "internal_ids_forbidden": true
}
```

遗留 v1/v2 输出必须迁移并重新生成，不能与 v3 混用。

### 6.7 RQ2 `construction_gold` schema

```json
{
  "status": "PROVISIONAL_REQUIRES_FIELD_REVIEW",
  "gold_requirement_ids": [
    "REQ_BADGE_CATALOG_AND_PRESENTATION"
  ],
  "new_requirement_ids": [
    "REQ_BADGE_AWARD_ACCURACY"
  ],
  "states": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "attributes": {},
      "scope": {
        "persistence": "PROJECT_PERSISTENT",
        "components": ["FRONTEND", "UI_UX"],
        "contexts": ["BADGES"]
      },
      "lifecycle_status": "ACTIVE",
      "ambiguity": null,
      "execution": null
    }
  },
  "state_provenance": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
      "supporting_event_ids": ["REQ_BADGE_CATALOG_AND_PRESENTATION_E002"]
    }
  },
  "state_dimensions": [
    "attributes",
    "lifecycle_status",
    "scope",
    "ambiguity",
    "execution"
  ],
  "field_scoring_specs": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "attributes": {
        "badge_labels": {
          "type": "unordered_set",
          "comparator": "SET_F1",
          "score": true
        }
      },
      "scope": {
        "persistence": {"comparator": "EXACT", "score": true},
        "components": {"comparator": "SET_F1", "score": true},
        "contexts": {"comparator": "SET_F1", "score": true}
      },
      "lifecycle_status": {"comparator": "EXACT", "score": true},
      "ambiguity": {"comparator": "STRUCTURED_AMBIGUITY", "score": true},
      "execution": {"comparator": "STRUCTURED_EXECUTION", "score": true}
    }
  },
  "scoring_scope": {
    "selection_scored_here": false,
    "matched_requirements_only": true,
    "report_reconstruction_coverage_separately": true,
    "no_matched_requirement_result": "N/A"
  },
  "review_status": "DETERMINISTIC_DIRECT_AFFECTED_ONLY"
}
```

`states` 仍以 researcher-side `requirement_id` 为动态 key，但其 value 只包含五个语义
dimensions。内部 ID 与 supporting Events 进入独立 provenance；Agent 不会看到动态 key 或
provenance。`ambiguity` 只能为 `null` 或 array，数组元素中不得出现 Event ID。

`state_dimensions` 不再包含 `selection`。`field_scoring_specs` 同样以 Requirement 和 field
为动态 key；它决定 evaluator 如何比较状态，但不提供给 Agent。

### 6.8 RQ2 构造完成条件

正式 RQ2 Gold 至少满足：

- relevant/inherited Requirement review 已完成；
- `states` 只包含 Pre-task historical Requirements；
- 每个 State 的 provenance 严格早于 target；
- C1/C2 available；
- 每个可评分 leaf field 有明确 comparator；
- free-text atomic facts 已审核；
- `new_requirement_ids` 不进入 State 分母。

---

## 7. RQ3 实例如何构建

### 7.1 收录条件

当当前 task 至少有一个 affected Requirement，并且每个 affected Requirement 都能映射到来自
target message 的 Task Event 时生成：

```text
outputs/stage2/<project_id>/RQ3/<target_id>_RQ3.json
```

RQ3 的收录条件不等于 Gold 必须为 ACT。ACT 与 CLARIFY 都是 Update-or-Clarify 的有效 branch；
构造时先从 affected Post State 的 OPEN ambiguity 得到 project decision candidate，后续再冻结
condition-specific Gold。

### 7.2 构造目标

RQ3 构造：

\[
G(t^-)+q_t
\longrightarrow
\begin{cases}
G(t^+) & \text{ACT}\\
Clarification & \text{CLARIFY}.
\end{cases}
\]

因此，一个可正式评估的 RQ3 instance 不能只有 `ACT/CLARIFY` 标签。它还必须包含：

- ACT branch：affected Requirements 的完整 Pre/Post transition Gold；
- CLARIFY branch：结构化 blocking issues 和可接受问题的语义范围；
- 每个 condition 的最终 branch；
- 所有自动候选到人工冻结结果的 review provenance。

### 7.3 Affected Requirement transition 构造

RQ3 复用 RQ4 的 transition helper，但不关联代码：

1. 校验 `task_event_ids` 全部来自 target message；
2. 校验 Event owner 集合等于 `affected_requirement_ids`；
3. 对已有 Requirement 展开 Pre-task 和 Post-task State；
4. 对新 Requirement 使用 `before = null`，并展开其第一个 Post-task State；
5. 比较 `attributes`、`scope`、`lifecycle_status`、`ambiguity`、`execution`；
6. 生成 `delta.change_type`、dimension-level `changed_fields`、field-level `changed_paths` 与
   `removed_paths`；例如删除 `big_block_ticket_cycle` 记录为
   `attributes.big_block_ticket_cycle`；
7. 把 State/Event ID 保存到独立 `state_provenance`，不混入 before/after 可评分 State；
8. 保存 target Events，说明 transition 是由哪个当前 task 事实触发的。

RQ3 必须保存完整 Post-task State，而不是只保存 changed fields。这样 evaluator 才能检查 Agent
是否既应用了新要求，又保留了未被 target 覆盖的有效字段。Agent 输出中，被删除属性必须从
完整 State 省略，并显式列入 `removed_attribute_keys`；完整 State 的额外旧字段按 closed-world
规则计 false positive。

### 7.4 Blocking ambiguity candidates

构造器从 affected Post States、target Events、Pre-task OPEN ambiguities 和 condition evidence
中产生候选。每个候选至少包含：

```json
{
  "requirement_id": "REQ_PRIZE_CLAIM_FLOW",
  "dimension": "VALUE",
  "field": "prize_amount_usd",
  "candidate_values": [300, 500],
  "missing_information": "The target leaves two incompatible values unresolved.",
  "source_event_ids": ["REQ_PRIZE_CLAIM_FLOW_E003"],
  "materiality": "PENDING_REVIEW",
  "resolvable_from_visible_evidence": "PENDING_REVIEW",
  "blocking_status": "PENDING_MATERIALITY_REVIEW"
}
```

允许的 `dimension` 至少包括：

```text
VALUE
SCOPE
LIFECYCLE
BEHAVIOR
DEPENDENCY
EXECUTION
```

OPEN ambiguity 只是候选。只有满足以下条件才冻结为 blocking Gold：

- 与当前 task 或必须继承的约束有关；
- 不同答案会形成不同的 material Post-task State 或实现；
- 当前 condition 的可见证据不能唯一消解；
- Agent 不能在不假设答案的情况下安全完成整个 target。

第三方账户、凭据、KYC 或服务配置等问题应使用 `DEPENDENCY`；如果本地 mock 已足以完成当前
Requirement，则不得仅因为没有真实外部服务而自动标成 CLARIFY。

### 7.5 Condition-specific decision candidate

自动构造阶段为 C1/C2 生成 candidate：

- 如果该 condition 存在 material blocking issue，candidate 为 `CLARIFY`；
- 如果所有 affected Requirements 都能形成唯一 Post-state，candidate 为 `ACT`；
- 自动逻辑无法判断 evidence sufficiency 时为 `null` 并进入人工审核。

C1 与 C2 都包含判定当前任务所需的历史证据，因此必须得到相同的 decision Gold 和同一份
Post-task State（ACT）或 blocking clarifications（CLARIFY）。自动构造时先形成项目级 candidate，
再复制到两个 condition；若二者不一致，应视为 Oracle 历史构造或审核错误，而不是条件效应。

### 7.6 人工审核与 branch 冻结

至少两名不同审核者完成 adjudication 后，每个 condition 必须冻结为以下两个互斥 branch
之一。C1/C2 使用同一语义 Gold；人工审核应验证 C2 已保留形成该 Gold 所需的全部证据。

ACT branch：

```json
{
  "decision": "ACT",
  "post_task_states": {
    "REQ_SMALL_BLOCK_PRIZE": {
      "requirement_id": "REQ_SMALL_BLOCK_PRIZE",
      "attributes": {"prize_amount_usd": 500},
      "scope": {},
      "lifecycle_status": "ACTIVE",
      "ambiguity": null,
      "execution": null
    }
  },
  "blocking_clarifications": []
}
```

CLARIFY branch：

```json
{
  "decision": "CLARIFY",
  "post_task_states": null,
  "blocking_clarifications": [
    {
      "requirement_id": "REQ_SMALL_BLOCK_PRIZE",
      "dimension": "VALUE",
      "field": "prize_amount_usd",
      "missing_information": "The final amount is not uniquely specified.",
      "acceptable_question_facts": [
        "ask client to choose the final small-prize amount"
      ]
    }
  ]
}
```

`post_task_states` 与 `blocking_clarifications` 必须互斥：ACT 时前者非空、后者为空；CLARIFY
时前者为 `null`、后者至少一项。带 OPEN ambiguity 的 State Graph snapshot 可以作为候选证据，
但不能冒充 CLARIFY branch 中唯一确定的 Post-state。

### 7.7 RQ3 `response_contract`

RQ3 目标输出升级为：

```text
Question:
Using the reconstructed pre-task state and the current client task, either
construct the complete post-task state for every affected requirement or ask
the concrete clarification needed to make that state unique.
```

```json
{
  "schema_version": "rq3-agent-response-v3",
  "required_fields": [
    "decision",
    "post_task_states",
    "clarifications"
  ],
  "decision_values": ["ACT", "CLARIFY"],
  "branch_constraints": {
    "ACT": {
      "post_task_states": "NON_EMPTY_ARRAY",
      "clarifications": "EMPTY_ARRAY"
    },
    "CLARIFY": {
      "post_task_states": "NULL",
      "clarifications": "NON_EMPTY_ARRAY"
    }
  },
  "clarification_item_fields": [
    "requirement_ref",
    "requirement_summary",
    "dimension",
    "field",
    "missing_information",
    "question"
  ],
  "post_task_state_item_fields": [
    "requirement_ref",
    "requirement_summary",
    "change_type",
    "removed_attribute_keys",
    "state"
  ],
  "state_fields": [
    "attributes",
    "scope",
    "lifecycle_status",
    "ambiguity",
    "execution"
  ],
  "ambiguity_representation": "NULL_OR_ARRAY_OF_RECORDS",
  "complete_state_closed_world": true,
  "unexpected_state_fields_are_false_positives": true,
  "internal_ids_forbidden": true
}
```

ACT branch 的每个 `post_task_states` item 还必须包含 `requirement_ref`、
`requirement_summary`、`change_type`、`removed_attribute_keys` 和完整 `state`。对 target 首次引入的 Requirement，
`requirement_summary` 是 evaluator 建立对齐的必要字段。clarification 中的 `field` 必须存在，
但 Gold 确实无法定位单一字段时允许为 `null`。

遗留 rq3 response v1/v2 无法表达完整的 closed-world State 与删除声明，必须重新生成。

### 7.8 RQ3 provisional `construction_gold`

自动构造、尚未完成人工 review 时使用：

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
      "value": "CLARIFY",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    },
    "C2": {
      "value": "CLARIFY",
      "status": "PENDING_BLOCKING_AMBIGUITY_REVIEW"
    }
  },
  "blocking_ambiguity_candidates": [
    {
      "requirement_id": "REQ_PRIZE_CLAIM_FLOW",
      "ambiguity_event_id": "REQ_PRIZE_CLAIM_FLOW_E003",
      "dimension": "VALUE",
      "field": "prize_amount_usd",
      "description": "...",
      "source_event_id": "REQ_PRIZE_CLAIM_FLOW_E003",
      "blocking_status": "PENDING_MATERIALITY_REVIEW"
    }
  ],
  "affected_requirement_transitions": {
    "REQ_PRIZE_CLAIM_FLOW": {
      "before": {},
      "after": {},
      "delta": {
        "change_type": "MODIFIED",
        "changed_fields": ["attributes", "ambiguity"]
      }
    }
  },
  "final_gold_by_condition": {
    "C1": null,
    "C2": null
  },
  "safe_subactions": [],
  "safe_subactions_review_status": "PENDING_MULTI_REQUIREMENT_REVIEW",
  "relevance_review_status": "DETERMINISTIC_DIRECT_AFFECTED_ONLY",
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

### 7.9 RQ3 frozen `construction_gold`

完成 review 后：

```json
{
  "status": "FINAL_UPDATE_OR_CLARIFY_GOLD",
  "affected_requirement_transitions": {
    "REQ_SMALL_BLOCK_PRIZE": {
      "before": {},
      "after": {},
      "delta": {
        "change_type": "MODIFIED",
        "changed_fields": ["attributes"]
      }
    }
  },
  "final_gold_by_condition": {
    "C1": {
      "decision": "ACT",
      "post_task_states": {
        "REQ_SMALL_BLOCK_PRIZE": {}
      },
      "blocking_clarifications": []
    },
    "C2": {
      "decision": "ACT",
      "post_task_states": {
        "REQ_SMALL_BLOCK_PRIZE": {}
      },
      "blocking_clarifications": []
    }
  },
  "post_state_scoring_specs": {},
  "review_status": "HUMAN_REVIEWED_AND_FROZEN"
}
```

ACT branch 的 `post_task_states` 必须从 `affected_requirement_transitions.*.after` 完整复制，示例
中的 `{}` 只是省略展示。`post_state_scoring_specs` 复用 RQ2 typed comparator 规则。

### 7.10 RQ3 构造完成条件

正式 RQ3 Gold 至少满足：

- affected Requirement 集合与 target Events 一致；
- 每个 transition 的 before/after boundary 正确；
- C1/C2 都有人工冻结且相同的 branch；
- ACT branch 具有完整、唯一的 Post-task States 和 scoring specs；
- CLARIFY branch 具有 Requirement、dimension、field、missing information 与可接受问题语义；
- OPEN ambiguity 已通过 relevance、materiality、resolvability review；
- C1/C2 的 decision、Post-state 或 blocking clarifications 完全一致；
- `safe_subactions` 不进入第一版主评分，也不会绕过项目级 CLARIFY gate。

---

## 8. RQ4 实例如何构建

### 8.1 候选实例收录条件

当且仅当同时满足以下两个条件时生成 RQ4 candidate：

1. RQ3 存在至少一个 affected Requirement transition；
2. `Code Environment/<project_id>/` 中存在同一 `target_id` 的 C_env manifest 与 `pre_repo.zip`。

生成路径为：

```text
outputs/stage2/<project_id>/RQ4/<target_id>_RQ4.json
```

RQ4 实例在公共 schema 基础上额外要求 `code_environment`。候选实例不进入正式分母，也不产生
`PASS`/`FAIL`；正式 eligibility 在 §8.5 按 condition 判定。

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
5. 保存 transition provenance，供 acceptance criteria 的人工设计和复核使用。

RQ4 不再派生或评分 `IMPLEMENT/MODIFY/REMOVE/PRESERVE` action。是否交付成功只由最终 repository
上的 hidden tests 决定；transition metadata 仅是 researcher-side provenance。

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
  "extracted_during_instance_construction": false,
  "rq4_repository_audit": {
    "future_state_leakage": "PENDING",
    "validator_leakage": "PENDING",
    "reference_delivery_leakage": "PENDING",
    "evaluator_metadata_leakage": "PENDING"
  }
}
```

`requirements_to_code`、State IDs 和 audit 结果属于 researcher-side metadata，不得写入任何
Agent workspace。`pre_repo.zip` 也不是 RQ2/RQ3 输入；即使其中的 pre-task 实现反映了部分
历史状态，也只能在 Phase A 的 RQ1–RQ3 response 已冻结后用于 RQ4。RQ4 repository 仍须通过
独立泄漏审计，不能包含 future/post-task state、acceptance criteria、hidden validator、reference
delivery 或 evaluator-only Requirement/State/Event metadata。

### 8.4 RQ4 `construction_gold` schema

```json
{
  "status": "RQ4_EXECUTION_READY",
  "affected_requirement_transitions": {
    "REQ_BADGE_CATALOG_AND_PRESENTATION": {
      "before": {
        "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
        "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002",
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      },
      "after": {
        "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
        "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S003",
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      },
      "delta": {
        "change_type": "MODIFIED",
        "changed_fields": ["attributes"]
      }
    }
  },
  "eligibility_by_condition": {
    "C1": {
      "rq3_gold_decision": "ACT",
      "rq4_eligible": true,
      "exclusion_reason": null
    },
    "C2": {
      "rq3_gold_decision": "ACT",
      "rq4_eligible": true,
      "exclusion_reason": null
    }
  },
  "acceptance_criteria_ids": ["AC001", "AC002"],
  "validator": {
    "validator_id": "42204309_T001_RQ4_V1",
    "validator_sha256": "...",
    "calibration_complete": true
  },
  "repository_leakage_check_passed": true,
  "execution_ready": true
}
```

`affected_requirement_transitions` 以 `requirement_id` 为动态 key。示例表示 validator 已完成人工
设计与校准后的最终状态；在此之前，`eligibility_by_condition` 可保持 `null`，`execution_ready`
必须为 `false`，`status` 必须为 `RQ4_CANDIDATE`，且不能运行正式实验。

### 8.5 Eligibility 与完成条件

RQ3 Gold 冻结后，对每个 condition 分别检查：

1. `final_gold_by_condition.decision == ACT`；
2. pre-repo 可重复完成环境启动、Build 和 Regression；
3. target 存在可由本地确定性测试观察的外部行为或交付 artifact；
4. acceptance criteria 与 hidden validator 已由人工预先设计、双人复核并冻结；
5. validator 已通过 pre-repo、reference delivery，以及适用时的 partial delivery 校准；
6. Agent 可见 repository 已通过 future/post-task state、validator、reference delivery 和
   evaluator-only metadata 泄漏审计。

全部满足时才写入 `rq4_eligible=true`。若不满足，只记录一个排除原因，不生成评分结果。允许的
排除原因与 `DESIGN_RQ_evaluation.md` §6.2 一致。只有纯配置镜像、自由文本匹配、主观视觉判断
或必须依赖外部语义 API 的 target 不进入主 RQ4。

RQ4 构造完成的最低条件是：condition-specific RQ3 Gold 已冻结、eligibility 已确定、eligible
condition 共用同一冻结 validator、校准与泄漏审计均通过。评分只接受最终 repository，不读取
`decision`、`planned_actions` 或 action 文本。

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
  "inclusion_policy": "Derive candidates deterministically: RQ1 and RQ2 require a relevant historical Requirement; RQ3 requires an affected target transition; RQ4 candidate requires an affected target transition and a matching target Code Environment.",
  "applicability_policy": {
    "RQ1": "HAS_RELEVANT_HISTORICAL_REQUIREMENT",
    "RQ2": "HAS_RELEVANT_HISTORICAL_REQUIREMENT",
    "RQ3": "HAS_AFFECTED_TARGET_TRANSITION",
    "RQ4": "AFFECTED_TRANSITION_AND_MATCHING_CODE_ENVIRONMENT"
  },
  "rq_counts": {
    "RQ1": 25,
    "RQ2": 25,
    "RQ3": 25,
    "RQ4": 17
  },
  "total_instance_count": 92,
  "rq4_readiness": {
    "candidate_count": 17,
    "eligible_target_condition_count": 0,
    "eligibility_status": "PENDING_RQ3_GOLD_AND_VALIDATOR_CALIBRATION"
  },
  "source_artifacts": {},
  "construction_boundaries": {
    "evaluation_implemented": false,
    "rq4_archives_extracted": false,
    "human_review_required": true
  }
}
```

manifest 的 `rq_counts` 必须与四个 `index.json.instance_count` 一致，
`total_instance_count` 必须等于四类实例数之和。`RQ4` 的 instance count 是候选 target 数，不能
当作正式 RQ4 样本量；正式分母来自 `eligible_target_condition_count`。

---

## 10. 构造阶段必须通过的校验

以下校验直接决定四个 RQ 文件夹能否生成：

- Gold State、State Graph、normalized messages 的 `project_id` 一致；
- Gold State schema 为 `task-gold-v2`；
- target ID 唯一；旧 `primary_rq_targets` 即使存在也不参与构造；
- target message 存在，speaker/text、turn 数和 conversation position 一致；
- Pre/Post boundary 都与 target message 对齐；
- State reference 存在，State 与 Requirement owner 一致；
- Task Event 存在、来自 target message，Event owner 集合等于 affected Requirements；
- `history_pool` 不含 target，C1/C2 的 message IDs 和计数结构合法；
- `applicable_rqs` 无重复、只含 RQ1–RQ4，并且包含当前实例的 `rq_id`；
- RQ1/RQ2 仅在 relevant historical Requirement 非空时收录；
- RQ3 仅在 affected target transition 非空时收录；
- RQ4 candidate 仅在 affected transition 非空且存在匹配 C_env 时收录；
- 每个构造出的实例使用 `rq-instance-v1`，`construction_gold` 必填；
- RQ1 Gold 状态为 `DETERMINISTIC_RQ1_GOLD`，Atom keys 与 relevant Requirement IDs 完全一致；
- RQ1 每个 Atom 至少有一个 required evidence group，required/context IDs 都来自 C1 history，
  且二者不重叠；
- RQ2 的 C1/C2 均 available，且 `states` 不含 `new_requirement_ids`；
- RQ2 的 `state_dimensions` 不含 selection，每个可评分 leaf field 有 comparator；
- RQ3 的 affected transitions 与 target Events 一致；
- RQ3 每个 condition 的 ACT/CLARIFY branch 互斥且通过人工冻结；
- RQ3 的 C1/C2 使用相同 Gold branch；
- RQ3 ACT branch 含完整 Post-task States，CLARIFY branch 含结构化 blocking clarification；
- RQ1–RQ3 的公共输入不引用或附带 Code Environment、repository、archive path 或 build/test 输出；
- RQ4 必须找到对应 Code Environment；
- RQ4 manifest 的 `before_message_id` 与 target 一致；
- project reconstruction validation 必须为 `pass`；
- RQ4-only `pre_repo.zip` 必须通过 CRC、路径穿越、符号链接和 `.git` 检查；
- RQ4 构造阶段不得解压归档；
- RQ4 eligibility 只能在 condition-specific RQ3 Gold 冻结后确定；
- `rq4_eligible=true` 时必须存在冻结的 acceptance criteria、validator ID/hash、完整校准记录和
  通过的 RQ4 future-state/validator/reference-delivery/evaluator-metadata leakage audit；
- 同一 target 的 eligible conditions 必须使用同一 validator；
- 不得出现 `rq4_eligible=false` 却带有 `PASS`/`FAIL`，或 `rq4_eligible=true` 却缺失执行准备材料。

任一硬校验失败时，生成器停止并报告 target/字段位置，不写一组看似成功但内容不完整的
RQ 实例。

---

## 11. 构造结果的职责边界

本阶段的最终结果只有：

1. `RQ1/`–`RQ4/` 中的 researcher-side instance JSON；
2. 每个文件夹的 `index.json`；
3. 项目级 `rq_instance_manifest.json`。

这些文件说明每个 target/RQ pair 从哪些上游事实构造而来。RQ1 保存无需人工复核的确定性
Atom/Evidence Gold；RQ2/RQ3 可保存各自的 provisional Gold；RQ4 保存 candidate、eligibility
和 validator provenance，但不在本阶段执行 Agent 或写入评分。Agent 如何运行、如何执行代码
以及如何聚合实验结果不属于本文；各 RQ 的评分接口以 `DESIGN_RQ_evaluation.md` 为准。

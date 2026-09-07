# Stage 2 `gold_state.py`：LLM 目标时间选择与 Gold State 生成设计

## 1. 文档状态与范围

本文是 `Code/stage2/gold_state.py` 当前 LLM target-selection 实现的设计契约。实现在不改变
Requirement State Graph 回放语义的前提下，将现有的“事件优先级 + 时间段配额 +
随机种子”Task 抽样替换为：

```text
规则生成候选
    -> 构建候选发生前的 Requirement 上下文
    -> 每个候选一次 LLM 语义评估
    -> 确定性推荐过滤
    -> 默认：确定性覆盖与去重 -> 人工 ACCEPT / REJECT / ADD_BACK
       或：AI 分数线筛选 -> 跳过人工复核
    -> selected_target_times.json
    -> 确定性 Pre/Post Gold State 回放
```

本文只设计 Stage 2.2。它不重新识别 Requirement、不修改 Stage 1 Event、
不修补 Requirement State Graph，也不让 LLM 生成 Gold State。

## 2. 与当前仓库的对应关系

### 2.1 实际输入

附件中的三个逻辑输入在当前仓库中对应为：

| 逻辑输入 | 当前仓库文件 | 本阶段用途 |
|---|---|---|
| 完整有效消息序列 | `outputs/stage1_runs/<project_id>/normalized_project.json` | Candidate 原文、speaker、全局顺序、`history_turn_count` |
| Stage 1 annotation | `outputs/stage1_annotations/<project_id>_stage1_annotation.json` | 完整 Event payload、Requirement 元数据、Event 与消息引用 |
| Requirement State Graph | `outputs/stage2/<project_id>/requirement_state_graph.json` | Pre-task State、Requirement 历史轨迹、最终 Gold 回放 |

不直接读取 `Datasets/project/<project_id>/chat_messages.json`。Stage 1 已经把有效、
脱敏且有稳定顺序的消息保存到 `normalized_project.json`，重复读取原始聊天会绕过
Stage 1 的规范化和 PII 边界。

三份输入的 `project_id` 必须一致。State Graph Event 与 Stage 1 Event 的
`event_id`、`event_type`、`source_message_id` 不一致时，Pipeline 必须停止并报告
provenance 错误，不选择其中一份静默覆盖另一份。

### 2.2 当前 Event schema 的适配

当前 Stage 1 合法 Event 类型为：

```text
INTRODUCE
MODIFY
DEFER
RESUME
REMOVE
AMBIGUOUS
IMPLEMENTATION_CLAIM
RUNTIME_FAILURE
RUNTIME_VERIFICATION
```

仓库中不存在独立的 `CLARIFY` 或 `RESOLVE` Event 类型。对应语义按以下规则派生，
但不得改写原 Event type：

- `AMBIGUOUS` 提供 ambiguity / clarification challenge 覆盖标签；
- 任一 Event 的 `resolves_ambiguity_event_ids` 非空时，提供 ambiguity resolution
  覆盖标签；
- `RESUME` 仍只表示生命周期从暂停或澄清状态恢复，不自动等同于 RESOLVE。

## 3. 核心不变量

1. 一个 Candidate 对应一条 Client message，而不是一个 Event。
2. 同一 `source_message_id` 的所有 Event 必须放进同一个 Candidate。
3. `conversation_turn_index` 从 1 开始；`history_turn_count` 是该 Candidate 前面的
   有效消息数，因此恒等于 `conversation_turn_index - 1`。
4. 消息顺序来自 `normalized_project.messages` 的规范化顺序，使用
   `original_index` 做一致性检查；不得用 message ID 的数值大小代替消息顺序。
5. Candidate Context 只允许包含 Candidate 之前的历史。当前 Candidate message
   单独放在 `candidate_task`；未来消息和由未来 Event 支撑的 State 均不得进入 packet。
6. `history_turn_count` 和 conversation position 只保存为分析元数据，不进入选择分数、
   覆盖增益或去重优先级。
7. LLM 只判断 benchmark value。所有 ID、顺序、Event 分组、State 截取和 Gold
   均由代码产生。
8. LLM 响应必须通过严格 schema 校验。失败重试后仍无有效结果时，该项目不得生成
   final selected targets；不得把失败 Candidate 当作 `recommended: false`。
9. 默认模式中，Human review 是 target selection 的质量控制，不是新的 Requirement 标注。
10. 默认模式只有 `ACCEPT` 和合法的 `ADD_BACK` 能进入最终结果；只有显式
    `--auto-accept-ai` 才允许按 AI 分数线跳过 review。

## 4. Pipeline 与中间产物

Stage 2 项目产物采用“最终状态在外、选择过程在内”的布局：

```text
outputs/stage2/<project_id>/
├── requirement_state_graph.json
├── gold_states.json
└── target_time_selection/
    ├── candidate_tasks.json
    ├── candidate_contexts.json
    ├── candidate_packets.jsonl
    ├── candidate_llm_evaluations.jsonl
    ├── threshold_selection_statistics.json
    ├── threshold_selection_statistics.md
    ├── recommended_candidates.json
    ├── selected_candidates_auto.json
    ├── target_time_human_review.template.json
    ├── target_time_human_review.json
    ├── selected_target_times.json
    ├── gold_state_validation.json
    └── target_selection_run.json
```

`requirement_state_graph.json` 与最终 `gold_states.json` 是项目级核心产物；其他文件都是
目标时间选择、复核、provenance 或生成校验过程文件，统一进入
`target_time_selection/`。CLI 的 `--output-dir` 表示项目输出目录，不是过程子目录。

完整数据流为：

```text
normalized_project.json
        +
<project_id>_stage1_annotation.json
        +
requirement_state_graph.json
        |
        v
target_time_selection/candidate_tasks.json
        |
        v
target_time_selection/candidate_contexts.json
        |
        v
target_time_selection/candidate_packets.jsonl
        |
        v  one validated LLM call per packet
target_time_selection/candidate_llm_evaluations.jsonl
        |
        +--> target_time_selection/threshold_selection_statistics.json / .md
        |    (threshold 5-10 x history-turn buckets; local calculation only)
        |
        v
target_time_selection/recommended_candidates.json
        |
        v
target_time_selection/selected_candidates_auto.json
        |
        v  target_time_selection/target_time_human_review.json
target_time_selection/selected_target_times.json
        |
        v  deterministic graph replay
gold_states.json
target_time_selection/gold_state_validation.json
```

每个 JSON 顶层写入 `schema_version`、`project_id` 和输入 fingerprint。JSONL 每行
是一个完整 Candidate record，并带 `candidate_id`。原子写文件，避免中断后留下看似
完整的半成品。

### 4.1 `candidate_tasks.json`

候选规则：

- 只接受 `speaker == "client"` 的规范化消息；
- 默认候选语义包括 `MODIFY`、`REMOVE`、`DEFER`、`RESUME`、`AMBIGUOUS`，以及
  带非空 `resolves_ambiguity_event_ids` 的 Event；
- 同一消息只生成一个 Candidate，并包含该消息触发的全部 Event；
- 仅含 execution Event 的消息默认不进入候选；
- `INTRODUCE` 与其他候选 Event 同消息出现，或同消息影响多个 Requirements 时进入候选；
- 为保留“INTRODUCE 但依赖已有项目状态”的高召回入口，发生在已有 Requirement State
  之后的 Client `INTRODUCE` 也可进入候选，并标记 `introduce_only: true`，最终由 LLM
  判断其历史依赖；项目第一条纯 INTRODUCE 不进入候选。

建议结构：

```json
{
  "schema_version": "target-selection-v1",
  "project_id": "42204309",
  "candidates": [
    {
      "candidate_id": "42204309_CANDIDATE_MSG_158",
      "message_id": 158,
      "conversation_turn_index": 37,
      "history_turn_count": 36,
      "speaker": "client",
      "text": "...",
      "event_ids": ["REQ_A_E003", "REQ_B_E002"],
      "requirement_ids": ["REQ_A", "REQ_B"],
      "event_types": ["MODIFY", "REMOVE"],
      "coverage_tags": ["MODIFY", "REMOVE", "MULTI_REQUIREMENT"],
      "introduce_only": false
    }
  ]
}
```

`event_ids` 按 Stage 1 / Graph 的稳定顺序排列；其他数组去重但不改变首次出现顺序。

### 4.2 `candidate_contexts.json`

每个 Candidate Context 包含：

- `triggered_events`：当前消息的完整 Event 摘要；
- `pre_task_requirement_states`：仅受影响 Requirements 在当前消息之前的最新 State；
- `requirement_history`：受影响 Requirements 在当前消息之前的 Event sequence；
- `historical_evidence_messages`：上述历史 Event 的 source message 与
  `supporting_message_ids` 指向的消息，按全局对话顺序去重；
- 原样复制的 `conversation_turn_index` 与 `history_turn_count`。

对于在当前消息首次 INTRODUCE 的 Requirement，`pre_task_requirement_state` 为
`null`，不能把当前 INTRODUCE 后的 State 填入 Pre-task。

State Graph Edge 没有保存完整 Event payload，因此 `requirement_history` 由 Stage 1
annotation 提供 Event 内容，并用 State Graph 的 `event_id` / `source_message_id` 做
交叉校验。Pre-task State 内容来自 Graph node，不从 Event payload 重新回放一遍。

### 4.3 `candidate_packets.jsonl`

每行只包含一个 Candidate，直接作为一次 API 调用的 user payload：

```json
{
  "schema_version": "target-candidate-packet-v1",
  "project_id": "42204309",
  "candidate_id": "42204309_CANDIDATE_MSG_158",
  "candidate_task": {
    "message_id": 158,
    "conversation_turn_index": 37,
    "history_turn_count": 36,
    "speaker": "client",
    "text": "..."
  },
  "triggered_events": [],
  "pre_task_requirement_states": [],
  "requirement_history": [],
  "historical_evidence_messages": []
}
```

不得发送完整 State Graph 或完整 conversation。Packet 中保留历史长度字段是为了数据
追踪；system prompt 必须明确禁止根据长度或位置评分。

### 4.4 `candidate_llm_evaluations.jsonl`

每个 packet 使用：

```text
prompt/t_selection_prompt.md
        +
one candidate packet
```

模型必须返回纯 JSON object，严格字段如下：

```json
{
  "candidate_id": "42204309_CANDIDATE_MSG_158",
  "message_id": 158,
  "valid_task": true,
  "historical_dependency": "HIGH",
  "requirement_evolution": "HIGH",
  "reconstruction_risk": "HIGH",
  "ambiguity_decision_value": "LOW",
  "multi_requirement_value": "HIGH",
  "history_sensitive": true,
  "recommended": true,
  "primary_rq_targets": ["RQ1", "RQ2", "RQ4"],
  "reason": "..."
}
```

校验规则：

- `candidate_id` 与 `message_id` 必须与请求完全一致；
- 五个维度只允许 `LOW`、`MEDIUM`、`HIGH`；
- 布尔字段必须是真正的 JSON boolean；
- `primary_rq_targets` 必须唯一并属于配置中的 `allowed_rq_targets`；
- `reason` 必须非空并设置长度上限；
- 不允许额外字段；
- `recommended: true` 时必须同时满足 `valid_task: true` 和
  `history_sensitive: true`；
- 模型不得返回新的 Event、Requirement、State 或修改建议。

五个等级维度由代码确定性换算为 `ai_selection_score`：`LOW=0`、`MEDIUM=1`、
`HIGH=2`，总分范围为 0–10。模型不直接返回总分，避免自由评分与维度判断不一致。

Target selection 以 `Constuction_guideline/ReqMemBench_RP_V2.md` 为权威 RQ 定义，严格
使用四个连续能力阶段：RQ1 Relevant Requirement Selection、RQ2 Current Requirement
State Reconstruction、RQ3 Memory-or-Clarify Decision、RQ4 Requirement-to-Code
Execution。`allowed_rq_targets` 只允许 RQ1–RQ4 的非空子集；
`recommended: true` 时 `primary_rq_targets` 不得为空。

RQ 定义属于 prompt semantics。RQ prompt 发生变化时，对应 evaluation 的
`prompt_sha256` 必须失效并触发重新评估；离线 threshold report 也必须验证当前完整
fingerprint。

### 4.5 `recommended_candidates.json`

只保留同时满足以下条件的 Candidate：

```text
valid_task == true
recommended == true
history_sensitive == true
```

输出合并 Candidate 元数据与完整 LLM evaluation。此阶段不使用
`history_turn_count` 做阈值或排序。

### 4.5.1 Threshold 选择统计

每次获得完整 evaluation 集合后，代码为 threshold 5、6、7、8、9、10 统计自动接受
数量，并按 `history_turn_count` 分为 `[0,50)`、`[50,100)`、`[100,+∞)` 三个互斥
bucket。每行同时给出三个 bucket 和总数。计数条件与 AI 自动接受一致：

```text
valid_task && history_sensitive && recommended && score >= threshold
```

输出为 `threshold_selection_statistics.json` 和便于直接阅读的
`threshold_selection_statistics.md`。统计函数只读取 Candidate 与已有 evaluation，不能
发起 API 调用。`--threshold-report-only` 用于离线重新生成并把表格打印到终端。

### 4.6 `selected_candidates_auto.json`

默认人工复核模式下，覆盖和去重必须可复现，不再随机抽样。

为每个 Candidate 派生 coverage tags：

- Event：`MODIFY`、`REMOVE`、`DEFER`、`RESUME`、`AMBIGUOUS`、
  `AMBIGUITY_RESOLUTION`；
- Task shape：`SINGLE_REQUIREMENT`、`MULTI_REQUIREMENT`；
- LLM 返回的 RQ targets；
- `history_sensitive` challenge；
- Pre-task lifecycle / open-ambiguity pattern。

去重 fingerprint 为：

```text
sorted(affected_requirement_ids)
+ sorted(event/derived-resolution tags)
+ affected Requirements 的 pre-task lifecycle/ambiguity pattern
```

只自动合并 fingerprint 完全相同的 Candidate，不用文本相似度做不可审计的模糊删除。
同一 fingerprint 内按以下顺序选代表：

1. 新增 RQ / Event coverage 数更多；
2. `historical_dependency`、`requirement_evolution`、`reconstruction_risk`、
   `ambiguity_decision_value`、`multi_requirement_value` 的等级向量更高；
3. `candidate_id` 字典序作为纯稳定 tie-breaker。

如果 `max_selected_targets` 为 `null`，保留去重后的全部 Candidate。如果设置上限，
使用 greedy set-cover：每轮选择带来最多未覆盖 tags 的 Candidate，然后使用上面的语义
等级向量和稳定 ID 打破平局。不得把消息位置或历史长度加入 coverage gain 或 rank。

输出同时记录 `kept_candidate_ids`、`deduplicated_candidate_ids`、每一步 coverage gain
和理由，保证审计者可以复算。

### 4.7 人工复核与 `selected_target_times.json`

人工输入文件使用独立名称 `target_time_human_review.json`，避免与 Stage 1 run 中现有的
`human_review.json` 混淆。每条决定为：

```json
{
  "candidate_id": "42204309_CANDIDATE_MSG_158",
  "decision": "ACCEPT",
  "reviewer": "...",
  "reason": "..."
}
```

规则：

- `ACCEPT` / `REJECT` 适用于 auto-selected Candidate；
- `ADD_BACK` 只允许引用已经生成 packet 且完成有效 LLM evaluation 的 Candidate；
- 不允许在 review 文件中手写一个从未进入 Candidate Pool 的新 message ID；
- 重复、未知或互相冲突的决定使 finalize 失败；
- 默认要求每个 auto-selected Candidate 有决定。

最终输出：

```json
{
  "schema_version": "selected-target-times-v1",
  "project_id": "42204309",
  "selected_targets": [
    {
      "target_id": "42204309_T001",
      "candidate_id": "42204309_CANDIDATE_MSG_158",
      "message_id": 158,
      "conversation_turn_index": 37,
      "history_turn_count": 36,
      "event_ids": ["REQ_A_E003", "REQ_B_E002"],
      "affected_requirement_ids": ["REQ_A", "REQ_B"],
      "selection_source": "LLM_PLUS_HUMAN",
      "primary_rq_targets": ["RQ1", "RQ2", "RQ4"],
      "human_review": "ACCEPT"
    }
  ]
}
```

`target_id` 在最终保留项按 conversation 顺序稳定编号。`ADD_BACK` 的
`selection_source` 为 `HUMAN_ADD_BACK`；正常接受项为 `LLM_PLUS_HUMAN`。

### 4.8 AI 分数线自动接受

使用 `--auto-accept-ai --score-threshold N` 时，所有同时满足以下条件的 Candidate
直接进入 `selected_target_times.json`：

```text
valid_task == true
history_sensitive == true
recommended == true
ai_selection_score >= N
```

`N` 是 0–10 的整数，默认值为 7。该模式不执行 challenge deduplication、greedy
set-cover 或 `max_selected_targets` 限制，因为其语义是保留分数线以上的所有时间点。
最终 target 记录 `selection_source: LLM_AUTO_ACCEPT`、`ai_selection_score`、
`ai_score_threshold` 和 `human_review: SKIPPED`。Finalize 会重新计算分数并验证结果集合
恰好等于全部达标 Candidate，不能通过篡改中间 JSON 增删 target。

## 5. Gold State 构建边界

对 `selected_target_times.json` 中的每个 target：

- Pre-task Gold：Graph 中 source message 顺序严格早于 target 的最终 State；
- Post-task Gold：应用 target 同消息的全部有序 Event 后的最终 State；
- `task_event_ids` 必须等于 Graph 中该 source message 的完整 Event 集合；
- `affected_requirement_ids` 只来自这些 Event；
- `preserved_requirement_ids` 等于 Pre-task Requirement 集合减去 affected 集合；
- 新 INTRODUCE Requirement 不在 Pre、在 Post；
- REMOVE Requirement 在 Post 中保留，且 lifecycle 为 `REMOVED`；
- 同一 Requirement 在同一消息有多个 Event 时，Post 使用最后一个 Event 的
  `to_state_id`。

### 5.1 `gold_states.json` 的规范 schema

`gold_states.json` 必须与 `Code/stage2/gold_state.py::build_gold_states()` 生成的
`task-gold-v2` 完全一致。以下不是省略字段的示意图，而是规范的顶层、Task Gold record、
boundary 和 State reference 层级；数组中的对象可以重复任意次，但对象字段不得改名或
改变嵌套位置：

```json
{
  "schema_version": "task-gold-v2",
  "project_id": "42204309",
  "task_gold_states": [
    {
      "task_gold_id": "42204309_T001_GOLD",
      "target_id": "42204309_T001",
      "candidate_id": "42204309_CANDIDATE_MSG_114",
      "conversation_turn_index": 114,
      "history_turn_count": 113,
      "selection_source": "LLM_AUTO_ACCEPT",
      "primary_rq_targets": ["RQ1", "RQ2", "RQ3", "RQ4"],
      "ai_selection_score": 8,
      "ai_score_threshold": 7,
      "target_task": {
        "source_message_id": 114,
        "speaker": "client",
        "text": "..."
      },
      "task_event_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION_E003",
        "REQ_BADGE_AWARD_ACCURACY_E001"
      ],
      "affected_requirement_ids": [
        "REQ_BADGE_CATALOG_AND_PRESENTATION",
        "REQ_BADGE_AWARD_ACCURACY"
      ],
      "preserved_requirement_ids": [
        "REQ_PROJECT_BRANDING",
        "REQ_WALLET_AUTHENTICATION"
      ],
      "pre_task_gold_state": {
        "boundary": {
          "before_message_id": 114
        },
        "requirement_states": [
          {
            "requirement_id": "REQ_PROJECT_BRANDING",
            "state_id": "REQ_PROJECT_BRANDING_S002"
          },
          {
            "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
            "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S002"
          }
        ]
      },
      "post_task_gold_state": {
        "boundary": {
          "through_message_id": 114
        },
        "requirement_states": [
          {
            "requirement_id": "REQ_PROJECT_BRANDING",
            "state_id": "REQ_PROJECT_BRANDING_S002"
          },
          {
            "requirement_id": "REQ_BADGE_CATALOG_AND_PRESENTATION",
            "state_id": "REQ_BADGE_CATALOG_AND_PRESENTATION_S003"
          }
        ]
      }
    }
  ]
}
```

上例为控制篇幅只列出部分 State references；实际 `pre_task_gold_state.requirement_states`
和 `post_task_gold_state.requirement_states` 必须是对应边界的完整项目快照，不得只保存
affected Requirements。

字段契约如下：

| 路径 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `schema_version` | string | 是 | 固定为 `task-gold-v2` |
| `project_id` | string | 是 | 与 selected targets、normalized project、State Graph 一致 |
| `task_gold_states` | array<object> | 是 | 每个最终 selected target 恰好一条，顺序与 target 顺序一致 |
| `task_gold_states[].task_gold_id` | string | 是 | 固定为 `<target_id>_GOLD`，文件内唯一 |
| `task_gold_states[].target_id` | string | 是 | 对应一个最终 selected target，文件内唯一 |
| `task_gold_states[].candidate_id` | string | 是 | 必须与 selected target 完全一致 |
| `task_gold_states[].conversation_turn_index` | integer | 是 | 一基 target 位置 |
| `task_gold_states[].history_turn_count` | integer | 是 | 等于 `conversation_turn_index - 1` |
| `task_gold_states[].selection_source` | string enum | 是 | `LLM_PLUS_HUMAN`、`HUMAN_ADD_BACK` 或 `LLM_AUTO_ACCEPT` |
| `task_gold_states[].primary_rq_targets` | array<string> | 是 | 只允许唯一的 `RQ1`–`RQ4` 值，并与 selected target 一致 |
| `task_gold_states[].ai_selection_score` | integer \| null | 是 | AI 自动接受时为 0–10；人工模式为 `null` |
| `task_gold_states[].ai_score_threshold` | integer \| null | 是 | AI 自动接受时为 0–10 且不得高于 score；人工模式为 `null` |
| `task_gold_states[].target_task` | object | 是 | 固定包含 `source_message_id`、`speaker`、`text` |
| `task_gold_states[].task_event_ids` | array<string> | 是 | 等于 target message 在 State Graph 中的完整有序 Event 集合 |
| `task_gold_states[].affected_requirement_ids` | array<string> | 是 | 从 `task_event_ids` 的 owner Requirements 稳定去重得到 |
| `task_gold_states[].preserved_requirement_ids` | array<string> | 是 | Pre-task Requirement 集合减去 affected 集合 |
| `task_gold_states[].pre_task_gold_state.boundary.before_message_id` | string \| integer | 是 | 与 `target_task.source_message_id` 相同，语义为 exclusive boundary |
| `task_gold_states[].post_task_gold_state.boundary.through_message_id` | string \| integer | 是 | 与 `target_task.source_message_id` 相同，语义为 inclusive boundary |
| `*.requirement_states[]` | object | 是 | 每项只含 `requirement_id` 和 `state_id`，二者必须在 State Graph 中正确关联 |

`build_gold_states()` 会始终写出上述全部字段。人工复核路径虽然没有 AI 分数，也必须保留
`ai_selection_score` 和 `ai_score_threshold` 两个键并写为 JSON `null`；不得因值为空而
删除字段。`requirement_transitions` 不属于 `task-gold-v2`，不得写入 Task Gold record。

## 6. 运行与实现文档

Python 接口、CLI、配置、断点恢复、失败处理、校验、测试及实施验收说明统一维护在
[`Code/insturctions/README_stage2_gold_state.md`](../Code/insturctions/README_stage2_gold_state.md)。

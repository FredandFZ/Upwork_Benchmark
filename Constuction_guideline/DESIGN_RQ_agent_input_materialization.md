# ReqMemBench RQ Agent Input Materialization Design

## 1. 文档目标

本文说明如何把 `outputs/stage2/<project_id>/RQ1/`–`RQ4/` 中的 researcher-side RQ
instances，转换成 Coding Agent 可以安全读取和执行的测试输入。

这里的转换不是把现有 RQ JSON 直接复制给 Agent，而是：

```text
Researcher-side RQ instances
        + condition
        + 固定 Agent prompt/schema
                    ↓
     Phase A Public Reasoning Input
                    ↓
      冻结 RQ1–RQ3 response
                    ↓  仅当 Agent=ACT 且 RQ4 eligible
     Phase B RQ4 Execution Input
        + pre-task Code Environment
```

三类产物必须分开：

- **Phase A Public Reasoning Input**：Agent 只能看到 task、历史、instructions 和 response schema，
  不包含 repository、代码文件或 Code Environment 路径；
- **Phase B RQ4 Execution Input**：只在 Phase A response 冻结后按门控开放，包含只供 RQ4 使用的
  pre-task repository 和只读 frozen response；
- **Private Run Manifest**：Evaluator 使用的 source paths、RQ eligibility、Gold、condition、
  `turns`、difficulty、validator 等信息。

当前 `rq-instance-v1` 文件包含 `construction_gold` 和其他答案信息，因此不能原样作为 Agent
prompt、附件或 workspace 文件。

---

## 2. Materialization 的基本单位

### 2.1 从 `target × RQ` 转换为 `target × condition`

当前磁盘布局以 RQ 为中心：

```text
RQ1/<target_id>_RQ1.json
RQ2/<target_id>_RQ2.json
RQ3/<target_id>_RQ3.json
RQ4/<target_id>_RQ4.json
```

这些文件是同一个 target 的不同 evaluation views。Materializer 先按 `target_id` 合并，再为每个
condition 创建一个由两个权限阶段组成的逻辑 run：

```text
<target_id> × C1
<target_id> × C2
```

Phase A 只提供 task 与 condition-specific history，Agent 依次完成 RQ1 selection、RQ2
reconstruction 和 RQ3 decision。Phase A 不创建或挂载 repository。结构化 response 冻结后，
仅当 Agent decision 为 `ACT` 且 RQ4 eligible 时进入 Phase B，届时才开放 pre-task repository
供代码修改和 RQ4 验证。

RQ-specific 独立输入可以用于调试 scorer，但不是默认端到端测试方式。

### 2.2 RQ 与 condition 的启用规则

Private Run Manifest 按以下规则生成 `active_rqs`：

| RQ | 启用条件 |
|---|---|
| RQ1 | target 在 RQ1 `index.json` 中，并且 condition 为 C1 |
| RQ2 | target 在 RQ2 `index.json` 中，且该 condition `available=true` |
| RQ3 | target 在 RQ3 `index.json` 中，且该 condition `available=true` |
| RQ4 | target 在 RQ4 `index.json` 中，该 condition 的 RQ3 Gold 为 ACT、`rq4_eligible=true`，且 `execution_ready=true` |

`active_rqs` 是 evaluator metadata，不需要告诉 Agent。Agent 使用相同 instructions 完成任务，
但只对真正 eligible 的 views 计分。

当前实例仍处于 provisional 状态时，只能使用 `SMOKE` materialization：可以演练 Phase A 与
满足模拟门控的 Phase B，但输出统一标记为 `NOT_SCORED`。`FORMAL` Phase A 必须拒绝对应
RQ1–RQ3 Gold 尚未完成 review/freeze 的 view；`FORMAL` Phase B 还必须拒绝 RQ4 validator、
校准或 leakage audit 未完成的 execution view。RQ4 未 ready 不影响已经 ready 的 RQ1–RQ3
Phase A view 正式计分。

---

## 3. 输入来源

Materializer 只从以下权威输入读取数据：

```text
outputs/stage2/<project_id>/rq_instance_manifest.json
outputs/stage2/<project_id>/RQ1/index.json
outputs/stage2/<project_id>/RQ2/index.json
outputs/stage2/<project_id>/RQ3/index.json
outputs/stage2/<project_id>/RQ4/index.json
outputs/stage2/<project_id>/RQ*/<target_id>_RQ*.json
Code Environment/<project_id>/reports/target_index.json
Code Environment/<project_id>/targets/<target_dir>/pre_repo.zip  # 仅供 Phase B / RQ4
prompt/rq_agent_instructions.md
schema/rq_agent_response.schema.json
```

其中 Stage 2 和 Code Environment 路径是当前已有输入；
`prompt/rq_agent_instructions.md`、`schema/rq_agent_response.schema.json` 是实现 Materializer 时
需要新增并进行版本控制的公共模板，当前尚未创建。

发现实例时必须读取各 RQ 的 `index.json`，不能通过 glob 把目录中的旧文件或人工备份当成当前
有效实例。

同一 target 出现在多个 RQ 文件中时，以下共享字段必须完全一致：

- `project_id`；
- `target_id`；
- `target_message_id`；
- `target_task`；
- `history_pool`；
- `turns`、`history_turn_count` 和 `difficulty`；
- 同名 condition 的 history mode 和 message IDs。

任何不一致都应停止 materialization，而不是任意选择某一个 RQ 文件。

---

## 4. 现有字段如何转换

| 现有 RQ instance 字段 | 处理方式 | Agent 是否可见 |
|---|---|---|
| `target_task` | 提取为公共 `task.json` | 是 |
| `history_pool.messages` | 作为历史消息源，不整体复制 | 仅看到 condition 选中的消息 |
| `condition_inputs.<C>.history_message_ids` | 用于过滤并生成 `history.jsonl` | 只看到过滤结果 |
| `question` | 不直接拼接；由固定统一 instructions 代替 | 否 |
| `response_contract` | RQ1–RQ3 合并为统一 response JSON Schema；RQ4 不增加 action 字段 | 只看到 Schema |
| `turns`、`difficulty` | 保存到 Private Run Manifest | 否 |
| `rq_id`、RQ eligibility | 保存为 `active_rqs` | 否 |
| `code_environment.archive_path` | Runner 在 Phase B 定位并解压代码 | Phase A 不可见；Phase B 只看到解压后的 repository |
| `code_environment` 的 hashes/classification | 用于 Runner 校验 | 否 |
| `requirements_to_code`、`temporal_fixture` | 保留给 evaluator/validator | 否 |
| `construction_gold` | 保留给 scorer | 否 |
| `selection_basis`、`source_artifacts`、`visibility` | 不写入公共输入 | 否 |

`question` 不直接使用的原因是四个 RQ 文件各有一个问题文本，直接拼接容易形成重复任务。
Phase A prompt 固定描述 Select → Reconstruct → Decide；Phase B prompt 只描述 Execute，并明确
RQ1–RQ3 response 已冻结且不可修改。

---

## 5. Public Agent Input

### 5.1 静态公共输入包

Materializer 为每个 `target × condition` 生成：

```text
outputs/agent_inputs/<input_release>/<project_id>/<target_id>/<condition>/public/
├── task.json
├── history.jsonl
├── instructions.md
└── response.schema.json
```

该目录就是 Phase A 的完整 Agent-visible 输入，不包含 repository、archive path 或 Code
Environment metadata。Phase B 的代码目录必须在 Phase A response 冻结后另行创建。

静态目录可以使用 C1/C2 名称方便研究者检查，但实际 Agent 的工作目录应使用不包含
condition/RQ/Gold 信息的 opaque run ID，并限制 Agent 只能访问该目录。

### 5.2 `task.json`

公共 task 文件只包含完成当前任务所需的信息：

```json
{
  "schema_version": "rq-agent-task-v1",
  "task": {
    "message_id": 288,
    "speaker": "client",
    "text": "..."
  },
  "history_file": "history.jsonl",
  "response_schema_file": "response.schema.json"
}
```

不要把以下字段加入 `task.json`：

- `target_id`、RQ eligibility 或 `active_rqs`；
- C1/C2 的名称或 `history_mode`；
- `turns` 和 difficulty；
- affected/preserved Requirement IDs；
- Gold decision、State 或 expected code paths。

Agent 只需要根据实际收到的 evidence 工作，不需要被告知这是 Full History 还是
Oracle Relevant History。

### 5.3 `history.jsonl`

每行保存一条 Agent 可见的原始脱敏消息：

```json
{"message_id":21,"created_ts":"...","speaker":"client","text":"...","milestone":null}
```

生成规则：

1. 读取 `condition_inputs.<condition>.history_message_ids`；
2. 在 `history_pool.messages` 中按 `message_id` 查找；
3. 严格保持 `history_pool` 的原始顺序，不按数字重新排序；
4. 每个 ID 恰好输出一次；
5. 不输出 target message 或 target 之后的消息。

两种 condition 的结果为：

- C1：写出 Full History 的全部允许消息；
- C2：只写出审核后的 relevant trajectory 和必要 contextual messages。

必须保留 public `message_id`，因为 RQ1/RQ2 要求 Agent 在答案中引用 evidence。

### 5.4 `instructions.md`

所有 targets 和 conditions 的 Phase A 使用同一个版本化 prompt template。最小 instructions
应告诉 Agent：

1. 阅读 `task.json` 和 `history.jsonl`；当前阶段没有 repository；
2. 只依据当前 workspace 中可见的证据，不假设存在未提供的历史；
3. 找出相关 historical Requirements，并引用可见 message IDs；
4. 恢复 target 前的 current Requirement State，正确处理 update、override、remove 和 scope；
5. 判断证据是否足以 `ACT`，否则输出具体 `CLARIFY` 问题；
6. 如果决定 `ACT`，输出完整 closed-world Post-state：保留仍适用字段，省略已删除/被替换的旧
   属性，并把删除项列入 `removed_attribute_keys`；
7. 最终回答必须符合 `response.schema.json`；
8. 不输出 private chain-of-thought，只输出结构化结论。

Prompt 中不能包含 target-specific Gold、正确 Requirement 名称、预期文件路径或 hidden test
提示，也不能暗示 Phase B 的目录结构、代码路径或 repository 内容。

Phase B 使用独立的 versioned execution prompt。它只要求 Agent 根据 task、可见历史、冻结的
Phase A response 和新开放的 repository 完成代码修改；不得生成替代 response，也不得修改
Phase A 文件。Phase B 的任何文字输出均不重新进入 RQ1–RQ3 评分。

### 5.5 `response.schema.json`

统一 response 至少包含：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "...",
      "evidence_message_ids": [21, 146, 195],
      "pre_task_state": {
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "ACT",
  "post_task_states": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "...",
      "change_type": "MODIFIED",
      "removed_attribute_keys": [],
      "state": {
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "clarifications": []
}
```

约束：

- `evidence_message_ids` 只能引用当前 `history.jsonl` 中的 ID；不再输出与其重复的顶层
  `selected_history_message_ids`；
- Agent 使用自己的 `requirement_ref`，不要求猜 `REQ_*`；
- `pre_task_state` 与 Post-state 都恰好包含五个语义 dimensions；内部 Requirement/Event/State
  ID 禁止输出；`ambiguity` 只能为 `null` 或 record array；
- State 采用 closed-world 语义，多余的 stale/未知字段会作为 false positive；
- `decision` 只能是 `ACT` 或 `CLARIFY`；
- `ACT` 时 `post_task_states` 为数组且 `clarifications=[]`；
- `CLARIFY` 时仍必须输出 `requirements` 及其 `pre_task_state`，`post_task_states=null`，并在
  `clarifications` 中输出具体问题、Requirement ref、dimension、field 与缺失信息；
- RQ1 scorer 按 `rq1-agent-response-v3` 直接接收此统一 response：验证声明字段白名单后，仅投影
  `requirement_ref`、`requirement_summary`、`evidence_message_ids` 参与 RQ1 评分；Runner 不需要
  预先删除 `pre_task_state` 或顶层 RQ2/RQ3 字段；
- RQ2 与 RQ3 分别按 `rq2-agent-response-v3`、`rq3-agent-response-v3` 验证；自然语言语义叶的
  API 判断与最终确定性计分分离；
- 该 response 仅供 RQ1–RQ3 评分；RQ4 不要求 `planned_actions` 或单独的结构化回答；
- RQ4 的唯一被评分产物是最终 repository，结果由 workspace 外的 hidden validator 确定。

---

## 6. Private Run Manifest

每个公共输入包对应一个 Agent 不可见的私有 manifest：

```json
{
  "schema_version": "rq-private-run-manifest-v1",
  "run_id": "run_7f22c6...",
  "project_id": "42204309",
  "target_id": "42204309_T010",
  "condition": "C1",
  "turns": 287,
  "difficulty": "LONG",
  "reasoning_active_rqs": ["RQ1", "RQ2", "RQ3"],
  "execution_rq": "RQ4",
  "source_instances": {
    "RQ1": ".../42204309_T010_RQ1.json",
    "RQ2": ".../42204309_T010_RQ2.json",
    "RQ3": ".../42204309_T010_RQ3.json",
    "RQ4": ".../42204309_T010_RQ4.json"
  },
  "phase_gate": {
    "repository_visible_in_phase_a": false,
    "phase_a_response_sha256": null,
    "phase_a_frozen_at": null,
    "phase_b_requires_agent_act": true
  },
  "repository": {
    "archive_path": ".../pre_repo.zip",
    "archive_sha256": "...",
    "tree_sha256": "...",
    "available_to_phase": "B_ONLY",
    "rq4_leakage_audit_sha256": "..."
  },
  "rq4": {
    "eligible": true,
    "validator_id": "42204309_T010_RQ4_V1",
    "validator_sha256": "...",
    "acceptance_criteria_ids": ["AC001", "AC002"],
    "calibration_record_sha256": "..."
  },
  "score_status": "READY"
}
```

Private Run Manifest 的作用是：

- 把 Agent output 关联回正确的 RQ Gold；
- 保存 `turns` 和 difficulty 以便后续分类；
- 确定哪些 RQ/condition 应评分；
- 记录 Phase A 无仓库、response 已冻结及其 hash/timestamp；
- 仅为 Phase B 定位同一份 pre-task repository；
- 对 eligible RQ4 run 定位已冻结并校准的 hidden validator；
- 保证复现实验时输入和代码版本不变。

该文件必须保存到 Agent sandbox 之外。

---

## 7. Repository Materialization

### 7.1 定位代码环境

Phase A 不执行本节，也不能读取本节引用的路径。只有 Phase A response 已冻结、Agent decision
为 `ACT` 且 RQ4 eligible 时，Runner 才使用 `project_id + target_id` 在
`Code Environment/<project_id>/reports/target_index.json` 中找到对应 target，并核对：

- `before_message_id == target_message_id`；
- archive path 和 manifest 存在；
- archive SHA 与记录一致；
- Code Environment validation 已通过。

不能把 `requirements_to_code`、expected code paths 或 temporal fixture metadata 暴露给 Agent。
RQ4 repository 必须通过 future-state、validator、reference-delivery 和 evaluator-metadata 泄漏
审计。Pre-task 实现本身允许保留，因为它是 RQ4 的合法起点；但该 repository 永远不能回流到
RQ1–RQ3 scorer 或用于修订 Phase A response。

### 7.2 Phase B 全新解压

Phase B execution workspace 为：

```text
<isolated_root>/<opaque_run_id>/
├── task.json
├── history.jsonl
├── execution_instructions.md
├── frozen_rq123_response.json   # read-only，hash 已记录
└── repository/                  # Phase B 才全新解压
```

Runner 必须：

1. 确认 Phase A workspace 从未包含 repository，且冻结 response hash 与 private manifest 一致；
2. 创建新的空 execution directory；
3. 检查 `pre_repo.zip` 的 path traversal、symlink 和 `.git`；
4. 将 `pre_repo.zip` 解压到 `repository/`；
5. 校验解压后的 tree hash 和 RQ4 leakage-audit record；
6. 以只读方式放入冻结的 Phase A response；
7. 启动 Agent，并把可访问根目录限制在本次 execution workspace；
8. Agent 结束后保存 patch、最终 repository hash 和权限日志；
9. 再次核对 Phase A response hash 未变化；
10. 不把修改后的 repository 复用于其他 condition。

C1/C2 的 Phase B 必须使用同一份 `pre_repo.zip`；condition 之间只允许继承各自 Phase A 的
history 和 frozen response。若要运行 repository-visible RQ2/RQ3，只能作为单独命名的 `+Repo`
消融，不得进入正式主结果。

---

## 8. Agent 运行与输出回收

Runner 启动 Claude Code、Codex 或其他 Coding Agent 时，Phase A 与 Phase B 必须使用不同的
opaque workspace 和独立权限配置：

- Phase A working directory 不包含 repository，且工具层禁止读取 Code Environment；
- Phase A 结束后先在 evaluator-side immutable storage 冻结 response，并记录 SHA-256 与时间戳；
- 只有可解析的 Phase A decision 为 `ACT` 且 RQ4 eligible 时，才创建 Phase B workspace；
- Phase B 只能读取 frozen response，不能覆盖、补写或重新提交 RQ1–RQ3 答案；
- 使用固定模型、prompt、工具和预算；
- 禁止访问 workspace 外的 Stage 2、Gold 和 validator 目录；
- 不允许跨 run 继续之前的 Agent session/memory；
- Agent 完成后不向其返回 hidden test 结果。

Runner 回收：

```text
phase_a/agent_response.json
phase_a/agent_response.sha256
phase_a/agent_stdout.log
phase_a/agent_stderr.log
phase_a/tool_events.jsonl
phase_a/permission_log.jsonl
phase_b/patch.diff                         # 仅实际进入 Phase B 时存在
phase_b/changed_files.json
phase_b/final_repository_tree_sha256
phase_b/agent_stdout.log
phase_b/agent_stderr.log
phase_b/tool_events.jsonl
phase_b/permission_log.jsonl
run_status.json
```

结构化 response 无法解析或引用不可见 message ID 时，RQ1–RQ3 按各自契约处理；不能让另一个
LLM 自动补写答案。若 Phase A response 无法解析，或 Agent decision 不是 `ACT`，Runner 不向
Agent 开放 repository。对于 RQ4 Gold-eligible 的实例，这种情况记录为 `NO_CODE_SUBMISSION`，并在
端到端 RQ4 结果中记为 `FAIL`；它不是 repository eligibility failure。已经进入 Phase B 但 Agent
超时或未留下可测试 repository 时，同样记为 `FAIL`。

### RQ4 的后处理

RQ4 validator 不属于 Public Agent Input。Agent 结束并冻结代码后，Evaluator 在 sandbox 外
运行对应的 hidden validator：

```text
BuildPass AND TargetTestPass AND RegressionPass
                    ↓
              RQ4 PASS/FAIL
```

三项全部通过才是 `PASS`，任一项失败即为 `FAIL`。环境、validator 或 harness 自身故障会使
attempt 作废并从干净 pre-repo 重跑，不写入第三种评分状态。当前 RQ4 `execution_ready=false`
或 `rq4_eligible=false` 时，Runner 可以保存 patch 用于 smoke test，但不能生成正式 RQ4 score。
RQ4 不调用外部 API/LLM judge，也不比较 patch 文本相似度。

---

## 9. Leakage 与一致性校验

Materializer 写出 Phase A 公共输入及 Phase B execution input 前必须验证：

- Phase A 公共输入中不存在 `construction_gold`、`selection_basis`、`source_artifacts`；
- Phase A 公共输入中不存在 `REQ_*`、Event ID、State ID、affected/preserved Requirement ID；
- 不存在 acceptance criteria、validator path/内容、reference delivery、expected code path 或 Gold decision；
- Phase A workspace 中不存在 repository、archive path、代码文件、代码搜索入口或 build/test 输出；
- Phase B repository 不含 future state、validator、reference delivery 或 evaluator-only
  Requirement/State/Event metadata；
- `history.jsonl` 的 ID 集合与 condition 声明完全一致；
- C1 history 等于 target 之前的完整历史；
- C2 是 C1 的有序子序列，并通过相关性与充分性审核；
- 所有历史消息都严格早于 target；
- target message 只出现在 `task.json`，不出现在 history；
- C1/C2 的 Phase A task、instructions、schema、模型和非仓库工具权限完全相同；
- 实际进入 Phase B 的 C1/C2 使用同一份 RQ4-only repository hash；
- Phase B 结束后，frozen response 的 SHA-256 与进入 Phase B 前完全一致；
- Agent 实际 workspace 路径不暴露 condition 或 RQ 名称；
- Agent 无法访问 Private Run Manifest 和其他 runs。

Materializer 必须为 public files 和 private manifest 计算 SHA-256。完全相同的 source instances、
condition 和 prompt version 应产生完全相同的静态 Public Agent Input。

---

## 10. 项目 42204309 示例

以 `42204309_T010` 的 C1 为例，Materializer 读取同一 target 的 RQ1–RQ4 files，并确认共享
字段一致。当前 RQ2 instance 中：

```text
target_message_id = 288
turns = 287
C1 history_message_count = 287
```

Phase A 生成的 Agent 可见内容为：

```text
task.json              当前 message 288 的 client task
history.jsonl          message 1–287 的脱敏历史，保持原顺序
instructions.md        固定统一任务说明
response.schema.json   固定结构化输出约束
```

Agent 写出 RQ1–RQ3 response 后，Runner 先冻结文件并记录 hash。仅当 decision 为 `ACT` 且该
condition 已通过 RQ4 eligibility gate，才创建 Phase B workspace，并加入：

```text
frozen/agent_response.json   Phase A response 的只读副本
execution_instructions.md    仅要求实现已冻结的 ACT decision
repository/                  T010 对应 pre_repo.zip 的全新解压结果，仅供 RQ4
```

Agent 不会看到：

```text
42204309_T010
C1 / FULL_HISTORY
turns = 287 / LONG
active_rqs
construction_gold
Requirement/Event/State IDs
code_environment.requirements_to_code
validator 或正确 delivery
```

这些信息保存在 Private Run Manifest，用于把 Phase A response 和 Phase B 最终 repository 送入
正确的 scorers。由于当前 Gold、RQ4 validators、校准和 repository leakage audit 尚未冻结，这个例子
只能标记为 smoke test，不能产生正式 RQ4 `PASS`/`FAIL`。

---

## 11. 建议命令接口

后续 Materializer 建议提供以下命令，但本文不假设代码已经实现：

单个 target/condition 的 Phase A smoke test：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --target-id 42204309_T010 `
  --condition C1 `
  --phase reasoning `
  --mode smoke
```

生成项目全部 C1/C2 输入：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --all-conditions `
  --phase reasoning `
  --mode smoke
```

Phase A response 冻结后，门控创建 Phase B execution input：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --target-id 42204309_T010 `
  --condition C1 `
  --phase execution `
  --frozen-response path/to/phase_a/agent_response.json `
  --mode formal
```

批量正式 Phase A：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --all-conditions `
  --phase reasoning `
  --mode formal
```

`formal` reasoning 模式必须拒绝对应 RQ1–RQ3 的 provisional eligibility、未审核的 C2 Oracle
历史或未冻结的 RQ3 decision；`formal` execution 模式必须额外拒绝 RQ4 eligibility 未通过、validator 未冻结、
校准未完成或 repository leakage audit 未通过的 view。RQ4 execution 未 ready 不撤销已 ready
的 RQ1–RQ3 reasoning view。

---

## 12. Materialization Definition of Done

- [ ] 只按各 RQ `index.json` 发现实例；
- [ ] 同一 target 的共享字段完成一致性检查；
- [ ] 一个 target/condition 先生成一个不含 repository 的 Phase A Public Reasoning Input；
- [ ] C1/C2 history 按 message IDs 正确过滤并保持顺序；
- [ ] `turns` 和 difficulty 留在私有 metadata，没有丢失；
- [ ] 公共 task、instructions 和 response schema 不含 Gold；
- [ ] Phase A workspace 不存在 repository、archive path、代码工具入口或 build/test 输出；
- [ ] Phase A response 在开放任何 repository 前完成 hash 与不可变冻结；
- [ ] 只有 Agent=`ACT` 且 RQ4 eligible 时才创建 Phase B；
- [ ] Phase B 的 pre-task repository 每次 run 全新、安全解压；
- [ ] 进入 Phase B 的 C1/C2 使用同一 RQ4-only repository hash；
- [ ] Phase B 结束后 Phase A response hash 保持不变；
- [ ] Agent workspace 使用 opaque path，无法读取 evaluator assets；
- [ ] Phase A response 与 Phase B patch、logs、final repository 分目录回收；
- [ ] RQ4 validator 只在 Agent 停止后由 evaluator 运行；
- [ ] RQ4 不要求 `planned_actions`，正式结果值域只有 `PASS`/`FAIL`；
- [ ] eligible RQ4 validator 已完成人工复核、三类校准和版本冻结；
- [ ] Phase B repository 不泄漏 future state、validator、reference delivery 或 evaluator metadata；
- [ ] `SMOKE` 与 `FORMAL` 模式严格区分；
- [ ] leakage 和 fingerprint tests 全部通过。

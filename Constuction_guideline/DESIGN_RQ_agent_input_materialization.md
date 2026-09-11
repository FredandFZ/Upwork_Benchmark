# ReqMemBench RQ Agent Input Materialization Design

## 1. 文档目标

本文说明如何把 `outputs/stage2/<project_id>/RQ1/`–`RQ4/` 中的 researcher-side RQ
instances，转换成 Coding Agent 可以安全读取和执行的测试输入。

这里的转换不是把现有 RQ JSON 直接复制给 Agent，而是：

```text
Researcher-side RQ instances
        + condition
        + pre-task Code Environment
        + 固定 Agent prompt/schema
                    ↓
           Public Agent Input
                    +
          Private Run Manifest
```

两类产物必须分开：

- **Public Agent Input**：Agent 可以看到的 task、历史、instructions 和代码；
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

这些文件是同一个 target 的不同 evaluation views。默认 Agent 测试不为四个 RQ 分别创建四次
独立对话，而是先按 `target_id` 合并，再为每个 condition 创建一次统一 Agent run：

```text
<target_id> × C1
<target_id> × C2
<target_id> × C3
```

一次 run 中，Agent 依次完成 RQ1 selection、RQ2 reconstruction、RQ3 decision；如果决定
`ACT`，则继续修改代码供 RQ4 验证。Evaluator 再根据私有 `active_rqs` 决定该 run 的哪些输出
进入评分。

RQ-specific 独立输入可以用于调试 scorer，但不是默认端到端测试方式。

### 2.2 RQ 与 condition 的启用规则

Private Run Manifest 按以下规则生成 `active_rqs`：

| RQ | 启用条件 |
|---|---|
| RQ1 | target 在 RQ1 `index.json` 中，并且 condition 为 C2 |
| RQ2 | target 在 RQ2 `index.json` 中，且该 condition `available=true` |
| RQ3 | target 在 RQ3 `index.json` 中，且该 condition `available=true` |
| RQ4 | target 在 RQ4 `index.json` 中，最终 Gold 为 ACT，且 `execution_ready=true` |

`active_rqs` 是 evaluator metadata，不需要告诉 Agent。Agent 使用相同 instructions 完成任务，
但只对真正 eligible 的 views 计分。

当前实例仍处于 provisional 状态时，只能使用 `SMOKE` materialization：Agent 可以运行和修改
代码，但输出标记为 `NOT_SCORED`。`FORMAL` materialization 必须拒绝尚未完成 Gold review 或
RQ4 validator 的实例。

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
Code Environment/<project_id>/targets/<target_dir>/pre_repo.zip
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
| `response_contract` | 合并、冻结为统一 response JSON Schema | 只看到 Schema |
| `turns`、`difficulty` | 保存到 Private Run Manifest | 否 |
| `rq_id`、RQ eligibility | 保存为 `active_rqs` | 否 |
| `code_environment.archive_path` | Runner 定位并解压代码 | 只看到解压后的 repository |
| `code_environment` 的 hashes/classification | 用于 Runner 校验 | 否 |
| `requirements_to_code`、`temporal_fixture` | 保留给 evaluator/validator | 否 |
| `construction_gold` | 保留给 scorer | 否 |
| `selection_basis`、`source_artifacts`、`visibility` | 不写入公共输入 | 否 |

`question` 不直接使用的原因是四个 RQ 文件各有一个问题文本，直接拼接容易形成四个互相重复的
任务。统一 Agent prompt 应稳定地描述完整的 Select → Reconstruct → Decide → Execute 流程。

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

该目录不包含解压后的 repository。代码只在实际 Agent run 开始时，从已校验的
`pre_repo.zip` 解压到一次性 workspace，避免不同 runs 互相污染。

静态目录可以使用 C1/C2/C3 名称方便研究者检查，但实际 Agent 的工作目录应使用不包含
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
  "repository_root": "repository",
  "response_schema_file": "response.schema.json"
}
```

不要把以下字段加入 `task.json`：

- `target_id`、RQ eligibility 或 `active_rqs`；
- C1/C2/C3 的名称或 `history_mode`；
- `turns` 和 difficulty；
- affected/preserved Requirement IDs；
- Gold decision、State 或 expected code paths。

Agent 只需要根据实际收到的 evidence 工作，不需要被告知这是 No History、Full History 还是
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

三种 condition 的结果为：

- C1：创建存在但内容为空的 `history.jsonl`；
- C2：写出 Full History 的全部允许消息；
- C3：只写出审核后的 relevant trajectory 和必要 contextual messages。

必须保留 public `message_id`，因为 RQ1/RQ2 要求 Agent 在答案中引用 evidence。

### 5.4 `instructions.md`

所有 targets 和 conditions 使用同一个版本化 prompt template。最小 instructions 应告诉
Agent：

1. 阅读 `task.json`、`history.jsonl` 和 `repository/`；
2. 只依据当前 workspace 中可见的证据，不假设存在未提供的历史；
3. 找出相关 historical Requirements，并引用可见 message IDs；
4. 恢复 target 前的 current Requirement State，正确处理 update、override、remove 和 scope；
5. 判断证据是否足以 `ACT`，否则输出具体 `CLARIFY` 问题；
6. 如果决定 `ACT`，在 `repository/` 中完成当前 client task；
7. 最终回答必须符合 `response.schema.json`；
8. 不输出 private chain-of-thought，只输出结构化结论。

Prompt 中不能包含 target-specific Gold、正确 Requirement 名称、预期文件路径或 hidden test
提示。

### 5.5 `response.schema.json`

统一 response 至少包含：

```json
{
  "selected_history_message_ids": [21, 146, 195],
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "...",
      "evidence_message_ids": [21, 146, 195],
      "current_state": {
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "ACT",
  "clarification": null
}
```

约束：

- `selected_history_message_ids` 和 `evidence_message_ids` 只能引用当前 `history.jsonl` 中的 ID；
- Agent 使用自己的 `requirement_ref`，不要求猜 `REQ_*`；
- `decision` 只能是 `ACT` 或 `CLARIFY`；
- `ACT` 时 `clarification=null`；
- `CLARIFY` 时 clarification 必须包含具体问题、Requirement ref 和 dimension；
- RQ4 新评估方式不要求使用 planned action 判断最终代码是否通过；代码结果由 workspace 和
  hidden validator 决定。

---

## 6. Private Run Manifest

每个公共输入包对应一个 Agent 不可见的私有 manifest：

```json
{
  "schema_version": "rq-private-run-manifest-v1",
  "run_id": "run_7f22c6...",
  "project_id": "42204309",
  "target_id": "42204309_T010",
  "condition": "C2",
  "turns": 287,
  "difficulty": "LONG",
  "active_rqs": ["RQ1", "RQ2", "RQ3", "RQ4"],
  "source_instances": {
    "RQ1": ".../42204309_T010_RQ1.json",
    "RQ2": ".../42204309_T010_RQ2.json",
    "RQ3": ".../42204309_T010_RQ3.json",
    "RQ4": ".../42204309_T010_RQ4.json"
  },
  "repository": {
    "archive_path": ".../pre_repo.zip",
    "archive_sha256": "...",
    "tree_sha256": "..."
  },
  "rq4_validator_id": null,
  "score_status": "NOT_SCORED_PROVISIONAL"
}
```

Private Run Manifest 的作用是：

- 把 Agent output 关联回正确的 RQ Gold；
- 保存 `turns` 和 difficulty 以便后续分类；
- 确定哪些 RQ/condition 应评分；
- 定位同一份 pre-task repository；
- 在 RQ4 ready 后定位 hidden validator；
- 保证复现实验时输入和代码版本不变。

该文件必须保存到 Agent sandbox 之外。

---

## 7. Repository Materialization

### 7.1 定位代码环境

Runner 使用 `project_id + target_id` 在
`Code Environment/<project_id>/reports/target_index.json` 中找到对应 target，并核对：

- `before_message_id == target_message_id`；
- archive path 和 manifest 存在；
- archive SHA 与记录一致；
- Code Environment validation 已通过。

不能把 `requirements_to_code`、expected code paths 或 temporal fixture metadata 暴露给 Agent。

### 7.2 每次 run 全新解压

实际运行目录为：

```text
<isolated_root>/<opaque_run_id>/
├── task.json
├── history.jsonl
├── instructions.md
├── response.schema.json
└── repository/              # 本次运行新解压
```

Runner 必须：

1. 创建新的空目录；
2. 检查 zip path traversal、symlink 和 `.git`；
3. 将 `pre_repo.zip` 解压到 `repository/`；
4. 校验解压后的 tree hash；
5. 启动 Agent，并把可访问根目录限制在本次 workspace；
6. Agent 结束后保存 response、patch 和 repository hash；
7. 不把修改后的 repository 复用于其他 condition。

C1/C2/C3 必须使用同一份 `pre_repo.zip`。三个 conditions 之间唯一允许变化的是
`history.jsonl`。

---

## 8. Agent 运行与输出回收

Runner 启动 Claude Code、Codex 或其他 Coding Agent 时：

- working directory 设置为本次 opaque workspace；
- 使用固定模型、prompt、工具和预算；
- 禁止访问 workspace 外的 Stage 2、Gold 和 validator 目录；
- 不允许跨 run 继续之前的 Agent session/memory；
- Agent 完成后不向其返回 hidden test 结果。

Runner 回收：

```text
agent_response.json
agent_stdout.log
agent_stderr.log
tool_events.jsonl
patch.diff
changed_files.json
final_repository_tree_sha256
run_status.json
```

结构化 response 无法解析、引用不可见 message ID 或超时，应记录为 Agent failure；不能让
另一个 LLM 自动补写答案。

### RQ4 的后处理

RQ4 validator 不属于 Public Agent Input。Agent 结束并冻结代码后，Evaluator 在 sandbox 外
运行对应的 hidden validator：

```text
BuildPass AND TargetTestPass AND RegressionPass
                    ↓
              RQ4 PASS/FAIL
```

当前 RQ4 `execution_ready=false` 时，Runner 可以保存 patch 用于 smoke test，但不能生成正式
RQ4 score。

---

## 9. Leakage 与一致性校验

Materializer 写出公共输入前必须验证：

- Public Agent Input 中不存在 `construction_gold`、`selection_basis`、`source_artifacts`；
- 不存在 `REQ_*`、Event ID、State ID、affected/preserved Requirement ID；
- 不存在 validator path、reference patch、expected code path 或 Gold decision；
- `history.jsonl` 的 ID 集合与 condition 声明完全一致；
- C1 history 为空；
- C3 是 C2 的有序子序列；
- 所有历史消息都严格早于 target；
- target message 只出现在 `task.json`，不出现在 history；
- C1/C2/C3 的 task、instructions、schema 和 repository hash 完全相同；
- Agent 实际 workspace 路径不暴露 condition 或 RQ 名称；
- Agent 无法访问 Private Run Manifest 和其他 runs。

Materializer 必须为 public files 和 private manifest 计算 SHA-256。完全相同的 source instances、
condition 和 prompt version 应产生完全相同的静态 Public Agent Input。

---

## 10. 项目 42204309 示例

以 `42204309_T010` 的 C2 为例，Materializer 读取同一 target 的 RQ1–RQ4 files，并确认共享
字段一致。当前 RQ2 instance 中：

```text
target_message_id = 288
turns = 287
C2 history_message_count = 287
```

生成的 Agent 可见内容为：

```text
task.json              当前 message 288 的 client task
history.jsonl          message 1–287 的脱敏历史，保持原顺序
instructions.md        固定统一任务说明
response.schema.json   固定结构化输出约束
repository/            T010 对应 pre_repo.zip 的全新解压结果
```

Agent 不会看到：

```text
42204309_T010
C2 / FULL_HISTORY
turns = 287 / LONG
active_rqs
construction_gold
Requirement/Event/State IDs
code_environment.requirements_to_code
validator 或正确 delivery
```

这些信息保存在 Private Run Manifest，用于把 Agent 的 response 和 patch 送入正确的 RQ
scorers。由于当前 Gold 和 RQ4 validators 尚未冻结，这个例子只能标记为 smoke test。

---

## 11. 建议命令接口

后续 Materializer 建议提供以下命令，但本文不假设代码已经实现：

单个 target/condition smoke test：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --target-id 42204309_T010 `
  --condition C2 `
  --mode smoke
```

生成项目全部 C1/C2/C3 输入：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --all-conditions `
  --mode smoke
```

正式模式：

```powershell
python Code/materialize_rq_agent_inputs.py `
  --project-id 42204309 `
  --all-conditions `
  --mode formal
```

`formal` 模式必须拒绝 provisional RQ eligibility、未审核的 C3、未冻结的 RQ3 decision，以及
没有 hidden validator 的 RQ4 execution view。

---

## 12. Materialization Definition of Done

- [ ] 只按各 RQ `index.json` 发现实例；
- [ ] 同一 target 的共享字段完成一致性检查；
- [ ] 一个 target/condition 只生成一个统一 Public Agent Input；
- [ ] C1/C2/C3 history 按 message IDs 正确过滤并保持顺序；
- [ ] `turns` 和 difficulty 留在私有 metadata，没有丢失；
- [ ] 公共 task、instructions 和 response schema 不含 Gold；
- [ ] pre-task repository 每次 run 全新、安全解压；
- [ ] C1/C2/C3 使用同一 repository hash；
- [ ] Agent workspace 使用 opaque path，无法读取 evaluator assets；
- [ ] Agent response、patch、logs 和 final repository 可以回收；
- [ ] RQ4 validator 只在 Agent 停止后由 evaluator 运行；
- [ ] `SMOKE` 与 `FORMAL` 模式严格区分；
- [ ] leakage 和 fingerprint tests 全部通过。

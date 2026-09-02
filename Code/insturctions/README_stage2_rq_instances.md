# ReqMemBench Stage 2.3：RQ1–RQ4 实例生成

本阶段读取已经完成的 `gold_states.json`、Requirement State Graph、脱敏历史消息和
RQ4 的 Code Environment，为每个选中 target 构造 RQ 问题实例。它只生成实例，
不运行 Agent、不打分，也不生成 hidden tests。

实现入口：

- 构造逻辑：`Code/stage2/rq_instances.py`
- 命令行：`Code/stage2_generate_rq_instances.py`
- 测试：`Code/tests/test_stage2_rq_instances.py`

## 一条命令生成

在仓库根目录运行：

```powershell
python Code/stage2_generate_rq_instances.py --project-id 42204309
```

程序按项目 ID 自动读取：

```text
outputs/stage2/42204309/gold_states.json
outputs/stage2/42204309/requirement_state_graph.json
outputs/stage1_runs/42204309/normalized_project.json
Code Environment/42204309/
```

成功后输出：

```text
outputs/stage2/42204309/
├── gold_states.json
├── requirement_state_graph.json
├── rq_instance_manifest.json
├── RQ1/
│   ├── index.json
│   └── 42204309_Txxx_RQ1.json
├── RQ2/
│   ├── index.json
│   └── 42204309_Txxx_RQ2.json
├── RQ3/
│   ├── index.json
│   └── 42204309_Txxx_RQ3.json
└── RQ4/
    ├── index.json
    └── 42204309_Txxx_RQ4.json
```

当前项目按照 `gold_states.json` 中的 `primary_rq_targets` 生成 RQ1=21、RQ2=25、
RQ3=18、RQ4=16，共 80 个 target/RQ 实例。`primary_rq_targets` 只负责本阶段的
初始收录；每个实例仍将最终 RQ eligibility 标为待审核。

## 先校验、不写文件

建议第一次运行新项目时先执行：

```powershell
python Code/stage2_generate_rq_instances.py `
  --project-id 42204309 `
  --validate-only
```

`--validate-only` 会在内存中完整构建所有实例，并检查：

- Gold、State Graph、消息目录的 `project_id` 是否一致；
- target 消息、顺序、`turns`、Pre/Post boundary 是否一致；
- State ID、Event ID、Requirement ID 是否能严格关联；
- C1 为空、C2 为完整历史、C3 是 C2 的有序子集；
- RQ4 manifest 是否和 target message/Event 一致；
- `reports/target_index.json` 是否与全部 target manifest 一致，项目级
  `validation_report.json.overall` 是否为 `pass`；
- `pre_repo.zip` 是否可读、CRC 是否正确，是否存在路径穿越、符号链接或 `.git`；
- 所有实例是否满足 `rq-instance-v1` 的核心结构约束。

校验不会调用网络，也不会解压 Code Environment。

## 实例中的关键字段

每个实例都是 researcher-side construction record，公共字段结构一致：

```json
{
  "schema_version": "rq-instance-v1",
  "instance_id": "42204309_T003_RQ2",
  "project_id": "42204309",
  "rq_id": "RQ2",
  "target_id": "42204309_T003",
  "target_message_id": 158,
  "turns": 157,
  "history_turn_count": 157,
  "difficulty": "LONG",
  "question": "...",
  "target_task": {},
  "history_pool": {},
  "condition_inputs": {},
  "response_contract": {},
  "construction_gold": {}
}
```

### `turns` 与难度

`turns` 必须保留在实例顶层，定义为规范化对话顺序中严格早于 target message 的
消息数。构造器还保留同值的 `history_turn_count` 以兼容 Stage 2 Gold，并确定性派生：

| difficulty | turns |
|---|---:|
| `SHORT` | 0–25 |
| `MEDIUM` | 26–50 |
| `LONG` | >50 |

程序不会使用 message ID 的数值大小猜测 turn 数，而是使用
`normalized_project.messages` 的真实顺序。声明值与实际值不一致时，整个 target 构建失败。

### 历史条件

`history_pool.messages` 保存 target 之前的完整脱敏历史，每条消息只保留
`message_id`、`created_ts`、`speaker`、`text` 和 `milestone`。具体条件通过
`condition_inputs.<condition>.history_message_ids` 引用该池：

- `C1`：No History，消息列表为空；
- `C2`：Full History，包含完整 pre-task 历史；
- `C3`：Oracle Relevant History，当前由直接相关 Requirement 的完整 Event trajectory
  自动生成。

RQ1 只开放 C2；RQ2、RQ3、RQ4 开放 C1/C2/C3。C3 当前尚未加入需人工判断的继承约束
和指代上下文，因此实例中会显示
`PENDING_CONTEXT_AND_INHERITED_CONSTRAINT_REVIEW`，不能直接把它当作最终 Oracle Gold。

### 四类实例分别保存什么

- RQ1：历史 Requirement 选择、current-support evidence、完整 temporal trajectory、
  core message IDs，以及新 Requirement 的分离记录。
- RQ2：直接相关历史 Requirement 在 target 前的完整五维状态：attributes、scope、
  lifecycle、ambiguity、execution，并保留 provenance。
- RQ3：`ACT/CLARIFY` 候选、OPEN ambiguity 候选和 condition-specific review 状态。
  OPEN ambiguity 不会被程序直接宣布为最终 blocking ambiguity。
- RQ4：Pre/Post transition、Requirement action 候选、Code Environment 引用和后续
  execution-readiness blockers；本阶段的 acceptance criteria/validator 列表为空。

### `construction_gold` 不是 Agent 输入

实例文件包含 `construction_gold`，是为了后续人工审核和 evaluator 构建。未来运行器必须
根据 `condition_inputs` 物化 Agent 可见输入，并隐藏：

- `construction_gold`；
- `source_artifacts`；
- `selection_basis`；
- Requirement/Event/State 内部 ID 及其他由这些字段派生的答案。

当前代码故意不实现运行器，避免在“实例构造”和“评估”之间形成隐式泄漏。

## RQ4 的压缩包处理

实例生成时不需要也不会解压 `pre_repo.zip`。构造器只做流式哈希和 zip 安全检查，并在
`code_environment` 中记录：

- `archive_path` 和 `manifest_path`；
- `manifest_sha256`、项目 validation report/target index 的路径与 SHA-256；
- `archive_sha256`：压缩包文件本身的 SHA-256；
- `repository_tree_sha256`：manifest 中的解压后仓库树 SHA-256；
- 文件数、压缩/解压成员字节数和安全检查结果；
- `workspace_policy = EXTRACT_TO_FRESH_ISOLATED_WORKSPACE_PER_RUN`；
- `extracted_during_instance_construction = false`。

后续真正评估 RQ4 时，运行器应为每次 target-condition run 创建全新的隔离目录，再把
压缩包解压进去；不得在实例目录中原地解压，也不得跨 run 复用被 Agent 修改过的目录。

## 自定义路径

目录不符合默认布局时，可显式指定所有输入和输出：

```powershell
python Code/stage2_generate_rq_instances.py `
  --project-id 42204309 `
  --gold-states outputs/stage2/42204309/gold_states.json `
  --state-graph outputs/stage2/42204309/requirement_state_graph.json `
  --messages outputs/stage1_runs/42204309/normalized_project.json `
  --code-environment-dir "Code Environment/42204309" `
  --output-dir outputs/stage2/42204309
```

如果已经显式给出 `--gold-states`，也可以省略 `--project-id`；程序会从 Gold State
读取项目 ID。其他路径仍可按推导出的 ID 使用默认值。

## 索引与重复运行

每个 RQ 文件夹中的 `index.json` 是该文件夹当前有效实例的权威列表，记录文件名、target、
`turns`、difficulty 和聚合统计。项目根部的 `rq_instance_manifest.json` 记录四类实例总数、
输入文件 SHA-256 和本阶段边界。

重复运行会原子覆盖同名实例、索引和 manifest。生成器不会擅自删除文件夹中未被当前
index 引用的人工文件；如果 target selection 后续发生变化，应以新 `index.json` 为准，
再人工确认是否清理旧的未引用实例。

## 测试

```powershell
python -m unittest Code.tests.test_stage2_rq_instances -v
```

测试覆盖四类实例、`turns`/difficulty 边界、RQ tag 收录、Pre-state 重建、ambiguity/action
候选、RQ4 zip 引用、失败 reconstruction report 拒绝、历史计数不一致拒绝，以及 zip
路径穿越拒绝。

## 当前阶段明确未做的事情

- 不运行 Agent；
- 不生成 C1/C2/C3 的独立评估 workspace；
- 不计算 RQ metrics；
- 不把启发式 ambiguity candidate 当成最终 RQ3 Gold；
- 不自动判定 preserved Requirement 中哪些是 inherited constraints；
- 不生成 RQ4 acceptance criteria、hidden validators 或 reference patch。

这些工作应在实例人工审核完成后进入独立的 evaluation 阶段。

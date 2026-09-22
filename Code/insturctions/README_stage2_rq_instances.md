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

当前项目按确定性 `applicable_rqs` 规则生成 RQ1=25、RQ2=25、RQ3=25、RQ4=17，
共 92 个 target/RQ 实例。RQ1/RQ2 要求存在 relevant historical Requirement；RQ3 要求
存在 affected target transition；RQ4 要求 RQ3 的自动 decision candidate 为 ACT，并且同一
target 有 C_env。Gold State 中遗留的 `primary_rq_targets` 不再参与收录。

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
  "applicable_rqs": ["RQ1", "RQ2", "RQ3", "RQ4"],
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

RQ1 只开放 C2；RQ2 只开放 C2/C3；RQ3、RQ4 开放 C1/C2/C3。C3 由 RQ1 Gold 中直接相关
Requirement 的完整 Event trajectory 确定性生成，状态为
`DETERMINISTIC_DIRECT_TRAJECTORY_ONLY`。preserved/inherited Requirements 不属于当前 RQ1/RQ2
Gold 的操作性范围。

### 四类实例分别保存什么

- RQ1：Independent Requirement Atoms、按 Event 聚合的 current-support evidence groups、
  same-family trajectory neutral context、完整 temporal trajectory，以及新 Requirement 的分离
  记录。同一 Event 的 source/supporting messages 是同组 alternatives；target 当下或之后的
  supporting message 会被过滤。RQ1 Gold 使用 `DETERMINISTIC_RQ1_GOLD`，不需要 Human Review。
- RQ2：matched historical Requirement 在 target 前的完整 (G(t^-))：attributes、scope、
  lifecycle、ambiguity、execution，以及 typed field comparator specs；可评分 State 不含内部 ID，
  ambiguity 使用 record array；不负责 selection，也不把当前 task 写入 Pre-task State。
- RQ3：affected Requirement transition、完整 Post-task State、`ACT/CLARIFY` 候选、结构化
  OPEN ambiguity 候选、field-level `changed_paths/removed_paths` 和 condition-specific review 状态。
  ACT branch 构造 closed-world (G(t^+))，CLARIFY branch 要定位 blocking
  Requirement/dimension/field。
- RQ4：Pre/Post transition、Requirement action 候选、Code Environment 引用和后续
  execution-readiness blockers；本阶段的 acceptance criteria/validator 列表为空。

### `construction_gold` 不是 Agent 输入

实例文件包含 `construction_gold`，是为了 evaluator 构建以及仍为 provisional 的其他 RQ Gold
处理。未来运行器必须
根据 `condition_inputs` 物化 Agent 可见输入，并隐藏：

- `construction_gold`；
- `source_artifacts`；
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

重复运行会原子覆盖同名实例、索引和 manifest，并删除四个 RQ 文件夹中已不再适用的
`<target_id>_RQ*.json`。其他命名的人工文件不会被删除。

## 测试

```powershell
python -m unittest `
  Code.tests.test_stage2_rq_instances `
  Code.tests.test_rq1_evaluation `
  Code.tests.test_rq2_evaluation `
  Code.tests.test_rq3_evaluation -v
```

测试覆盖四类实例、RQ1 Evidence Gold、same-Event alternatives、same-family neutral context、
target boundary、统一 response projection、SAME/MERGED/UNCERTAIN relations、一对一匹配、
Requirement 粒度与 Evidence 评分解耦、错误 evidence、`turns`/difficulty、RQ4 zip 引用和安全拒绝。

## RQ1 自动评价

纯评价逻辑位于 `Code/evaluation/rq1.py`。它不直接访问网络，而是把“一次 LLM judge call”和
确定性评分明确分开。

Agent response 使用 `rq1-agent-response-v3`。下面的 RQ1-only projection 合法：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Periodic small prize reward rule",
      "evidence_message_ids": [21, 56]
    }
  ]
}
```

同一 run 的统一 response 也可直接输入：顶层允许 `decision`、`post_task_states`、
`clarifications`，每个 Requirement 允许 `pre_task_state`。scorer 先按声明白名单验证，再只投影
`requirement_ref`、`requirement_summary`、`evidence_message_ids`；未知字段仍会被拒绝，Runner
无需预先 strip RQ2/RQ3 字段。

先生成该 target 的 all-pairs judge request：

```powershell
python Code/evaluate_rq1.py `
  --instance outputs/stage2/42204309/RQ1/42204309_T001_RQ1.json `
  --agent-response path/to/agent_response.json `
  --alignment-request-out path/to/alignment_request.json
```

把 `alignment_request.json` 整体交给冻结的 Judge model，一次返回
`rq1-alignment-response-v1`。然后执行确定性评分：

```powershell
python Code/evaluate_rq1.py `
  --instance outputs/stage2/42204309/RQ1/42204309_T001_RQ1.json `
  --agent-response path/to/agent_response.json `
  --judge-response path/to/judge_response.json `
  --score-out path/to/rq1_score.json
```

正式输出只有 Requirement Precision/Recall/F1、一个端到端 Evidence Precision/Recall/F1 和
Exact Requirement Set Accuracy。`conditional_evidence_recall_not_official` 仅位于 diagnostics。
Judge 必须覆盖全部 Prediction–Gold pairs；`UNCERTAIN` 和所有非 `SAME_ATOM` relation 自动不匹配，
不进入人工复核。当前安全上限是每个 target 20 个 Gold Atoms 和 50 个 predicted Requirements；
超过上限会明确报错，不会静默丢弃 Prediction。

Evidence 以 target-level claim↔Gold-group 二分匹配独立计分：正确 Gold evidence 即使位于一个
`MERGED_ATOMS`/`SUBPART_OF_ATOM` prediction 中，也不会因粒度错误再次计 FP；只有既不属于任何
Gold acceptable set、也不属于任何 neutral set 的未匹配 claim 才计 FP。Requirement 粒度错误仍
完整保留在 Requirement TP/FP/FN 中。

## RQ2 自动评价

RQ2 使用 `rq2-agent-response-v3`。评分分为两个 Judge request 和最终确定性聚合：

1. 通用 Requirement alignment API 只返回每个 Prediction–Gold pair 的离散 relation；
2. State semantic API 只判断 `SEMANTIC_FACT` 自由文本叶的等价性；
3. enum、number、boolean、set、null、closed-world extra fields 和最终指标全部由本地代码计算。

先生成 alignment request：

```powershell
python Code/evaluate_rq2.py `
  --instance outputs/stage2/42204309/RQ2/42204309_T001_RQ2.json `
  --agent-response path/to/agent_response.json `
  --condition C2 `
  --request-out path/to/rq2_alignment_request.json
```

取得冻结 Judge 的 alignment response 后，生成 State semantic request：

```powershell
python Code/evaluate_rq2.py `
  --instance outputs/stage2/42204309/RQ2/42204309_T001_RQ2.json `
  --agent-response path/to/agent_response.json `
  --condition C2 `
  --alignment-response path/to/alignment_response.json `
  --request-out path/to/rq2_state_request.json
```

最后传入两个 Judge responses 评分：

```powershell
python Code/evaluate_rq2.py `
  --instance outputs/stage2/42204309/RQ2/42204309_T001_RQ2.json `
  --agent-response path/to/agent_response.json `
  --condition C2 `
  --alignment-response path/to/alignment_response.json `
  --semantic-response path/to/state_response.json `
  --score-out path/to/rq2_score.json
```

主指标为 `attribute_reconstruction_score`、五个分维度分数、
`matched_full_state_exact` 和 `reconstruction_coverage`；`matched_state_score` 仅为 auxiliary。
`score_rq2_constant_state_baseline()` 提供 oracle-aligned majority/null 强制 baseline。当前实例状态为
`PROVISIONAL_REQUIRES_FIELD_REVIEW`，scorer 会明确输出 `reporting_eligible=false`，只能用于诊断，
不能发布为正式结果。

## RQ3 Gold 冻结与自动评价

当前自动候选不能直接计分。先为每个 RQ3 target 生成 review template：

```powershell
python Code/finalize_rq3_gold.py `
  --instance outputs/stage2/42204309/RQ3/42204309_T001_RQ3.json `
  --template-out path/to/reviews/42204309_T001.json
```

review 必须覆盖 C1/C2/C3，由至少两名不同审核者完成 adjudication。ACT branch 使用审核后的
完整 construction after-states；CLARIFY branch 必须补齐 blocking Requirement、dimension、可空
field、missing information 和非空 `acceptable_question_facts`。完成后写入新的 frozen instance：

```powershell
python Code/finalize_rq3_gold.py `
  --instance outputs/stage2/42204309/RQ3/42204309_T001_RQ3.json `
  --review path/to/reviews/42204309_T001.json `
  --output-instance path/to/frozen/RQ3/42204309_T001_RQ3.json
```

工具不会原地伪造或自动接受 Gold。未冻结实例交给 `evaluate_rq3.py` 会明确失败。

RQ3 使用 `rq3-agent-response-v3`。ACT item 必须包含完整 closed-world `state` 与
`removed_attribute_keys`；CLARIFY item 必须包含实际 question。若 Agent 选择错误 branch，
scorer 直接产生 decision/error score，不调用 API；branch 正确时依次生成 Requirement alignment
request 和 branch semantic request：

```powershell
python Code/evaluate_rq3.py `
  --instance path/to/frozen/RQ3/42204309_T001_RQ3.json `
  --agent-response path/to/agent_response.json `
  --condition C1 `
  --request-out path/to/rq3_alignment_request.json

python Code/evaluate_rq3.py `
  --instance path/to/frozen/RQ3/42204309_T001_RQ3.json `
  --agent-response path/to/agent_response.json `
  --condition C1 `
  --alignment-response path/to/alignment_response.json `
  --request-out path/to/rq3_branch_semantic_request.json

python Code/evaluate_rq3.py `
  --instance path/to/frozen/RQ3/42204309_T001_RQ3.json `
  --agent-response path/to/agent_response.json `
  --condition C1 `
  --alignment-response path/to/alignment_response.json `
  --semantic-response path/to/branch_semantic_response.json `
  --score-out path/to/rq3_score.json
```

ACT scoring 覆盖所有 affected Requirements，包括 target 新引入项，并惩罚遗漏和额外项。
CLARIFY scoring 用 exact dimension/field gate、语义 blocker equivalence、question validity 和一对一
matching 计算。聚合时报告 Decision/ Balanced Accuracy、class recalls、Unsupported Autonomy、
Unnecessary Clarification 和 branch-specific metrics；`score_rq3_constant_decision_baseline()` 提供
all-ACT/all-CLARIFY baselines。

## 常见构建报错与处理

| 报错 | 处理方式 |
|---|---|
| `project_id` 或 target message 不一致 | 检查 Gold、State Graph 与 normalized messages 是否来自同一次上游构建 |
| `turns` / `history_turn_count` 不一致 | 重新生成 Stage 2.2 Gold；不要按 message ID 数值手工修改 turn 数 |
| code reconstruction report 未通过 | 先修复 `Code Environment/<project_id>/reports/` 中指出的 boundary/build/test 问题 |
| manifest、target index 或 checksum 不一致 | 重新生成对应 Code Environment，并确认 target 与 `before_message_id` 对齐 |
| zip CRC、路径穿越、符号链接或 `.git` 校验失败 | 修复压缩包来源；不要关闭安全检查继续构建 |
| C3 不是 C2 的有序子集 | 回查 relevant Event trajectory 和 message 映射，不要向 C3 填入 target 或未来消息 |
| 输出目录存在旧实例 | 生成器会删除四个 RQ 文件夹内不再适用的 `<target_id>_RQ*.json`，并重写 `index.json`；其他命名的人工文件不会删除 |

## 当前阶段明确未做的事情

- 不运行 Agent；
- 不生成 C1/C2/C3 的独立评估 workspace；
- 不在 evaluator 内直接调用外部 API；CLI 只生成冻结、可审计的 Judge request 并消费 response；
- 不把启发式 ambiguity candidate 当成最终 RQ3 Gold，也不自动填写双人 review；
- 不自动判定 preserved Requirement 中哪些是 inherited constraints；
- 不生成 RQ4 acceptance criteria、hidden validators 或 reference patch。

RQ1 scorer 已可用；RQ2 scorer 已可生成 provisional diagnostics，但 field review 完成前不具备
报告资格；RQ3 scorer 已可用，但必须先冻结全部 condition-specific Gold；RQ4 仍等待 validators。

## 后续实现顺序

下列步骤覆盖从当前 construction records 到正式 benchmark 的后续实现；其中 schema、
join、Pre/Post state expansion 和基础 C1/C2/C3 materialization 已由当前生成器完成：

1. 定义并校验 `rq-core-instance-v1` schema；
2. 完成 Gold State / State Graph / Code Environment join；
3. 完成 Pre/Post state expansion 和 field delta；
4. 物化 C1/C2 history；
5. 生成 relevant trajectory 和 C3；
6. 使用确定性 RQ1 Gold 和自动 aligner/scorer；
7. 完成 RQ2 field review，冻结可评分/跳过字段并重跑常量 baseline；
8. 优先冻结全部 C1 Gold，再完成 C2/C3 双人 review 与 adjudication；
9. 选择 3–5 个覆盖 MODIFY、REMOVE/DEFER、CLARIFY、RUNTIME_FAILURE 的 pilot targets；
10. 为 pilot 构造 RQ4 hidden validators，并执行 Agent 端到端试验；
11. 根据 pilot 冻结 schema/Judge 配置，再扩展到全部 targets；
12. 输出 project / benchmark statistics、exact binomial CI 和 review agreement。

先用小规模 pilot 验证 response schema、Requirement matching、condition-specific decision
和 code validator，再批量扩展 hidden tests，避免在协议未稳定时全量返工。

## 正式 Benchmark 验收清单

一个 RQ instance 只有在以下条件全部满足时才可进入正式 benchmark：

- [ ] target、Gold State、State Graph、history 和 pre repo join 成功；
- [ ] pre/post temporal boundary 通过；
- [ ] C1/C2/C3 输入按定义生成；
- [ ] C3 保留 relevant temporal trajectory 且不含 gold labels；
- [ ] RQ1 direct relevant set 已按 `DIRECT_AFFECTED_ONLY` 确定性生成；
- [ ] RQ1 evidence labels 可追溯到原消息；
- [ ] RQ2 状态 Gold 完整且 state IDs 可展开；
- [ ] RQ3 按 condition 保存 ACT/CLARIFY Gold；
- [ ] blocking ambiguity 与 clarification target 已审核；
- [ ] RQ4 action taxonomy 与 Pre/Post delta 一致；
- [ ] executable target 具有 behavior-level hidden validators；
- [ ] pre-state、reference post-state 和 regression validation 结果符合预期；
- [ ] public package 不含 future leakage、PII、secret、hidden gold 和 answer-revealing tests；
- [ ] 自动校验 PASS；
- [ ] 人工 review / adjudication 完成；
- [ ] schema version、fingerprint 和 checksums 已冻结。

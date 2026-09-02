# ReqMemBench RQ1–RQ4 Evaluation Design

## 1. 文档状态、目标与适用范围

本文定义 ReqMemBench 在 RQ instance construction 完成之后，如何对 Coding Agent 进行
可复现、可比较、无 Gold 泄漏的正式评估。本文是后续 `public_materializer`、Agent runner、
response parser、Requirement aligner、RQ scorers、RQ4 sandbox、aggregator 和论文实验表格的
设计契约。

本文的权威语义来源依次为：

1. `Constuction_guideline/ReqMemBench_RP_V2.md` 中的论文主张与四个 Research Questions；
2. `Constuction_guideline/DESIGN_RQ_instance_construction.md` 中的 instance、condition、Gold
   和 eligibility 定义；
3. 冻结后的 `rq-instance-v1` 及其人工审核产物；
4. Code Environment 的 boundary、checksum、validation report 和 hidden validators。

本文只设计四个 RQ：

- RQ1 — Relevant Requirement Selection；
- RQ2 — Current Requirement State Reconstruction；
- RQ3 — Memory-or-Clarify Decision；
- RQ4 — Requirement-to-Code Execution。

当前阶段只确定评估结构，不实现 evaluator，也不把现有 provisional candidate 当作最终
Gold。尤其是，任何带有 `PENDING_*`、`is_final_gold=false` 或
`execution_ready=false` 的实例都不能进入论文正式分母。

本文不评价或要求 Agent 暴露 private chain-of-thought。只评价结构化结论、可验证的
message evidence、ACT/CLARIFY 决策、开发动作和最终 repository behavior。

---

## 2. Evaluation 的核心目标

ReqMemBench 的整体评估对象是：

\[
H_{<t^*}+C_{t^{*-}}+q_{t^*}
\rightarrow
G_P(t^{*-})
\rightarrow
\mathrm{Action}.
\]

四个 RQ 不是四个互不相关的排行榜，而是同一能力链上的四个可诊断阶段：

\[
\mathrm{Select}
\rightarrow
\mathrm{Reconstruct}
\rightarrow
\mathrm{Decide}
\rightarrow
\mathrm{Execute}.
\]

正式评估需要同时回答两类问题：

1. **End-to-end capability**：Agent 在真实输入下最终能否安全、正确地处理当前 task？
2. **Stage-specific diagnosis**：失败来自历史选择、状态重建、决策，还是代码执行？

### 2.1 四个 RQ 的主要 estimand

| RQ | Primary estimand | 主要失败含义 |
|---|---|---|
| RQ1 | Agent 从完整历史中找回完整相关 Requirement/evidence、同时排除噪声的能力 | retrieval/selection failure |
| RQ2 | Agent 在给定可见证据下恢复 target 前当前有效 Requirement State 的能力 | temporal/state reasoning failure |
| RQ3 | Agent 在当前 condition 中正确选择 ACT 或 CLARIFY 的能力 | unsafe autonomy 或 unnecessary abstention |
| RQ4 | Agent 把正确 state/action 落实为安全且行为正确的开发结果的能力 | planning/execution failure |

### 2.2 预先定义的核心比较

对 RQ2–RQ4 的同一 target，主要进行以下配对比较：

\[
\Delta_{history}=S_{C2}-S_{C1},
\]

表示完整历史相对于无历史的净收益；

\[
\Delta_{selection}=S_{C3}-S_{C2},
\]

表示移除 irrelevant/stale history 后的收益，即 selection、retrieval 或 full-context
management gap。

这些是 effect estimates，而不是预设必须为正的结论：

- `C2 > C1` 支持历史具有实际价值；
- `C1 > C2` 表示 full history 产生干扰；
- `C3 > C2` 表示 selection/context management 是瓶颈；
- `C3 ≈ C2` 但 RQ2 仍低，表示主要问题是 temporal state reasoning；
- RQ2/RQ3 高但 RQ4 低，表示主要问题是 development execution。

RQ1 只在 C2 下正式评分，不计算 C1/C3 condition effect。C1 没有可选历史，C3 已由 Gold
选择历史，二者都会使 RQ1 的 primary question 失去意义。

### 2.3 可检验研究假设

论文可在正式 benchmark release 前预注册以下假设：

- **H1 — History utility**：在需要历史的 target 上，C2 相比 C1 提高 RQ2–RQ4 表现；
- **H2 — History selection burden**：C3 相比 C2 提高状态重建或最终执行表现；
- **H3 — Temporal reasoning**：即使得到 C3，复杂 lifecycle/override 仍造成显著错误；
- **H4 — Decision calibration**：Agent 能区分可靠 memory 与真正 blocking ambiguity；
- **H5 — Understanding–execution gap**：正确理解 Requirement State 不保证最终代码正确；
- **H6 — Long-history robustness**：性能随 `turns`、历史版本数和 distractor density 变化。

具体假设、primary model comparisons 和统计检验必须在查看 held-out test 结果前冻结。

---

## 3. Evaluation Unit 与实验矩阵

### 3.1 三个不同层级的单位

必须区分：

- **Instance**：一个真实 project target time，对应固定 task、pre-task history 和 pre repo；
- **Run**：某 Agent configuration 在一个 target-condition-replicate 上的一次独立执行；
- **Score unit**：某次 run 在一个 eligible RQ 上的评分记录。

基本运行单位定义为：

\[
Run_{i,c,a,s}
=
Target_i
\times Condition_c
\times AgentConfig_a
\times Replicate_s.
\]

其中 `AgentConfig` 至少包含 Agent framework、backbone model、精确版本、system prompt、
tool configuration、decoding configuration 和资源预算。

### 3.2 Primary：统一端到端运行

论文主实验推荐同一 target-condition run 依次生成：

```text
Visible history + target task + pre-task repository
        ↓
RQ1 evidence / Requirement selection
        ↓
RQ2 current state reconstruction
        ↓
RQ3 ACT or CLARIFY
        ↓
RQ4 planned action + patch or clarification
```

同一次运行的结构化输出被不同 scorer 读取：

- RQ1 只在最终 RQ1-eligible target 的 C2 run 上评分；
- RQ2 在最终 RQ2-eligible target 的 C1/C2/C3 run 上评分；
- RQ3 在最终 RQ3-eligible target 的 C1/C2/C3 run 上评分；
- RQ4 policy/action 在最终 RQ4-policy-eligible target 的 C1/C2/C3 run 上评分；
- RQ4 code execution 只在对应 condition 的 Gold decision 为 ACT 且
  `execution_eligible_by_condition=true` 时评分。

因此，“没有被某 RQ 计分”不表示需要重新运行 Agent，只表示该 run 不进入该 RQ 的分母。

### 3.3 Secondary：Stage-isolated / Oracle-upstream 运行

为了区分 error propagation，另外运行明确标记的诊断协议：

| Diagnostic mode | 给 Agent 的额外信息 | 隔离的能力 |
|---|---|---|
| `ORACLE_RELEVANT_HISTORY` | 原始 C3 messages，不给结构化答案 | RQ2 temporal reasoning，去除 selection burden |
| `ORACLE_CURRENT_STATE` | 经审核的自然语言 current-state record，不含内部 ID | RQ3/RQ4 在正确 state 下的表现 |
| `ORACLE_DECISION_AND_STATE` | 正确 state 与 ACT/CLARIFY policy | 纯 RQ4 planning/execution ceiling |
| `TEXT_ONLY` | 隐藏 repository，仅给对应 history/task | 代码可观察证据的影响，作为可选 ablation |

Oracle-upstream 结果不得与 primary C1/C2/C3 结果混为同一 leaderboard。它们只用于回答：

- RQ2 错误中有多少来自 RQ1 selection；
- RQ3 错误中有多少来自 state reconstruction；
- RQ4 错误中有多少仍然存在于 Gold state/decision 已知时。

### 3.4 RQ-specific 独立运行

如果工程上需要分别调用现有 RQ1–RQ4 response contract，可以生成独立 RQ runs；但这属于
兼容模式。独立运行会改变 Agent 的任务 framing，不能替代统一 end-to-end 主实验，也不能
用于计算严格的四阶段 error propagation。

---

## 4. Benchmark Readiness 与正式 Eligibility

### 4.1 Construction inclusion 不等于 evaluation eligibility

当前实例依据 `primary_rq_targets` 被物化到 RQ 文件夹。该字段只表示 target-selection
阶段认为它可能对某 RQ 有研究价值，不能决定正式分母。

正式 release 必须为每个 `target × RQ × condition` 保存：

```json
{
  "eligibility": "ELIGIBLE",
  "reason_codes": [],
  "review_status": "FROZEN",
  "reviewers": [],
  "adjudication": null
}
```

允许状态只有：

- `ELIGIBLE`：可进入对应 primary denominator；
- `NOT_ELIGIBLE`：有明确、预注册的排除原因；
- `BUILD_BLOCKED`：源 artifact 或 temporal boundary 失败；
- `PENDING_REVIEW`：尚不能运行正式评估。

不得把 `PENDING_REVIEW` 当成负例或零分。

### 4.2 各 RQ 的 readiness gate

| Evaluation view | 必须冻结的 Gold/validator | 正式条件 |
|---|---|---|
| RQ1 | reviewed relevant historical set、inherited constraints、CORE/CONTEXT/IRRELEVANT evidence | 相关历史非空，且 Full History 同时存在真实 distractors |
| RQ2 | reviewed relevant set、Pre-task states、field scoring mask | 至少存在一个可评分 state dimension |
| RQ3 | `project_decision_gold`、`decision_by_condition`、blocking ambiguity、clarification target、safe-subaction policy | condition-specific decision 已双人审核并冻结 |
| RQ4 policy/action | task action、Requirement actions、CLARIFY policy | action taxonomy 覆盖 target 的全部 relevant Requirements |
| RQ4 executable | acceptance criteria、validator groups、C_env、execution eligibility | Gold ACT，且全部 environment/validator readiness gate PASS |

### 4.3 当前 instance 中不能直接计分的字段

以下内容目前只是构造候选：

- `selection_basis.final_rq_eligibility=PENDING_RQ_SPECIFIC_REVIEW`；
- RQ1/RQ2 `construction_gold.status=PROVISIONAL_*`；
- 空的 `inherited_constraint_requirement_ids` 和待审核 C3 CONTEXT；
- RQ3 `project_decision_candidate` 与 `decision_candidates_by_condition`；
- RQ4 `requirement_action_candidates`；
- 空的 `acceptance_criteria`、`validator_ids`；
- `execution_ready=false`。

Evaluator 必须拒绝以这些 candidate 字段生成 paper-grade score。

### 4.4 Dataset split

Train/dev/test 必须按 **project** 划分，不能随机按 target 划分。一个项目内的多个 target
共享大量历史、Requirement 和代码，按 target 划分会产生直接泄漏。

- Development projects：用于 prompt、matching threshold、normalization 和 validator pilot；
- Test projects：Gold、C3 mapping 和 hidden validators 冻结后才运行正式系统；
- 同一 project 的全部 target 必须只属于一个 split；
- release 后对 test Gold 的任何修订都必须提升 release version，并重跑所有受影响系统。

---

## 5. C1/C2/C3 输入条件

### 5.1 Condition 定义

| Condition | Agent 可见历史 | 作用 |
|---|---|---|
| C1 — No History | 空 | 测量 current task + pre-task code 自身能够支持的理解与行动 |
| C2 — Full History | target 前全部脱敏消息 | 测量真实 long-history selection、state reasoning 与干扰 |
| C3 — Oracle Relevant History | reviewed CORE + 必要 CONTEXT 的原始消息 | 去除 unrelated history，但保留完整 temporal reasoning |

RQ1 只在 C2 正式评分；RQ2–RQ4 比较 C1/C2/C3。

### 5.2 唯一允许变化的实验因素

同一 target、Agent configuration 和 replicate 的三个 condition 之间只能改变历史消息集合。
以下内容必须相同：

- target task 文本和 message ID；
- pre-task repository archive/tree hash；
- system/developer/task prompt；
- Agent scaffold 与工具权限；
- public commands；
- network policy；
- token/tool/time budget；
- retry、timeout 和停止规则；
- decoding configuration；
- dependency image、OS、CPU/memory limit。

输入 token 数随 condition 改变是实验处理本身，不通过截断或扩大 C1/C3 budget 补偿。报告中
必须同时披露实际 input tokens、history messages 和 history tokens。

### 5.3 Public materialization

现有 RQ JSON 是 researcher-side construction record，绝不能直接交给 Agent。Materializer
只能读取 `condition_inputs.<C>.history_message_ids`，从 `history_pool.messages` 中按原顺序
选择对应消息，并生成独立 public package。

统一使用同一个文件接口，例如：

```text
workspace_input/
├── task.json
├── history.jsonl       # C1 为空；C2/C3 为对应消息
├── instructions.md
└── repository/         # 安全解压后的 C(t-)
```

这样 C1/C2/C3 的工具接口相同，只改变 `history.jsonl` 的内容。

### 5.4 Repository visibility

Primary end-to-end protocol 遵循论文总任务定义：pre-task repository 对四个阶段均可观察，
因为它是同一 Agent run 的共同上下文。RQ1–RQ3 不因代码修改结果得分，但 Agent 可以把当前
代码作为辅助 evidence；C1 因此严格表示 `current code + current task`，不是纯文本 task。

当前 RQ1–RQ3 construction records 不内嵌 `code_environment`。Materializer 必须通过
`project_id + target_id` 与 C_env index 连接到同一份 pre-task repository；不得从 Gold、
post-task code 或 RQ4 私有字段反向构造该输入。

如果要测量纯 history reasoning，可增加明确标记的 `TEXT_ONLY` ablation。该结果不能与
primary C1/C2/C3 混合。

### 5.5 History delivery 与 context window

- C2 不得静默截断为最近 k 条消息；
- C3 不得因 token budget 删除必要 trajectory；
- 优先把 history 作为可搜索的只读 JSONL/file tool 提供，而不是全部塞进初始 prompt；
- 所有模型必须拥有同一种 history access API；
- 模型不读取已提供的文件属于 Agent 行为，不是 missing input；
- 如果某 Agent framework 无法接受完整输入，应标为 protocol incompatibility，而不是对其
  单独缩短历史；
- `turns` 始终是完整 target 前消息数，不能用 C3 message count 重算 difficulty。

---

## 6. Systems、Baselines 与 Replicates

### 6.1 Agent configuration

每个系统必须记录：

```text
agent framework + exact version/commit
backbone model + exact snapshot/version/date
system prompt hash
task prompt hash
tool schema hash
runner/container image digest
temperature/top_p/seed（如果支持）
context window
token/tool/time budget
network policy
```

只写营销名称或可滚动 alias 不足以复现实验。

### 6.2 必须运行的核心条件

每个被比较的 Agent 至少运行：

- C1；
- C2；
- C3；
- primary unified end-to-end protocol。

无法完成全部三个 condition 的系统不能进入 condition-effect 主表，但可以在单 condition
附表中报告。

### 6.3 内部基线

RP 中列出的其他 benchmark 是 related work，不是可以直接比较分数的 system baseline。
ReqMemBench 至少应包含以下内部基线：

- **No-history baseline**：C1；
- **Full-history baseline**：C2；
- **Oracle-relevant raw-history ceiling**：C3；
- **All-history selection**：RQ1 选择全部 C2 messages；
- **Recency-k retrieval**：只选择最近固定 k 条消息；
- **Lexical retrieval**：BM25/关键词等不使用 hidden labels 的检索器；
- **Always-ACT / Always-CLARIFY / majority**：RQ3 policy baselines；
- **Oracle-state execution**：RQ4 的 stage-isolated ceiling。

Embedding retrieval、learned retriever 或 state-memory system 可以作为扩展 baseline，但必须
使用 project-disjoint development data，不能用 test Gold 调阈值。

### 6.4 随机性与重复运行

- 若系统可以真正固定 seed 且解码确定，可使用一个 primary replicate，并做重复稳定性审计；
- 对无法保证确定性的 Agent，正式设计建议至少 3 个独立 replicates；
- replicate 数、seed list 和汇总方法在 test 前冻结；
- primary 报告使用逐 run score 的预注册汇总，不以“挑最好一次”替代；
- `success@k`、best-of-k 或 majority vote 只能作为 secondary result，并同时报告额外成本。

---

## 7. Agent Run Protocol

### 7.1 Preflight

每次 run 前，Evaluator 必须：

1. 从 RQ `index.json` 枚举实例，不通过 glob 猜测有效文件；
2. 校验 project manifest、instance、Gold release 和 input fingerprints；
3. 验证 target、condition、RQ eligibility；
4. 验证 C1/C2/C3 history invariants；
5. 验证 pre-repo archive SHA、tree SHA、manifest、target boundary；
6. 在 canonical untouched repo 上运行 environment preflight；
7. 确认 hidden assets 不会挂载到 Agent 可访问路径。

Preflight 失败产生 `INFRASTRUCTURE_INVALID`，不启动 Agent，也不计为 Agent failure。

### 7.2 Isolated workspace

每个 `target × condition × agent × replicate` 必须：

- 创建全新临时目录；
- 从已验证的同一个 `pre_repo.zip` 解压；
- 禁止复用之前 condition 或 replicate 修改过的 workspace；
- 默认禁网，或使用所有系统一致的显式 allowlist；
- 设置 CPU、memory、disk、process 和 wall-clock limit；
- 不包含 `.git`、未来代码、未来 tests、Gold 或 hidden validators；
- run 完成后先保存 evidence，再清理 workspace。

### 7.3 Agent 阶段

1. 向 Agent 提供通用任务说明、condition-specific history、target task 和 pre repo；
2. Agent 可检查代码、运行公开命令并编辑 workspace；
3. Agent 必须提交统一结构化 response；
4. `decision=ACT` 时可提交代码变化；
5. `decision=CLARIFY` 时给出具体问题，不获得模拟 client 后续回复；
6. 到达停止条件后冻结 workspace，Agent 不再看到任何 validator feedback。

CLARIFY 在 primary protocol 中是 terminal action。未来如研究 clarification 后继续执行，应作为
独立 multi-step extension，不能混入当前单回合结果。

### 7.4 Evidence capture

每次 run 保存：

- 完整 public input fingerprint；
- Agent structured response；
- stdout/stderr 与工具事件；
- token usage、latency、tool calls、cost；
- timeout/invalid/tool error；
- unified diff、changed-file list、file-mode changes；
- final repository tree hash；
- public command logs；
- hidden validator logs（仅 evaluator-side）。

### 7.5 Retry policy

- API 连接失败、runner crash、host filesystem error 属于 infrastructure fault，可以在固定上限内
  重试，并保存原始失败；
- Agent timeout、无效 JSON、错误工具调用、build failure 或安全违规是 Agent outcome，不自动
  重试到成功；
- 所有重试必须保持相同 run fingerprint，并记录 attempt number；
- 不允许看到 Agent 结果后临时增加预算或换 prompt。

---

## 8. Unified Response 与 Requirement Alignment

### 8.1 Canonical response

现有各 RQ `response_contract` 是字段说明，不是完整 JSON Schema。正式 runner 应冻结一个严格
的统一 schema，例如：

```json
{
  "schema_version": "rq-agent-response-v1",
  "instance_id": "42204309_T003_C2",
  "selected_history_message_ids": [8, 21, 156],
  "requirements": [
    {
      "requirement_ref": "agent-local-prize-rule",
      "requirement_summary": "Small Block prize mechanism",
      "evidence_message_ids": [8, 21, 156],
      "current_state": {
        "attributes": {},
        "scope": {
          "persistence": "PROJECT_PERSISTENT",
          "components": ["BACKEND", "SMART_CONTRACT"],
          "contexts": ["PRIZE_SYSTEM"]
        },
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "ACT",
  "clarification": null,
  "planned_actions": [
    {
      "requirement_ref": "agent-local-prize-rule",
      "action": "MODIFY",
      "summary": "Update the current prize parameters."
    }
  ]
}
```

Schema 必须定义类型、required、enum、nullability、unique items、额外字段策略、最大长度和
message ID 可见性约束。不能在 scorer 中临时猜测非结构化答案。

内部 RQ4 Gold 的 `APPLY_CHANGES` 映射为 Agent response 的 `ACT`；Gold 和 public response
最终应统一名称，mapping table 必须版本化。

### 8.2 Invalid response

- 无法解析、schema 不合法、引用不可见 message ID 或重复 `requirement_ref`，标记
  `AGENT_INVALID_RESPONSE`；
- 不使用 LLM 自动重写 response；
- 可以使用预先冻结的确定性 JSON envelope extraction，但不能补写语义字段；
- invalid response 在所有适用 primary metrics 中计失败，同时单独报告 invalid rate。

### 8.3 Agent-local Requirement 对齐

Agent 不需要猜内部 `REQ_*` ID。Evaluator 使用 prediction–Gold bipartite graph：

1. 为每个 predicted/Gold Requirement 计算 evidence message overlap；
2. 比较规范化 title/summary 和结构化 fact units；
3. 比较 scope/component/context；
4. 生成 matching confidence；
5. 使用 maximum-weight one-to-one matching；
6. 低于冻结阈值、并列或结构冲突时进入 blinded adjudication。

Matching weights、normalization 和 threshold 只能在 development split 上调整，之后写入
`matching_config_version`。LLM judge 不得静默决定 primary alignment。

- unmatched Gold Requirement 是 false negative；
- unmatched prediction 是 false positive；
- 一个 prediction 不能同时匹配多个 Gold Requirements；
- 同一 source message 可以为多个 Gold Requirements 提供 evidence；
- matching 结果与 confidence 必须作为 score artifact 保存。

---

## 9. RQ1 — Relevant Requirement Selection Evaluation

### 9.1 Eligibility 与输入

RQ1 只评价 C2，并要求：

- reviewed `relevant_requirement_ids` 非空；
- relevant set 已包括 applicable inherited constraints；
- CORE、CONTEXT、IRRELEVANT labels 已冻结；
- Full History 中确实存在 unrelated/stale distractors；
- target 不能只凭当前 message 完整作答。

新 Requirement 保存在 `new_requirement_ids`，但不进入 historical Requirement recall 分母。

### 9.2 Requirement selection metrics

对已对齐 prediction，定义：

\[
P_{req}=\frac{TP_{req}}{TP_{req}+FP_{req}},\qquad
R_{req}=\frac{TP_{req}}{TP_{req}+FN_{req}},
\]

\[
F1_{req}=\frac{2P_{req}R_{req}}{P_{req}+R_{req}}.
\]

Primary metrics：

- Requirement Precision / Recall / F1；
- exact relevant-Requirement set accuracy；
- direct-affected historical recall；
- inherited-constraint recall。

若 Gold 非空而 prediction 为空，Precision、Recall 和 F1 均按 0 处理，避免 undefined 值被
错误排除。

### 9.3 Evidence message metrics

设：

- $S$：Agent 选择的 history message IDs；
- $G_{core}$：Gold CORE message IDs；
- $G_{ctx}$：容许但不承载 primary fact 的 CONTEXT IDs；
- $U$：C2 的全部 message IDs；
- $G_{irr}=U\setminus(G_{core}\cup G_{ctx})$。

则：

\[
TP=|S\cap G_{core}|,\quad
FN=|G_{core}\setminus S|,\quad
FP=|S\cap G_{irr}|.
\]

CONTEXT selection 既不增加 TP，也不计 FP。报告：

- CORE evidence Precision / Recall / F1；
- exact CORE coverage；
- current-support message recall；
- temporal-trajectory message recall；
- irrelevant selection rate：$|S\cap G_{irr}|/|G_{irr}|$；
- selected-noise ratio：$|S\cap G_{irr}|/\max(1,|S|)$。

只选择 CONTEXT、没有任何 CORE 时，CORE Precision/Recall/F1 均为 0。

### 9.4 New-Requirement false retrieval

如果 target 新引入 Requirement，Agent 可以正确描述它，但不能声称它已有历史 evidence。
报告：

\[
NewFalseRetrievalRate
=
\frac{\#\text{new Requirements assigned non-empty historical evidence}}
{\#\text{new Requirements}}.
\]

该指标没有适用 new Requirement 时记为 N/A，不作为 0 或 1 聚合。

---

## 10. RQ2 — Current Requirement State Reconstruction Evaluation

### 10.1 Gold boundary

RQ2 Gold 是 target message 发生前：

\[
G_P(t^{*-})|_{\mathcal{R}^{hist}(q)}.
\]

它不是 Post-task State，也不是项目结束状态。REMOVED、DEFERRED 或 OPEN ambiguity 都可能是
需要恢复的有效当前状态，不能只保留 ACTIVE Requirements。

### 10.2 Field scoring mask

正式 Gold 应为每个 state field 保存：

- `SCORE`：存在明确 Gold，包括明确的 `null`/empty；
- `NOT_OBSERVABLE`：即使使用完整、合法的 benchmark evidence 也无法建立可靠 Gold，不进入
  任何 condition 的分母；
- `NOT_APPLICABLE`：该维度对该 Requirement 不适用。

该 mask 在 C1/C2/C3 间必须保持不变。某个 `SCORE` 字段仅因 C1 隐藏了历史而无法恢复，是
实验处理产生的困难，仍然要按同一 Gold 评分；不能事后改为 `NOT_OBSERVABLE`，否则会消除
`C2 − C1` 所要测量的 history benefit。

明确 `null` 与 unknown 不同：例如 Gold `ambiguity=null` 表示没有 OPEN ambiguity，Agent
凭空报告 ambiguity 应被扣分；而 incomplete observed baseline 上真正未知的字段不应被当成
空值 exact match。

### 10.3 Field matching

- typed scalar / enum / boolean：规范化后 exact；
- numeric、currency、duration：先按冻结的单位规则规范化，再 exact；
- unordered set：set Precision/Recall/F1；
- ordered business rule：保持顺序，按 list fact unit 评分；
- nested attributes：展开为 typed fact units，额外冲突值计 false positive；
- lifecycle：exact；
- scope：分别评价 persistence、components 和 contexts；
- ambiguity：OPEN/null、dimension 为 primary exact fields，description 为诊断；
- execution：status 为 primary exact，observed behavior 使用预定义 fact units。

禁止使用开放式 LLM “看起来相似”分数作为 primary field score。

### 10.4 State metrics

先完成 Requirement alignment。对每个 dimension $d$：

\[
S_{d,e2e}
=
\frac{1}{|R_d|}
\sum_{r\in R_d}s_{r,d},
\]

其中 unmatched Gold Requirement 的 $s_{r,d}=0$；`NOT_OBSERVABLE/NOT_APPLICABLE` 不进入
$R_d$。

另外报告：

\[
S_{d,matched}
=
\frac{1}{|M_d|}
\sum_{r\in M_d}s_{r,d},
\]

只在成功对齐的 Requirement 上测量 state quality。

Task-level primary scores：

\[
StateE2E
=
\operatorname{mean}
(S_{selection},S_{attr},S_{life},S_{scope},S_{amb},S_{exec}),
\]

\[
StateConditional
=
\operatorname{mean}
(S_{attr,matched},S_{life,matched},S_{scope,matched},
S_{amb,matched},S_{exec,matched}).
\]

仅包含有适用 Gold 的 dimension。还必须报告：

- strict full-state exact accuracy；
- lifecycle exact accuracy；
- persistence exact accuracy；
- attribute fact F1；
- ambiguity exact accuracy；
- execution-status accuracy。

### 10.5 Temporal error taxonomy

Scorer 额外输出非 primary 的 error flags：

- `STALE_VALUE_RETAINED`；
- `LATEST_OVERRIDE_MISSED`；
- `REMOVED_AS_ACTIVE`；
- `DEFERRED_AS_ACTIVE`；
- `PERSISTENCE_OVERGENERALIZED`；
- `PERSISTENT_RULE_DROPPED`；
- `RESOLVED_AMBIGUITY_REOPENED`；
- `OPEN_AMBIGUITY_IGNORED`；
- `EXECUTION_FAILURE_IGNORED`；
- `FREELANCER_CLAIM_AS_CLIENT_VALUE`。

这些 flags 用于解释结果，不替代 field scores。

---

## 11. RQ3 — Memory-or-Clarify Decision Evaluation

### 11.1 Binary primary policy

Primary task-level decision 只有：

- `ACT`；
- `CLARIFY`。

多 Requirement task 中即使存在 safe subactions，只要一个 mandatory dimension 被 blocking
ambiguity 阻塞，task-level Gold 仍是 CLARIFY。是否允许执行 safe subactions 由独立冻结的
policy 保存：

- `FORBID_ALL_CHANGES`；
- `ALLOW_LISTED_SAFE_SUBACTIONS`。

不临时增加 `PARTIAL_ACT_WITH_CLARIFICATION` 第三类，否则会破坏预定义 binary metrics。

### 11.2 Condition-specific Gold

每个 eligible target 保存：

- `project_decision_gold`：完整合法项目证据下的 ACT/CLARIFY；
- `decision_by_condition.C1/C2/C3`；
- blocking Requirement、dimension 和 reason；
- clarification target；
- safe-subaction policy。

C2 与 C3 的 normative decision 必须一致。若不一致，说明 C3 缺少必要 evidence 或 C2
materialization 有误，target 不能进入正式评估。

不能从“存在任意 OPEN ambiguity”自动得到 CLARIFY。必须满足 materiality、task relevance、
alternative implementation 和 available-evidence tests。

### 11.3 Primary metrics

- Accuracy；
- Macro F1；
- ACT recall；
- CLARIFY recall；
- confusion matrix。

安全相关错误单独报告：

\[
UnsupportedAutonomyRate
=
\frac{\#(Gold=CLARIFY,Pred=ACT)}{\#(Gold=CLARIFY)},
\]

\[
UnnecessaryClarificationRate
=
\frac{\#(Gold=ACT,Pred=CLARIFY)}{\#(Gold=ACT)}.
\]

两者不得合并成一个不透明 accuracy。若论文使用 asymmetric cost，权重必须预注册，并作为
sensitivity analysis，而不是事后挑选。

### 11.4 Clarification quality

只对 Gold CLARIFY 的 run 评价：

- decision 是否为 CLARIFY；
- question 是否指向正确 Requirement；
- 是否指向正确 state dimension；
- 是否询问真正缺失的决定；
- 是否避免重复询问已明确事实；
- 是否足以让 client 给出可执行答案。

Primary `clarification_target_accuracy` 要求 Requirement 与 dimension 同时命中。开放文本的
actionability 采用冻结 rubric、双人 blinded review；同时报告 decision-correct 条件下和
end-to-end 两种分数。

### 11.5 Memory-enabled actionability

另外报告：

- project-decision accuracy；
- C1 missing-history gap；
- 在 `project_decision_gold=ACT` 且 C1 Gold 为 CLARIFY 的 targets 中，C2/C3 能否恢复 ACT；
- safe-subaction policy compliance。

这些是 secondary diagnostics，不与 condition-specific primary accuracy 混合。

---

## 12. RQ4 — Requirement-to-Code Execution Evaluation

### 12.1 两个分母

RQ4 必须分成：

1. **Policy/action evaluation**：所有 final RQ4-policy-eligible conditions；
2. **Executable code evaluation**：只包含 Gold ACT 且 validators ready 的 conditions。

Gold CLARIFY 不进入 coding-success 分母，但仍进入 RQ4 task-action/policy 分母。这样不会把
安全 clarification 错判为 coding failure，也不会让总是 CLARIFY 的 Agent 获得虚假 coding
success。

### 12.2 Action taxonomy

论文主 taxonomy：

- `IMPLEMENT`；
- `MODIFY`；
- `REMOVE`；
- `PRESERVE`；
- task-level `CLARIFY`。

内部 operation `DEFER/RESUME/REPAIR/VERIFY` 必须通过冻结 mapping 归入主 taxonomy，同时
保留原 operation 作为 diagnostic。

Predicted planned actions 通过同一个 Requirement aligner 对齐。报告：

- requirement-level action macro accuracy；
- task-level exact action-set success；
- affected Requirement action recall；
- inherited-constraint PRESERVE recall；
- forbidden speculative action rate。

### 12.3 Environment 与 validator readiness

每个 executable target 必须在 Agent run 前完成：

1. archive SHA、manifest SHA、tree SHA 与 target index 一致；
2. `before_message_id` 和 target Event boundary 一致；
3. safe extraction、secret、PII、`.git`、future leakage scan PASS；
4. clean install/build/public smoke PASS；
5. acceptance criteria 已审核；
6. target/negative/inherited/regression validators 已实现；
7. pre-state 产生预期 fail、reference/canonical post-state PASS；
8. validator 不绑定唯一 patch 或内部实现细节；
9. observed/reconstructed/simulated substrate 已明确标记。

任何一项失败都使 `execution_eligible_by_condition=false`，而不是给 Agent 记 0。

### 12.4 Hidden validation layers

Gold ACT run 在 Agent 停止后依次运行：

1. **Security gate**：secret、forbidden path、hidden access、network violation；
2. **Environment/build gate**：install、format/lint、compile/build；
3. **Target behavior gate**：target 新增/修改行为；
4. **Negative/removal gate**：old/removed/deferred/forbidden 行为不再存在；
5. **Inherited-constraint gate**：relevant preserved Requirements 仍满足；
6. **Regression gate**：高风险未受影响功能仍通过；
7. **Temporal-fixture gate**：pre defect 可复现且 patch 后消失；
8. **Repository integrity gate**：无无关破坏、最终 tree 可记录。

每组 validator 保存 `mandatory`、acceptance-criterion ID、Requirement mapping 和结果。
Agent 不能看到 hidden command、源码或输出。

### 12.5 RQ4 metrics

Primary/secondary metrics：

- decision/policy correctness；
- requirement action accuracy；
- task exact action success；
- post-Agent build success；
- target behavior criterion pass rate；
- negative/removal criterion pass rate；
- inherited-constraint pass rate；
- regression-free rate；
- temporal-fixture repair success；
- security compliance；
- coding full-task success。

Gold ACT 的 strict coding success：

\[
FullCodeSuccess
=
\mathbf{1}[
DecisionCorrect
\land RequiredActionsCorrect
\land AllMandatoryGatesPass
].
\]

测试数量不能直接决定 task 权重。先把 validator assertions 聚合到 acceptance criterion，再聚合
到 Requirement 和 task，避免测试更多的 target 权重更大。

### 12.6 Gold CLARIFY branch

Gold CLARIFY run 的 RQ4 success 要求：

- Agent decision 为 CLARIFY；
- clarification target 正确；
- blocked source area 没有 speculative change；
- `FORBID_ALL_CHANGES` 时 source tree 不变；
- `ALLOW_LISTED_SAFE_SUBACTIONS` 时仅执行明确允许的 changes，并通过对应 validators。

该结果命名为 `clarification_policy_success` 或 `rq4_task_success`，不能命名为 code pass。

### 12.7 Agent failure 与 environment failure

- preflight environment 失败：`INFRASTRUCTURE_INVALID`，不进入分母；
- preflight 通过、Agent 修改后 build 失败：Agent RQ4 failure；
- evaluator/validator crash：infrastructure retry；
- Agent timeout：Agent failure；
- security violation：Agent failure，并单独报告；
- public tests PASS 但 hidden target tests FAIL：functional failure。

不通过 patch 与唯一 reference diff 的文本相似度决定正确性。

---

## 13. End-to-End 与 Error Propagation

### 13.1 严格端到端成功

对四个 RQ 都 eligible 的 C2 run，可定义：

\[
E2ESuccess_i
=
\mathbf{1}[
RQ1_i\land RQ2_i\land RQ3_i\land RQ4_i
].
\]

这里每一阶段的“成功”阈值必须在 test 前冻结。为了避免阈值掩盖连续分数，论文同时报告各
阶段原始 metric，不只报告 E2E binary。

### 13.2 Conditional diagnostics

报告：

\[
P(RQ2\ success\mid RQ1\ success),
\]

\[
P(RQ3\ success\mid RQ1,RQ2\ success),
\]

\[
P(RQ4\ success\mid RQ1,RQ2,RQ3\ success).
\]

这些是诊断性条件统计，不作为因果证明，也不替代 primary marginal scores。

### 13.3 Pipeline–Oracle gap

对同一 eligible target，计算：

\[
\Delta_{state\rightarrow code}
=
S_{RQ4}^{OracleState}-S_{RQ4}^{Pipeline}.
\]

- 大 gap：上游 Requirement understanding/decision 是主要限制；
- 两者都低：即使提供正确 state，Agent 的 planning/coding/verification 仍然困难；
- Pipeline 高但显式 RQ2 低：检查 response schema、Requirement alignment 或 Agent
  “代码做对但解释错”的现象。

### 13.4 Failure attribution

每个 task 保存最早失败阶段和所有并发失败：

- `RQ1_SELECTION_FAILURE`；
- `RQ2_STATE_FAILURE`；
- `RQ3_POLICY_FAILURE`；
- `RQ4_ACTION_FAILURE`；
- `RQ4_EXECUTION_FAILURE`；
- `MULTIPLE_FAILURES`。

不能仅以“最早失败”抹去后续 independently observable failure。

---

## 14. Metrics Aggregation 与统计分析

### 14.1 聚合层级

Primary aggregation：

```text
Field → Requirement → Task → Project → Benchmark
```

对每个 Agent/config/condition/metric：

1. replicate 先按预注册规则聚合到 target；
2. target 在项目内 macro average；
3. project 再做 benchmark-level macro average。

形式化为：

\[
S_{p} = \frac{1}{|I_p|}\sum_{i\in I_p}S_i,
\qquad
S_{bench}=\frac{1}{|P|}\sum_{p\in P}S_p.
\]

这避免 target、Requirement、attribute 或 validator 更多的项目获得不成比例权重。Micro average
可作为 supplemental result，但不能替代 project macro primary result。

### 14.2 Eligibility 与 paired set

- 每个 metric 只在其 frozen eligible set 上聚合；
- condition effect 使用同一 Agent 在 C1/C2/C3 都具有有效结果的 paired targets；
- `NOT_ELIGIBLE` 不进入分母；
- Agent invalid/timeout 在 eligible set 中计失败；
- 每个表必须给出 project 数、target 数、run 数和 missing/invalid 数。

### 14.3 Confidence intervals

- 95% CI 以 project 为 cluster 进行 bootstrap；
- condition/model difference 使用 project-level paired bootstrap；
- 不能把同一 project 的多个 targets 当作独立样本；
- stochastic replicates 先在 target 内聚合，再 resample projects；
- binary paired outcome 可补充 clustered/stratified McNemar-style analysis；
- project 数过少时，不报告虚假的窄 CI，只给 project-wise descriptive result。

Bootstrap seed、replicate count 和 interval method 必须写入 evaluation config。

### 14.4 显著性与多重比较

- 预先指定 primary model pairs、RQ metrics 和 condition contrasts；
- 报告 paired effect size 与 CI，不只报告 p-value；
- 多模型、多 RQ 的 confirmatory tests 使用 Holm correction；
- exploratory slices 明确标为 exploratory，不对其过度解释；
- 不在看到 test 结果后选择最有利的 RQ threshold 或 matching threshold。

### 14.5 Sample size

正式 benchmark 在 project level 做 power/sensitivity analysis。一个 project 的 25 个 targets
不是 25 个独立 project samples。若 project 数不足，论文必须把结果描述为 pilot/case study，
而不是跨项目泛化结论。

---

## 15. 必须报告的切片

每个切片必须同时给出 denominator，样本过小时只作描述：

- C1/C2/C3；
- `turns`：SHORT 0–25、MEDIUM 26–50、LONG >50；
- history message/token count 与 distractor density；
- INTRODUCE/MODIFY/REMOVE/DEFER/RESUME；
- override/version count；
- lifecycle status；
- ambiguity dimension VALUE/SCOPE/LIFECYCLE；
- Gold ACT/CLARIFY；
- single vs multi-Requirement task；
- direct affected vs inherited constraint；
- runtime-failure/verification target；
- single vs multi-component/shared-file；
- observed vs reconstructed/simulated code substrate；
- Agent framework、backbone model 和 exact version。

不得把 `turns` 当 target quality 分数，也不得因为某一当前项目全部为 LONG 就推断 difficulty
effect。

---

## 16. Run Status、Missingness 与 Denominator Policy

建议统一状态：

| Status | 含义 | Primary denominator |
|---|---|---|
| `COMPLETED` | response 与所需 artifacts 完整 | 进入 |
| `AGENT_INVALID_RESPONSE` | response schema/visible-ID 违规 | 进入并计失败 |
| `AGENT_TIMEOUT` | Agent 超出预算 | 进入并计失败 |
| `AGENT_TOOL_ERROR` | Agent 自身工具使用导致失败 | 进入并计失败 |
| `AGENT_SECURITY_VIOLATION` | 访问禁止资源、泄密或越界 | 进入并计失败 |
| `INFRASTRUCTURE_INVALID` | runner、host、preflight 或 validator infrastructure 故障 | 暂不进入，修复后重跑 |
| `NOT_ELIGIBLE` | Gold/validator 定义上不适用 | 不进入 |
| `PENDING_REVIEW` | benchmark 尚未冻结 | 禁止正式运行 |

必须同时发布 raw count 和排除原因。不得把难例标为 infrastructure invalid，也不得因为 Agent
失败而事后改成 not eligible。

---

## 17. Human Review 与 Adjudication

### 17.1 Gold freeze review

人工审核必须在查看正式系统输出前完成：

- inherited constraints 的 causal necessity；
- C3 必要 CONTEXT 与 excluded distractors；
- blocking ambiguity materiality；
- C1 evidence sufficiency；
- condition-specific RQ3 decision；
- multi-Requirement safe-subaction policy；
- RQ4 expected actions；
- acceptance criteria 和 hidden validator behavior coverage。

### 17.2 强制双人审核

以下 instances 至少两名 reviewer 独立判断：

- Gold CLARIFY；
- REMOVE/DEFER/RESUME；
- 多 Requirement；
- inherited constraint；
- runtime failure/verification；
- shared files/multiple components；
- reconstructed/simulated substrate 上的 RQ4。

不一致由第三人 adjudicate。报告 field-level agreement：categorical fields 使用 Cohen's
kappa 或 Krippendorff's alpha；set/continuous fields 报告相应 agreement/F1，而不是只报告
整条 instance 是否完全相同。

### 17.3 Prediction matching 与 clarification review

- reviewer 对 system/model/condition 身份 blinded；
- 全部低 confidence/tie matching 强制审核；
- 从高 confidence 自动 matching 中抽取预注册比例做质量审计；
- clarification actionability 按冻结 rubric 双人审核；
- LLM judge 可以作为 secondary analysis，但不能决定 primary Gold、alignment 或 score。

### 17.4 Gold issue protocol

如果正式运行后发现 Gold/validator 错误：

1. 停止受影响分析；
2. 创建 issue 与可追溯理由；
3. reviewer 在不知道具体模型排名的条件下修订；
4. 提升 benchmark release version；
5. 对所有系统重跑受影响实例；
6. 同时保留旧版结果和 change log。

---

## 18. Leakage、Security 与 Reproducibility

### 18.1 Public/Private separation

Agent workspace 不得出现：

- 整份 researcher-side RQ instance；
- `construction_gold`；
- `source_artifacts`、`selection_basis`；
- Requirement/Event/State IDs；
- `primary_rq_targets`、affected/preserved IDs；
- RQ4 `requirements_to_code`、temporal fixture metadata；
- acceptance criteria、hidden validators、reference implementation；
- target 后的 conversation/code/tests；
- evaluator logs 或其他 system runs。

尤其不能把包含完整 `history_pool` 的 C1/C3 instance 文件直接复制到 workspace；必须由
materializer 写出裁剪后的独立 `history.jsonl`。

### 18.2 Evidence precedence

当代码与 client history 不一致时：

- 明确、较新且权威的 client Requirement 决定 normative state；
- code 是当前实现状态的可观察证据，不能自动覆盖 client 的明确新要求；
- runtime evidence 可以更新 execution dimension，但不能无依据改写 client value/scope；
- unresolved material conflict 进入 RQ3，而不是由 scorer 替 Agent 猜测。

### 18.3 Fingerprint

每次 run 至少冻结：

```text
benchmark_release_id
instance JSON SHA
condition message-ID list SHA
public input SHA
pre-repo archive/tree SHA
prompt/tool schema SHA
Agent/model/version
container image digest
validator bundle SHA
evaluation config SHA
seed/replicate
```

Resume 只允许复用 fingerprint 完全一致的 run。任何 prompt、Gold、validator、model alias 或
tool schema 变化都必须产生新 evaluation ID。

### 18.4 Contamination 与审计

- test Gold 与 validators 尽量保持 private；
- 记录 benchmark release date 与模型 snapshot date；
- 检查 public README/tests/TODO/manifest 是否泄漏答案；
- 保存 Agent 访问文件与网络事件，检测 hidden-data probing；
- 发布不含个人信息、secret 和内部路径的可复现实验 manifest。

---

## 19. Evaluation Artifacts 与目录结构

建议把运行结果与 Stage 2 construction artifacts 分开：

```text
outputs/evaluation/<evaluation_id>/
├── evaluation_manifest.json
├── config/
│   ├── evaluation_config.json
│   ├── agent_configs/
│   ├── prompt_fingerprints.json
│   └── benchmark_release.json
├── public_inputs/
│   └── <project>/<target>/<condition>/
├── runs/
│   └── <agent>/<project>/<target>/<condition>/replicate_<n>/
│       ├── run_manifest.json
│       ├── agent_response.json
│       ├── tool_events.jsonl
│       ├── stdout.log
│       ├── stderr.log
│       ├── patch.diff
│       ├── changed_files.json
│       ├── final_repo_manifest.json
│       └── status.json
├── scores/
│   └── <agent>/<project>/<target>/<condition>/replicate_<n>/
│       ├── requirement_alignment.json
│       ├── rq1_score.json
│       ├── rq2_score.json
│       ├── rq3_score.json
│       ├── rq4_score.json
│       └── validator_results.json
└── reports/
    ├── eligibility_and_denominators.json
    ├── main_results.json
    ├── condition_effects.json
    ├── error_propagation.json
    ├── slice_results.json
    ├── cost_and_latency.json
    └── human_review_agreement.json
```

Private Gold、hidden validators 和 reference repos 放在 runner-only protected root，不复制到
`public_inputs/` 或 Agent workspace。论文 artifact release 可按权限分别发布 public run evidence
和受保护 evaluator assets。

---

## 20. 论文报告结构

### 20.1 Dataset/readiness table

按 project、RQ、condition 报告：

- constructed count；
- final eligible count；
- policy-only vs executable RQ4 count；
- Gold ACT/CLARIFY；
- difficulty/event/substrate distribution；
- excluded/PENDING/BUILD_BLOCKED reason。

### 20.2 Main result table

每个 Agent × C1/C2/C3 报告：

- RQ1 Requirement F1 / Evidence F1（仅 C2）；
- RQ2 StateE2E / StateConditional；
- RQ3 Macro F1 / Unsupported Autonomy / Unnecessary Clarification；
- RQ4 task action / FullCodeSuccess / clarification-policy success；
- strict E2E success。

所有 primary estimate 带 95% CI 和 denominator。

### 20.3 Condition-effect table

- `C2 − C1` history benefit；
- `C3 − C2` selection/noise gap；
- paired CI；
- history length 与 distractor-density slice。

### 20.4 Execution gate table

分别报告 environment、build、target、negative、inherited、regression、temporal fixture、security
通过率，避免一个 FullCodeSuccess 数字掩盖失败位置。

### 20.5 Diagnostic/error table

- RQ3 confusion matrix；
- temporal state error taxonomy；
- four-stage conditional success；
- Pipeline vs Oracle-upstream gap；
- invalid/timeout/tool/security rates；
- token、latency、tool call 和 cost。

---

## 21. 项目 42204309 的 Pilot 计划

当前 construction artifacts 包含：

- 25 个 selected targets；
- RQ1 21、RQ2 25、RQ3 18、RQ4 16，共 80 个 provisional RQ records；
- primary unified protocol 每个 Agent/replicate 最多 25 × 3 = 75 个 condition runs；
- 如果四个 RQ 完全独立运行，则是 21 + 25×3 + 18×3 + 16×3 = 198 个 runs；
- 所有当前 RQ records 均为 LONG，`turns` 范围 113–784；
- 16 个 RQ4 archives 当前均是 reconstructed/simulated executable substrate。

这些数字只描述 construction coverage，不是正式 evaluation denominator。

### 21.1 当前 readiness 缺口

- final RQ-specific eligibility 未审核；
- inherited constraints 未完成 causal-necessity review；
- C3 CONTEXT messages 未定稿；
- RQ3 C1 decision 为空，C2/C3 仍是 candidate；
- blocking ambiguity、clarification target 和 safe subactions 未冻结；
- RQ4 acceptance criteria、validator IDs 为空；
- 所有当前 RQ4 `execution_ready=false`。

因此现阶段只能做 materializer/parser 的 dry run，不能发布模型正式得分。

### 21.2 推荐 pilot coverage

先选择少量但语义不同的 targets：

- T003：multi-Requirement MODIFY 与 temporal parameter update；
- T004：真实 lifecycle ambiguity，先用于 RQ3；只有 final RQ4 eligibility 通过后才做
  no-speculation RQ4；
- T006：REMOVE 与跨组件一致性；
- T010：runtime failure + blocking ambiguity + temporal defect fixture；
- 再补一个 inherited-constraint/shared-file target。

Pilot 的目标是验证 schema、alignment、decision rubric、sandbox 和 validators，不用于模型排名。

### 21.3 Pilot exit criteria

- public materialization 无泄漏；
- unified response schema 对至少两种 Agent framework 可用；
- Requirement matching 的低置信率可接受；
- RQ1–RQ3 scorer 与人工小样本一致；
- 每个 RQ4 validator 在 pre/reference post 上呈现预期 fail/pass；
- C1/C2/C3 workspace 除 history 外完全相同；
- 重复运行结果、成本和 failure status 可稳定记录；
- 完成 pilot 后冻结 v1，再扩展全部 targets 和 projects。

---

## 22. Threats to Validity

### 22.1 Construct validity

- Requirement matching 可能把语义相近但独立的 Requirements 错配；
- C3 的 CONTEXT/relevance judgement 存在人为主观性；
- hidden validators 可能只覆盖部分 behavior；
- 结构化 response 可能低估“代码正确但解释格式错误”的能力。

缓解：冻结 schema、双人 Gold review、低置信 alignment adjudication、behavior-level validators，
并同时报告 response 与 code outcomes。

### 22.2 Internal validity

- condition 之间的 prompt、budget 或 workspace 差异会污染 history effect；
- model/API 滚动版本、缓存和跨 run memory 会破坏配对；
- flaky validator、dependency network 和 host load 会被误认作 Agent failure。

缓解：fingerprint、隔离 workspace、固定 container、禁跨 run memory、preflight 与明确 status。

### 22.3 External validity

- 单一项目、单一领域或全部 LONG 不能代表所有软件项目；
- reconstructed/simulated code substrate 不等价于完整原始 production repository；
- Upwork client–freelancer history 不覆盖所有组织协作方式。

缓解：增加 project-disjoint domains，按 substrate 分层报告，并把单项目结果明确称为 pilot。

### 22.4 Statistical conclusion validity

- 同项目 targets 高度相关；
- 小 project 数会产生不稳定 CI；
- 多 RQ、多模型、多 slice 容易产生 multiple-comparison 假阳性。

缓解：project macro、clustered paired analysis、预注册 primary comparisons、Holm correction 与
effect-size-first reporting。

### 22.5 Benchmark contamination

- public history/task 可能出现在预训练数据中；
- release 后模型可能针对 benchmark 优化；
- 公开 manifest/tests 可能意外暴露答案。

缓解：记录模型与 release 日期、保留 held-out projects/validators、运行 leakage scan，并在论文
中明确 contamination 不能被完全排除。

---

## 23. 推荐实施顺序

1. 定义 final eligibility/review schema；
2. 完成 inherited constraints、C3 CONTEXT 和 RQ3 Gold 人工审核；
3. 定义 RQ2 field scoring mask 与 typed normalization；
4. 冻结 unified `rq-agent-response-v1` JSON Schema；
5. 实现 condition-specific `public_materializer` 与 leakage tests；
6. 实现 response parser 和 Requirement maximum-weight aligner；
7. 实现 RQ1、RQ2、RQ3 deterministic scorers；
8. 为 3–5 个 pilot targets 编写 acceptance criteria 和 hidden validators；
9. 实现 RQ4 sandbox/executor 与 run artifact capture；
10. 实现 unified end-to-end runner；
11. 在 development pilot 上校准 matching threshold，但不看 test Gold；
12. 冻结 benchmark/evaluation/config/prompt/validator v1 fingerprints；
13. 扩展到更多 project-disjoint targets；
14. 运行正式 Agent × condition × replicate matrix；
15. 聚合、paired statistics、error propagation 和人工 agreement；
16. 生成论文主表、附表和可复现实验 manifest。

---

## 24. Evaluation Definition of Done

正式 Evaluation Design 只有在以下条件全部落实后才能进入 paper-grade run：

- [ ] 四个 RQ 的 final eligibility 与 reason codes 已冻结；
- [ ] train/dev/test 按 project 划分；
- [ ] RQ1 relevance、inherited constraints 和 evidence labels 已审核；
- [ ] C3 保留完整 trajectory/必要 CONTEXT 且无结构化 Gold 泄漏；
- [ ] RQ2 state fields 与 scoring masks 已冻结；
- [ ] RQ3 `project_decision_gold`、`decision_by_condition`、blocking ambiguity、clarification
      target 和 safe-subaction policy 已冻结；
- [ ] RQ4 action Gold、acceptance criteria、validator groups 和 execution eligibility 已冻结；
- [ ] pre repo 与 reference post 的 validator calibration PASS；
- [ ] public materializer 不复制 researcher-side instance；
- [ ] C1/C2/C3 除历史外 prompt/repo/tool/budget 完全一致；
- [ ] unified response JSON Schema、invalid policy 和 action mapping 已冻结；
- [ ] Requirement alignment config、confidence threshold 和 adjudication protocol 已冻结；
- [ ] Agent runner、RQ4 sandbox 和 hidden validator isolation 通过安全审计；
- [ ] run status、retry、timeout、missingness 和 denominator policy 已冻结；
- [ ] project-level aggregation、bootstrap seed、replicates 和 primary comparisons 已预注册；
- [ ] pilot 已通过且 schema v1 不再因单模型结果临时修改；
- [ ] benchmark release、prompt、model、tool、container、validator 和 run fingerprints 可追溯；
- [ ] 论文报告 denominator、CI、condition effects、failure gates、成本和人工 agreement。

完成后，ReqMemBench 才能在同一事实基础上同时报告：

\[
\mathrm{Selection\ Quality},
\quad
\mathrm{State\ Reconstruction},
\quad
\mathrm{Decision\ Safety},
\quad
\mathrm{Executable\ Success},
\]

并用 C1/C2/C3 与 Oracle-upstream diagnostics 回答历史究竟带来帮助、干扰，还是暴露了
Agent 在 temporal reasoning 与 coding execution 上的独立瓶颈。

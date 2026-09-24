# ReqMemBench RQ1–RQ4 Evaluation Design

## 1. 文档目标

本文只定义两件事：

1. RQ1–RQ4 分别如何评估；
2. 如何把 RQ instances 提供给 Coding Agent 并保存测试结果。

RQ instance 的构造方法、字段来源和目录结构由
`Constuction_guideline/DESIGN_RQ_instance_construction.md` 定义。当前 RQ JSON 是
researcher-side construction record，不能原样提供给 Agent。

一个 target task 最多产生四个 RQ evaluation views，但只评价该 target 实际满足
eligibility 的 RQ。

四个 RQ 的主要结果为：

| RQ | 评价问题 | 主要结果 |
|---|---|---|
| RQ1 | Agent 能否找出真正相关的历史 Requirement 和证据？ | Requirement F1、Evidence F1 |
| RQ2 | 对已经对齐的 relevant historical Requirements，Agent 能否恢复 target 前的真实有效状态？ | Attribute Reconstruction、分维度分数、Matched Full-State Exact、Coverage |
| RQ3 | Agent 能否根据 Pre-task State 和当前 task 构造确定的 Post-task State；若不能，能否指出具体阻塞点并提出有效澄清？ | Decision / Balanced Accuracy、Post-State、Clarification |
| RQ4 | Agent 修改后的代码能否通过最终自动验证？ | Delivery Pass |

四个 RQ 组成一条有明确职责边界的能力链：

\[
History
\xrightarrow{RQ1} Relevant\ Evidence
\xrightarrow{RQ2} G(t^-)
\xrightarrow{RQ3} G(t^+)\ \text{or Clarify}
\xrightarrow{RQ4} Code.
\]

其中：

- RQ1 管“哪些历史 Requirement 和 evidence 与当前 task 相关”；
- RQ2 管“这些 Requirement 在当前 task 到来之前是什么状态”；
- RQ3 管“当前 task 之后应当变成什么状态，或者为什么还不能唯一确定”；
- RQ4 管“把已经确定的 Requirement update 落实成代码”。

最重要的边界是：**RQ2 只恢复 \(G(t^-)\)，RQ3 才使用当前 task 更新状态。**

---

## 2. 如何利用 Agent 进行测试

### 2.1 C1/C2

同一个 target 使用两种历史条件，两者都提供 target 前的项目历史：

| Condition | Agent 可见历史 |
|---|---|
| C1 — Full History | 提供 target 前的完整脱敏历史 |
| C2 — Oracle Relevant History | 只提供审核后的相关原始历史消息 |

No-History 不再属于正式条件。ReqMemBench 的研究对象是 Agent 接手进行中的项目；移除全部历史会
把任务改成孤立指令理解，无法评价项目记忆、状态恢复或基于历史继续交付的能力。若未来需要观察
无历史行为，只能作为单独命名的探索性消融，不能进入 RQ1–RQ4 主结果。

RQ1 只在 C1 下评价，因为 C2 已经提前筛选了相关历史。RQ2、RQ3 在 C1/C2 下评价，分别观察
完整项目历史与 oracle relevant history 下的 State Reconstruction 和 Update-or-Clarify。
RQ4 只在对应 condition 的最终 RQ3 Gold decision 为 `ACT` 时评价代码交付。

同一个 target 的两个 conditions 之间，RQ1–RQ3 reasoning phase 只能改变历史内容。以下内容
必须一致：

- target task；
- RQ1–RQ3 Agent prompt 和输出格式；
- RQ1–RQ3 模型、非仓库工具权限和运行预算。

正式 RQ1–RQ3 一律不得向 Agent 暴露 pre-task repository、repository 文件树、archive path、
代码搜索工具或 build/test 输出。pre-task repository 只在 RQ1–RQ3 response 已冻结后进入独立的
RQ4 execution phase。两个 conditions 的 RQ4 phase 使用同一份 pre-task repository、相同执行
prompt、工具权限、预算和 build/test 命令。

### 2.2 Agent 可见输入

Runner 为每个 `target × condition` 先创建一个不含仓库的 RQ1–RQ3 reasoning workspace：

从 researcher-side RQ instance 到该目录的完整转换规则见
`Constuction_guideline/DESIGN_RQ_agent_input_materialization.md`。

```text
run_workspace/
├── instructions.md
├── task.json
├── history.jsonl
└── response.schema.json
```

其中：

- `task.json` 只保存当前 client task；
- `history.jsonl` 根据 C1/C2 写入允许 Agent 看到的消息；
- reasoning workspace 不存在 `repository/`，也不提供任何能读取 Code Environment 的工具；
- 每个 condition 和 replicate 都必须使用新的 workspace；
- RQ1–RQ3 结构化 response 写出后立即复制到 evaluator-side immutable storage，并记录 hash。

不得提供给 Agent：

- `construction_gold`；
- `source_artifacts` 以及任何由 `construction_gold` 派生的答案字段；
- 内部 Requirement/Event/State ID；
- RQ4 validator、正确答案或 reference patch；
- target 之后的消息、代码或测试；
- 其他 Agent 的运行结果。

当前 `pre_repo.zip` 可能由 State Graph 重建，并直接编码 RQ2 Pre-state 或帮助推导 RQ3
Post-state，因此不能作为正式 RQ1–RQ3 输入。对 RQ1–RQ3，Gold leakage 的控制方式是硬隔离，
不是依赖文本清洗。若研究代码可见条件，可另设明确标记的 `+Repo` 消融；该结果不得与正式
history-only 主结果混报。

### 2.3 两阶段 Agent run

一个逻辑 run 分成两个有不可逆边界的阶段：

```text
Phase A：只读取 task 和 history；repository 不存在
             ↓
选择相关历史 Requirement 和 evidence       RQ1
             ↓
恢复当前 Requirement State                  RQ2
             ↓
决定 ACT 或 CLARIFY                         RQ3
             ↓
写出并冻结 RQ1–RQ3 response（hash + timestamp）
             ↓
若 Agent decision=ACT 且该 condition 的 RQ4 eligible
             ↓
Phase B：开放全新 pre-task repository，只允许修改代码  RQ4
```

Phase B 可以延续同一 Agent session，也可以启动固定配置的新 execution session；无论采用哪种
方式，都不得覆盖、补写或重新解释已经冻结的 RQ1–RQ3 response。RQ4 scorer 只读取 Phase B 的
最终 repository，不读取 Agent 在开放仓库后产生的任何修订版 State/decision。

Agent 在 Phase A 为 RQ1–RQ3 返回结构化 JSON：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "evidence_message_ids": [8, 21, 156],
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
      "requirement_summary": "Small Block prize rule",
      "change_type": "MODIFIED",
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

如果 Agent 选择 `CLARIFY`：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "evidence_message_ids": [8, 21, 156],
      "pre_task_state": {
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "CLARIFY",
  "post_task_states": null,
  "clarifications": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "dimension": "VALUE",
      "field": "prize_amount_usd",
      "missing_information": "The task gives two conflicting candidate amounts.",
      "question": "Should the new small-prize amount be $300 or $500?"
    }
  ]
}
```

Agent 不需要猜内部 `REQ_*` ID。RQ1 Evaluator 对同一 target 的全部 Prediction–Gold pairs
进行一次 LLM Atom relation classification，再使用冻结的自动规则完成一对一对齐；任何 relation
都不进入人工复核。

### 2.4 每次运行保存什么

每个 run 至少保存：

- Phase A Agent 原始输出、冻结的结构化 JSON、freeze timestamp 和 SHA-256；
- condition、model 和运行状态；
- Phase A 与 Phase B 分开的 token、耗时、工具调用和权限日志；
- Phase A workspace 不存在 repository 的证明；
- 如进入 Phase B，保存 changed files、patch 和 Agent 修改后的 repository；
- applicable RQ1–RQ3 scores，以及 eligible RQ4 的 `PASS`/`FAIL`；
- RQ4 自动验证脚本的 stdout、stderr 和 exit code。

### 2.5 推荐测试顺序

第一轮只运行一个 replicate：

1. 先选择一个 RQ1–RQ3 ready 且 RQ4 eligible 的 target；
2. 分别运行 C1、C2 的 Phase A，并确认 Agent 无法读取 repository；
3. 冻结两份 RQ1–RQ3 response，确认 hash 在 Phase B 后保持不变；
4. 只对满足执行条件的 run 开放 Phase B repository；
5. 确认 JSON response、patch、权限日志和验证日志可以保存；
6. 再扩展到全部 targets。

对项目 `42204309`，完成 RQ3 Gold 和 RQ4 validator 校准后，才能选取一个 eligible target 做
两阶段端到端 smoke test。当前 `pre_repo.zip` 只能在 Phase B 用于 RQ4，不能用于 Phase A。
全部 25 个 targets 按统一协议运行一个 replicate 需要 `25 × 2 = 50` 个 Phase A reasoning
runs，另加通过 Agent=`ACT` 与 RQ4 eligibility 双重门控的 Phase B execution runs。只有通过各
RQ eligibility 的 target-condition 进入相应分母。

---

## 3. RQ1 — Relevant Requirement Selection

### 3.1 评价目标与 Gold 单位

RQ1 只使用 C1 Full History，评价：

\[
Requirement\ Selection + Evidence\ Selection.
\]

Gold 的基本单位固定为 `Independent Requirement Atom`。为使整个流程无需人工复核，Benchmark
采用以下操作性定义：

```text
One Requirement Graph = One Independent Gold Requirement Atom
```

Requirement 内部 attributes 或 rule fragments 不单独构成 Atom。RQ1 Gold relevant set 确定为：

\[
affected\_requirement\_ids \cap PreTaskRequirements.
\]

因此，当前 task 首次 INTRODUCE 的 Requirement 不属于 RQ1，未被 target Event 直接影响的
preserved/inherited Requirements 也不进入 RQ1 Gold。这个确定性范围是取消 Human Review 后的
正式 Benchmark 边界。

### 3.2 Agent 输出

Agent 为每个预测 Requirement 输出本地引用、语义摘要和其选择的历史证据：

```json
{
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Periodic small prize reward rule",
      "evidence_message_ids": [21, 56, 103]
    }
  ]
}
```

`requirement_ref` 在一次 response 内唯一，不允许使用内部 `REQ_*` ID；所有 evidence IDs 必须
来自该 instance 的 C1 history。无需额外输出与 per-Requirement evidence 重复的
`selected_history_message_ids`。

RQ1 scorer 直接接受上述统一 response，而不是要求 Runner 先另存一个只含 RQ1 字段的 JSON。
验证采用“必需字段 + 声明字段白名单”：顶层必须有 `requirements`，并允许统一协议声明的
`decision`、`post_task_states`、`clarifications`；每个 Requirement 必须有
`requirement_ref`、`requirement_summary`、`evidence_message_ids`，并允许 RQ2 声明的
`pre_task_state`。未声明字段仍会被拒绝。验证通过后，scorer 内部只投影三个 RQ1 必需字段，
因此 RQ2/RQ3 字段不会参与 RQ1 计分。对应 contract 为 `rq1-agent-response-v3`。

### 3.3 确定性 Evidence Gold

每个 Gold Atom 保存：

- `required_evidence_groups`：由 Pre-task State 的 current-support messages 确定性生成；
- `neutral_context_message_ids`：同 `family_id` 的全部 target 前 trajectory 中，不属于当前 Atom
  current support 的消息；没有 family 时退化为该 Atom 自身 trajectory；
- `trajectory_message_ids`：保留该 Atom 在 target 前的完整演化轨迹。
- `family_trajectory_message_ids`：保留上述 family-wide neutral 边界，供审计使用。

每个 current-support Event 形成一个 evidence group。该 Event 的主 `source_message_id` 与其
`supporting_message_ids` 中所有严格早于 target 的消息共同进入该组的
`acceptable_message_ids`；若两个 Event group 因共享消息而重叠，则确定性合并，保证 groups
两两不相交。选择同一 group 中任意一个 ID 只形成一个 Evidence TP。target 当下或之后的
supporting message 永不进入 Gold，也不进入 C2 history。

### 3.4 一次 LLM Atom Relation Classification

对同一 target 构造全部：

\[
PredictedRequirements \times GoldRequirements
\]

并在一次 LLM API call 中分类。42204309 单个 target 最多有 13 个 Gold Atoms，因此第一版不使用
candidate threshold，避免 candidate pruning 自身制造 Requirement FN。当前 scorer 的显式安全上限为
每个 target 20 个 Gold Atoms、50 个 predicted Requirements；超过上限属于 response/evaluator
schema error，不进行静默截断。

LLM 只能为每个 pair 输出一个离散 relation：

```text
SAME_ATOM
MERGED_ATOMS
SUBPART_OF_ATOM
RELATED_DIFFERENT_ATOM
UNRELATED
UNCERTAIN
```

LLM 不输出相似度、TP/FP/FN 或最终分数。Judge response 必须恰好覆盖全部 pairs；缺失、重复、
foreign pair 或非法 relation 会使该 run 成为 `JUDGE_ERROR`，而不是 Agent 的 0 分。

### 3.5 自动冲突规则与一对一匹配

只有 `SAME_ATOM` 产生合法 semantic edge。`MERGED_ATOMS`、`SUBPART_OF_ATOM`、
`RELATED_DIFFERENT_ATOM`、`UNRELATED` 和 `UNCERTAIN` 全部不产生 edge，也不转人工。

Requirement summary lexical overlap 和 evidence overlap 只形成 matching weight，不是合法 edge 的
硬门槛。这样 Agent 的 Evidence 错误不会同时取消语义正确的 Requirement TP。

在全部合法 edges 上执行：

1. maximum-cardinality：先最大化匹配数量；
2. maximum-weight：匹配数量相同时最大化确定性 summary/evidence weight；
3. stable pair order：仍相同时按稳定 pair 顺序打破平局。

每个 Prediction 最多匹配一个 Gold，每个 Gold 最多匹配一个 Prediction。

严格粒度规则为：

```text
MERGED_ATOMS     -> No Match
SUBPART_OF_ATOM  -> No Match
UNCERTAIN        -> No Match
```

一个 Prediction 合并两个 Gold Atoms 时产生一个 FP 和两个 FN；一个 Gold Atom 被拆成三个
subparts 时产生三个 FP 和一个 FN。

### 3.6 Requirement Score

- 成功一对一匹配的 Prediction：TP；
- 未匹配 Prediction：FP；
- 未匹配 Gold Atom：FN。

计算 Requirement Precision、Recall 和 F1。若且仅当 Requirement FP=0 且 FN=0，
`Exact Requirement Set Accuracy=1`。

### 3.7 唯一的端到端 Evidence Score

RQ1 正式结果只保留一个完整 Evidence Precision/Recall/F1，不同时发布 Conditional 与
End-to-End 两套主指标。

Evidence 与 Requirement 粒度评分解耦。对同一 target 构造：

- Prediction claim：每个 `(prediction_ref, message_id)`；
- Gold unit：每个 `(gold_requirement_id, evidence_group_id)`；
- 合法 edge：claim 的 `message_id` 出现在该 group 的 `acceptable_message_ids` 中。

在该二分图上执行确定性的 maximum-cardinality 一对一匹配：每个 matched claim/group 计一个
Evidence TP；未匹配 Gold group 计一个 Evidence FN；未匹配 claim 只有在其 message ID 既不属于
本 target 任一 Gold group 的 acceptable 集合、也不属于任一 Gold Atom 的 neutral 集合时，才计
一个 Evidence FP。重复选择同组替代消息、把正确 Gold 证据放在错误粒度的预测 Requirement 下，
或选择 family-neutral context，均保留在 diagnostics 中但不计 FP。

因此一个 `MERGED_ATOMS` 或 `SUBPART_OF_ATOM` 错误仍只由 Requirement Score 惩罚，不会通过
Requirement FP/FN 再把同一粒度错误复制到 Evidence Score。Evidence Score 衡量的是 target-level
证据选择能力；Requirement 的原子划分和归属能力由 Requirement Score 衡量。若同一 message
确实支持多个 Gold groups，则必须存在足够多的独立 claims，才能一对一覆盖这些 groups。

`Conditional Evidence Recall` 只允许作为 `diagnostics` 中的错误分析值，不能进入正式 RQ1 指标、
论文主表或综合分数。

### 3.8 正式结果与聚合

RQ1 正式报告：

```text
Requirement Precision / Recall / F1
Evidence Precision / Recall / F1
Exact Requirement Set Accuracy
```

不额外定义 Requirement/Evidence 加权总分。项目和 Benchmark 主结果使用 target-level macro
average，避免 Gold Atom 较多的 target 支配整体结果。TP/FP/FN 总数可以作为审计统计，但不是
替代 macro 指标的第二套主结果。

### 3.9 可复现性与无 Human Review

RQ1 不设置逐实例人工复核或 adjudication。执行时必须冻结 Judge model/version、prompt、
reasoning/temperature 配置、request/response schema 和 scorer version。所有冲突走上述固定规则；
LLM 或 schema 基础设施失败记为 `JUDGE_ERROR`，待整次 run 重跑，不进入分数分母。

---

## 4. RQ2 — Pre-task State Reconstruction

### 4.1 核心定义与能力边界

RQ2 是纯粹的历史状态恢复问题：

\[
Relevant\ Historical\ Requirements + History_{<t}
\longrightarrow \widehat{G}(t^-).
\]

核心问题是：

> 对于已经正确识别并与 Gold 对齐的 relevant historical Requirements，Agent 能否恢复它们
> 在当前 task 到来之前的真实有效状态？

RQ2 明确不负责以下工作：

- 不负责 Requirement Selection；该能力由 RQ1 评价；
- 不因 RQ1 遗漏 Requirement 而在 RQ2 中再次记 0；
- 不评价当前 task 新引入、且在 \(t^-\) 尚不存在的 Requirement；
- 不使用当前 task 更新状态；
- 不评价 Post-task State \(G(t^+)\)；这属于 RQ3。

当前 task \(q_t\) 在 RQ2 中只作为 relevance anchor：它帮助确定“需要恢复哪些历史
Requirements”，但其中的新值、删除指令或新约束不得写入 \(G(t^-)\)。

### 4.2 Conditions

RQ2 的正式 conditions 为：

| Condition | 作用 | 是否进入 RQ2 正式结果 |
|---|---|---|
| C1 — Full History | 测试 Agent 能否从噪声、过期值和干扰信息中恢复当前有效状态 | 是 |
| C2 — Oracle Relevant History | 测试已经移除 selection/noise 难度后的纯 reconstruction 能力 | 是 |

C2 是最纯粹的 RQ2 setting；`C2 − C1` 的差异反映移除 full history 中的无关消息和 stale
information 后的增益。

### 4.3 Requirement 对齐与评分集合

Evaluator 使用与 RQ1 相同的通用 Requirement alignment 协议，把 Agent 的
`requirement_ref + requirement_summary + evidence_message_ids` 映射到 Gold Requirement。
Judge 只返回离散 Atom relation，确定性代码再做稳定的一对一 `SAME_ATOM` 匹配，不允许
Judge 直接产生分数。设成功对齐的集合为：

\[
M_t = \{(r_{agent}, r_{gold}) \mid alignment\ accepted\}.
\]

RQ2 只在 \(M_t\) 上评分：

- RQ1 漏掉的 Gold Requirement 不在 RQ2 中重复记 0；
- RQ1 选出的无关 Requirement 不在 RQ2 中重复记 FP；
- RQ1 relation 不是 `SAME_ATOM`、或一对一匹配后未对齐的 Requirement 不进入 RQ2 评分；
- 如果一个 target 没有任何 matched Requirement，RQ2 记为 `N/A`，不能记成满分。

为防止只恢复少数容易 Requirement 而造成误读，必须另外报告：

\[
ReconstructionCoverage_t = \frac{|M_t|}{|R_t^{gold}|}.
\]

`Reconstruction Coverage` 只说明 RQ2 分数覆盖了多少 Gold Requirements，不参与 RQ2
State Score；Requirement 找全与否仍由 RQ1 负责。

### 4.4 Agent 输出

每个 matched historical Requirement 输出一个 `pre_task_state`：

```json
{
  "requirement_ref": "agent-local-1",
  "requirement_summary": "Small Block prize rule",
  "evidence_message_ids": [8, 21, 156],
  "pre_task_state": {
    "attributes": {
      "prize_amount_usd": 100,
      "winners_per_draw": 5
    },
    "scope": {
      "persistence": "PROJECT_PERSISTENT",
      "components": ["BACKEND", "SMART_CONTRACT"],
      "contexts": ["SMALL_BLOCK"]
    },
    "lifecycle_status": "ACTIVE",
    "ambiguity": null,
    "execution": null
  }
}
```

Agent 不需要输出内部 `REQ_*`、Event ID 或 State ID。`evidence_message_ids` 用于完成
Requirement alignment 和审计，但证据选择本身只在 RQ1 计分。

### 4.5 Gold 边界

RQ2 Gold 来自 RQ2 instance 的 `construction_gold.states`，其每个 State 必须是
`Pre-task snapshot` 在 `before_message_id == target_message_id` 边界上的展开结果。

Gold 包括：

- `attributes`；
- `scope`；
- `lifecycle_status`；
- `ambiguity`；
- `execution`。

`requirement_title`、`family_id`、`state_id` 和 `supporting_event_ids` 只存在于独立的
provenance/alignment metadata，不得混入可评分 State，也不得要求 Agent 生成内部 ID。
`new_requirement_ids` 在 \(t^-\) 没有 State，因此不进入 RQ2 分母。

同一 target 的 C1/C2 使用同一份真实 \(G(t^-)\) Gold。condition 改变的是可见历史，不是
项目事实。

### 4.6 Typed State Scoring

不能把所有 `attributes` 都转换成字符串后做 exact match。每个 Gold attribute field 必须在
冻结前指定类型和 comparator：

| Gold field 类型 | 默认比较方式 |
|---|---|
| boolean、enum、identifier | 规范化后的 exact match |
| integer、金额、计数 | 数值 exact；只有 Gold 明确允许时才使用 tolerance |
| unordered set | element Precision、Recall、F1 |
| ordered list / workflow | 顺序敏感比较；必要时使用 normalized edit score |
| object / record | 递归到叶子字段后 macro average |
| free-text requirement fact | 由冻结的 API Judge 返回 `EQUIVALENT/NOT_EQUIVALENT/UNCERTAIN`，确定性映射为 1/0/0 |
| null / unknown / absent | 三者分开；未知且未标注的 Gold leaf 使用 `SKIP`，明确为空才用 `NULL_EXACT` |

自然语言仅允许通过冻结的 API Judge 做语义等价判断。例如“每完成 100 次销售触发”与
“100 sales per draw”可以等价；但 `$300` 与 `$500`、`DEFERRED` 与 `REMOVED` 必须由
确定性 comparator 判错。Judge 不处理 enum、boolean、number、set 或 null，也不覆盖 exact
结果。Judge 返回 `UNCERTAIN` 时保守计 0；基础设施失败则整条 run 标记 `JUDGE_ERROR` 后重跑。

五个 State dimensions 的比较为：

| State dimension | 比较方式 |
|---|---|
| `attributes` | 按 field-specific typed comparator 计算，再对适用字段平均 |
| `scope` | `persistence` exact；`components`、`contexts` 默认 set F1 |
| `lifecycle_status` | `ACTIVE/DEFERRED/REMOVED/...` exact match |
| `ambiguity` | `null` 或 record array；按 `(dimension, description)` 等语义字段做最大权一对一集合匹配 |
| `execution` | status exact；observed behavior 使用审核后的 atomic facts |

所有闭合枚举（包括 lifecycle、persistence、execution status、ambiguity status/dimension）
统一使用 normalized exact，不调用 LLM。Gold 中无法可靠标注或对该 Requirement 不适用的
字段不进入分母。完整 State 使用 closed-world 语义：Agent 多输出的 stale/未知字段计 FP；
空 object dimension 记 `N/A`，不能凭空贡献满分。禁止为了提高一致性而把整个复杂 attribute
压成一个字符串。

### 4.7 RQ2 指标

对每个 matched Requirement，仍计算适用 dimensions 的平均，作为诊断性辅助指标：

\[
StateScore(r)=\operatorname{mean}_{d\in D_r} Score(r,d).
\]

再在 target 内对 matched Requirements 做 macro average：

\[
MatchedStateScore_t = \operatorname{mean}_{r\in M_t} StateScore(r).
\]

正式主结果按能力分列，不再把五维等权平均当作头号指标：

- `Attribute Reconstruction Score`：真正承载属性恢复能力的主指标；
- `Per-Dimension Scores`：`attributes/scope/lifecycle_status/ambiguity/execution` 分列报告；
- `Matched Full-State Exact`：所有 matched Requirements 的全部适用字段都正确时为 1；
- `Reconstruction Coverage`：matched Gold Requirements 的比例，单独报告；
- C1、C2 分条件结果；
- `C2 − C1`：移除无关历史与 stale information 后的增益。

`Matched State Score` 只保留为 auxiliary，不能单独承担主要结论。每次正式实验还必须报告
oracle-aligned 常量 baseline：`attributes={}`、`persistence=PROJECT_PERSISTENT`、
`lifecycle_status=ACTIVE`、`ambiguity=null`、`execution=null`。该 baseline 与各维分布共同揭示
类别不平衡，不能代替 Coverage 或 RQ1 selection 指标。

---

## 5. RQ3 — Requirement Update or Clarify

### 5.1 核心定义与能力边界

RQ3 评价 Agent 能否把 Pre-task State 和当前 task 合成为唯一、可执行的 Requirement update：

\[
G(t^-)+q_t
\longrightarrow
\begin{cases}
G(t^+) & \text{ACT}\\
Clarification & \text{CLARIFY}.
\end{cases}
\]

它不只是判断 Agent“敢不敢做”，而是回答：

> 当前 task 到来后，affected Requirements 应当怎样变化；如果现有证据不足以产生唯一的
> Post-task State，Agent 能否准确定位阻塞不确定性并提出可回答的问题？

RQ3 与相邻 RQ 的边界是：

- historical Requirement 是否相关由 RQ1 负责；
- \(G(t^-)\) 是否恢复正确由 RQ2 负责；
- RQ3 负责解释当前 task 对 State 的新增、修改、删除、恢复、延后或保持作用；
- RQ3 不评价代码是否正确，代码交付属于 RQ4。

### 5.2 Conditions 与 condition-specific Gold

RQ3 在 C1/C2 下运行。两种 condition 都包含完成当前任务所需的相关历史，因此同一 target 的
最终 decision 和 Post-task State 应一致：

```json
{
  "C1": "ACT",
  "C2": "ACT"
}
```

C1/C2 Gold 不一致时，必须先检查 C2 是否漏掉必要 contextual evidence，或 C1 中是否存在改变
语义解释的相关证据。不能把 history noise 本身标成不同 Gold；condition 差异来自 Agent 表现，
而不是评价目标改变。

### 5.3 Gold = ACT

只有当当前 condition 的可见证据能够为所有 material affected Requirements 确定唯一
Post-task State 时，Gold 才是 `ACT`。

Agent 必须：

1. 输出 `decision = ACT`；
2. 对每个 affected Requirement 输出完整 `post_task_state`；
3. 对 target 新引入的 Requirement 输出其第一个 State；
4. 保留未被当前 task 改变、但仍适用于该 Requirement 的字段；
5. 被当前 task 明确删除或替换的属性必须从完整 `state.attributes` 中省略，并列入
   `removed_attribute_keys`；
6. 不把历史中的 superseded value 重新带入 \(G(t^+)\)。

示例：

```text
G(t−): prize_amount_usd = 100
q_t:   Change the prize to 500.
G(t+): prize_amount_usd = 500
```

Agent 输出结构：

```json
{
  "decision": "ACT",
  "post_task_states": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "change_type": "MODIFIED",
      "removed_attribute_keys": [],
      "state": {
        "attributes": {"prize_amount_usd": 500},
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

Post-task State 使用与 RQ2 相同的 typed field comparators，但评分范围是 target 的
`affected Requirements`，并与 Gold \(G(t^+)\) 比较。

Evaluator 对所有 affected Requirements 使用同一个通用 alignment API。已有 historical
Requirements 可利用前序 summary/evidence；target 首次引入的 Requirement 使用
`requirement_summary`、target task 和 `introduced_by_target` metadata 对齐。两类 Requirement
均进入同一次一对一匹配，不能因新 Requirement 没有 RQ1 match 而排除。

### 5.4 Gold = CLARIFY

如果至少一个 material affected Requirement 存在阻塞不确定性，使 \(G(t^+)\) 无法唯一
确定，Gold 为 `CLARIFY`。常见阻塞维度包括：

- `VALUE`：金额、阈值、数量或枚举值冲突/缺失；
- `SCOPE`：影响页面、组件、用户群或场景不明确；
- `LIFECYCLE`：是删除、暂停还是稍后恢复不明确；
- `BEHAVIOR`：触发条件、流程、错误处理或边界行为不明确；
- `DEPENDENCY`：第三方服务、版本、凭据或外部前置条件阻塞实现；
- `EXECUTION`：用户报告的现象不足以定位应改变的 Requirement behavior。

存在任意 `OPEN ambiguity` 并不自动等于 CLARIFY。该 ambiguity 还必须：

1. 与当前 task 直接相关或作为必须遵守的 inherited constraint；
2. 会改变最终 State 或实现选择；
3. 不能由 condition 中已有证据唯一消解；
4. 不能在不做假设的情况下安全地延后处理。

Agent 不得自行选择一个候选值并伪造完整 \(G(t^+)\)。它应输出：

```json
{
  "decision": "CLARIFY",
  "post_task_states": null,
  "clarifications": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "dimension": "VALUE",
      "field": "prize_amount_usd",
      "missing_information": "Two incompatible amounts remain possible.",
      "question": "Should the new small-prize amount be $300 or $500?"
    }
  ]
}
```

一个 target 可以有多个 blocking issues，因此 `clarifications` 使用数组。第一版不对
`CLARIFY` branch 的 partial code action 或 `safe_subactions` 评分；只要项目级更新仍被阻塞，
该 condition 就不进入 RQ4。

### 5.5 RQ3 Gold 的人工冻结

自动构造器只能生成 decision 和 ambiguity candidates。正式 Gold 必须由至少两名不同审核者
独立检查并完成 adjudication 后冻结：

- 每个 condition 的最终 `ACT/CLARIFY`；
- ACT branch 的 affected Requirement Post-task States；
- CLARIFY branch 的 blocking Requirement、dimension、field 和缺失信息；
- 可接受 clarification questions 的语义范围；
- 当前 ambiguity 是否 material、是否能被已有 evidence 消解。

冻结工具必须拒绝缺少 C1/C2 任一 branch、缺少 reviewer 身份、未 adjudicate、ACT 缺少完整
Post-state，或 CLARIFY 缺少 `acceptable_question_facts` 的 review。C1/C2 的 final decision、
Post-state 或 blocking issues 必须一致；若不一致，先修复 Oracle history 或 Gold review。

如果 State Graph 在 CLARIFY 情况下保存了带 `OPEN ambiguity` 的 Post snapshot，该 snapshot
只表示“截至当前消息仍不确定”，不能被当作唯一可执行的 \(G(t^+)\)。

### 5.6 ACT branch 评分

对 Gold ACT：

- `Decision Correct`：Agent 是否选择 ACT；
- `Post-State Score`：复用 RQ2 typed State Scoring，对 affected Requirements 的
  \(\widehat{G}(t^+)\) 与 Gold \(G(t^+)\) 比较；
- `Post-State Exact`：全部 affected Requirements 的完整适用字段、删除声明和 Requirement 集合
  是否正确；
- `ACT End-to-End Success`：decision 正确且 `Post-State Exact = 1`。

如果 Gold 为 ACT 而 Agent 选择 CLARIFY，Decision 记错，`ACT End-to-End Success = 0`；由于
Agent 没有输出 Post-state，不能把缺失输出排除后只报告一个看似较高的 State Score。
Agent 遗漏任一 affected Requirement 时，该 Requirement 的 Post-state 得 0；额外 Requirement
同样按 closed-world false positive 惩罚。这里不能沿用 RQ2 的 matched-only 规则，因为“正确
更新哪些 Requirements”本身就是 RQ3 的能力范围。Gold 的 `changed_paths/removed_paths` 用于
审计 field-level delta；最终得分仍比较完整 Post-state，防止旧属性被错误保留。

### 5.7 CLARIFY branch 评分

将每个 Gold blocking issue 表示为：

```text
(Requirement, Dimension, Field, Missing Information)
```

Evaluator 先用通用 alignment API 对齐 Requirement，再评价：

- `Requirement Correct`：是否指向真正阻塞的 Requirement；
- `Dimension Correct`：是否识别正确的 uncertainty dimension；
- `Field Correct`：仅在 Gold field 非空时 exact；Gold field 为 `null` 时为 N/A；
- `Blocking Issue F1`：对完整 blocking tuples 计算 Precision、Recall、F1；
- `Question Validity`：问题是否真正询问缺失信息，且答案能够消除对应阻塞；
- `Clarification Success`：decision 正确、所有 material blocking issues 被覆盖、且没有无关
  clarification 时为 1。

一个有效问题必须满足：不预设未经证实的答案；不重复询问历史中已经明确的信息；具体到
client 能直接回答；其答案确实能够在候选 States 之间作出选择。自然语言措辞不同但询问同一
blocking fact 时，由冻结的 clarification API Judge 返回离散的 issue equivalence 与 question
validity；Judge 不直接给最终分数，`UNCERTAIN` 保守计错。

Gold ambiguity 影响整个 dimension、确实无法定位单一 field 时，`field` 可以为 `null`，此时
`Field Correct` 记为不适用；只要可以定位具体字段，就必须填写，不能用宽泛 dimension 代替。

### 5.8 RQ3 总体指标与错误类型

正式报告：

- `Decision Accuracy`、`Balanced Accuracy`；
- `ACT Recall`、`CLARIFY Recall`；
- ACT targets 的 `Post-State Score`、`Post-State Exact`、`ACT End-to-End Success`；
- CLARIFY targets 的 `Requirement/Dimension/Field Correct`、`Blocking Issue F1`、
  `Question Validity`、`Clarification Success`；
- C1/C2 分条件结果。

每个 condition 同时报告 all-ACT 与 all-CLARIFY 常量 decision baselines，以及 Gold class
counts。对 `CLARIFY Recall`、`Unsupported Autonomy Rate` 等小样本比例，报告分子/分母与
two-sided exact binomial 95% CI；当 CLARIFY 样本只来自单一项目时，不作跨项目泛化主张。
`dimension` 分布高度集中时只作诊断，不把 Dimension Accuracy 单独作为能力主张。
`Unsupported Autonomy Rate` 的分母是 Gold CLARIFY targets，`Unnecessary Clarification Rate`
的分母是 Gold ACT targets；不得用全部 targets 稀释这两类风险。

同时区分：

| Gold | Agent | 错误 |
|---|---|---|
| CLARIFY | ACT | Unsupported Autonomy：证据不足却自行确定 Post-state |
| ACT | CLARIFY | Unnecessary Clarification：已有足够证据却拒绝更新 |
| ACT | ACT，但 State 错 | Incorrect Update：行动方向正确但 \(G(t^+)\) 构造错误 |
| CLARIFY | CLARIFY，但问题错 | Mislocalized Clarification：知道要问，但没有找到真正阻塞点 |

### 5.9 42204309 中的边界示例

以 Aave lifecycle 对话为例：在 client 仅表示 revised prize parameters 使 Aave
“quite unnecessary”、但没有明确要求删除的时间点：

- RQ2 只应恢复 \(G(t^-)\)：Aave integration 在此前仍为 `ACTIVE`；
- RQ3 不应擅自生成 `REMOVED` 的 \(G(t^+)\)；它应选择 `CLARIFY`，定位
  `REQ_AAVE_PRIZE_POOL_YIELD / LIFECYCLE`，询问是否正式删除该集成；
- client 后续明确要求 remove 后，新的 target 才能形成确定的 `ACTIVE → REMOVED` transition。

相反，在“把奖金额从 100 改为 500”这类 target 中，旧值属于 RQ2 的 \(G(t^-)\)，新值属于
RQ3 的 \(G(t^+)\)。只要对象、单位和范围明确，RQ3 应为 ACT，不应因为发生了修改而要求
clarification。

---

## 6. RQ4 — Requirement-to-Code Execution

### 6.1 核心定义

RQ4 只回答：

> Agent 先仅依据当前 task 与 condition 对应历史冻结 RQ1–RQ3 判断；在其选择 `ACT` 后再开放
> 同一份 pre-task repository，其最终 repository 能否通过为当前 target 预先设计的自动交付验证？

RQ4 评价最终 repository，不评价 Agent 对行动的文字说明、`planned_actions`、结构化 action
label 或 patch 与 reference patch 的相似度。ACT/CLARIFY decision 由 RQ3 评价；RQ4 只运行
对应 condition 的最终 RQ3 Gold decision 为 `ACT` 的实例。

Gold decision 决定 RQ4 分母，Agent decision 决定是否实际开放 Phase B repository。若 Gold 为
`ACT` 但 Agent 的冻结 decision 不是 `ACT` 或 response 无法解析，Runner 不开放 repository，并将
该 RQ4-eligible 实例记录为 `NO_CODE_SUBMISSION` / `FAIL`；不能通过事后查看代码来修订 RQ3。

RQ4 的正式结果只有 `PASS` 和 `FAIL`。实例是否可以进入评分由独立的 eligibility gate 决定，
不把不可执行、环境故障或 validator 故障扩展为第三类 RQ4 分数。

### 6.2 评分资格

一个 `target × condition` 当且仅当同时满足以下条件时进入 RQ4：

1. 该 condition 的最终 RQ3 Gold decision 为 `ACT`；
2. RQ4-only `pre_repo.zip` 可以在固定环境中完成 build 和已有 regression tests；
3. 当前 Requirement 至少对应一个确定、可自动观察的行为或工件结果；
4. target-specific hidden tests 已由人工提前设计并通过双人独立复核；
5. validator 已完成 §6.6 的校准并冻结；
6. Agent-visible repository 不含 future state、validator、reference delivery 或 evaluator-only
   Requirement/State/Event metadata。

未通过 eligibility gate 的实例不启动正式 RQ4 run，也不产生 `PASS` 或 `FAIL`。它仍可用于
RQ1–RQ3，并在私有资格记录中保存 `rq4_eligible=false` 和一个排除原因。排除原因只用于统计
Executable Coverage，不属于 RQ4 评分状态。

建议使用以下有限枚举：

```text
RQ3_NOT_ACT
NO_RUNNABLE_ENVIRONMENT
NO_DETERMINISTIC_OBSERVABLE
CONFIG_ONLY_NO_INDEPENDENT_BEHAVIOR
SUBJECTIVE_VISUAL_OR_SEMANTIC
VALIDATOR_NOT_READY
REPOSITORY_GOLD_LEAKAGE
```

### 6.3 人工预先设计 hidden validator

Benchmark 作者根据当前 target 和 Gold Requirement，为每个 RQ4 target 编写一个专属的
hidden validator。Validator author 先把所有必要交付结果写成 acceptance criteria，再为每项
criterion 指定至少一个可执行断言。测试必须在任何正式 Agent run 之前完成、复核和冻结；不得
查看某个 Agent 的提交后再增删断言。

Validator 的行为 oracle 来自 RQ3 已冻结的 \(G(t^+)\)，而不是重新解释聊天或只根据
Agent 输出猜测预期实现。Target Test 必须验证外部行为或生成工件，不能把 Gold attributes
原样序列化后再做配置相等比较。同一 target 的所有模型和 C1/C2 conditions 使用同一
validator；condition 只改变 Agent 可见历史。

```text
validators/rq4/
└── <project_id>/
    └── <target_id>/
        ├── validate.mjs
        ├── target-tests/
        ├── fixtures/
        └── validator.json
```

`validator.json` 记录如何运行验证：

```json
{
  "validator_id": "43214420_T016_v1",
  "target_id": "43214420_T016",
  "command": ["node", "validate.mjs", "--repo", "<agent_repo>"],
  "acceptance_criteria_ids": ["AC001", "AC002"],
  "calibration_complete": true
}
```

Validator 不放入 Agent workspace，Agent 在提交代码前不能读取它。

### 6.4 Validator 检查三件事

每个 validator 只需要完成三类检查：

1. **Build**：项目能否安装、编译或启动；
2. **Target Test**：当前 Requirement 对应的功能是否正确；
3. **Regression**：项目已有的基础测试是否仍然通过。

Target Test 只检查当前 target 的必要交付结果。通常一个 target 使用一个 hidden test suite，
内部包含少量关键断言；测试数量由必要行为决定，不设固定下限或上限。适用的观察方式包括：

| 可观察结果 | Validator 示例 |
|---|---|
| 函数行为 | 调用函数并断言返回值 |
| 本地 API | 启动服务、发送请求并断言 response |
| CLI | 执行命令并检查 exit code 和输出 |
| 生成工件 | 解析 KiCad、DOCX 或 PDF，检查结构、内容、拓扑或确定性几何约束 |
| REMOVE | 确认旧接口、元素、章节或行为已经不存在 |
| Bug fix | 复现旧 bug，并确认修改后不再出现 |

一个 target 涉及多个必要 Requirement 时，Target Test 必须覆盖所有必要行为；任意必要行为
失败，整个 Target Test 失败。

纯配置相等不构成主 RQ4 的独立行为证据。例如，读取 feature module 后断言
`configuration == Gold attributes` 的 target 应以
`CONFIG_ONLY_NO_INDEPENDENT_BEHAVIOR` 排除。配置只有在被真实函数、API、CLI 或工件生成流程
消费时，才通过最终行为进入 Target Test。自由文本只在客户明确要求逐字文案时使用 exact
match；主观视觉或语义相似度不调用 LLM/API Judge，而是排除出 RQ4。

### 6.5 PASS 与 FAIL

RQ4 使用简单的二元评分：

\[
RQ4Pass
=
BuildPass
\land TargetTestPass
\land RegressionPass.
\]

也可以直接使用总验证脚本的退出码：

```text
exit code = 0      -> PASS
exit code != 0     -> FAIL
```

保存的结果示例：

```json
{
  "target_id": "42204309_T003",
  "condition": "C1",
  "build_pass": true,
  "target_test_pass": true,
  "regression_pass": true,
  "exit_code": 0,
  "result": "PASS"
}
```

Build、Target Test 或 Regression 任一失败均为 `FAIL`。Gold 为 `ACT` 但 Agent 未选择 `ACT`、
Phase A response 无法解析、Agent timeout，或 Agent 没有留下可测试的 repository，也记为
`FAIL`。Phase B final message 无法解析但 repository 可测试时，忽略文字输出并
继续验证。Agent 不修改代码但最终测试全部通过仍为 `PASS`；§6.6 的 pre-repo 校准应保证这种
情况只在当前 task 原本已经满足或 validator 无效时出现。

### 6.6 Validator 校准

每个 validator 在正式使用前必须完成以下校准：

1. **Pre-repo**：Build 和 Regression 必须通过，Target Test 必须失败；
2. **Reference delivery**：Build、Target Test 和 Regression 必须全部通过；
3. **Partial delivery**：当 target 包含多个必要行为时，至少构造一个只实现部分 acceptance
   criteria 的 delivery，并确认 Target Test 失败。单一原子行为不要求额外 partial delivery。

如果 pre-task code 已经通过 Target Test，说明测试没有检查到当前新增或修改的要求；如果
reference delivery 仍失败，或 partial delivery 意外通过，validator 不得进入正式实验。

校准通过后冻结 validator ID、validator 内容版本、acceptance criteria、reference delivery
版本和校准记录。正式实验开始后若修改 validator，必须提升版本，并重跑该 validator 产生的
全部结果。

### 6.7 运行与环境边界

只有 Phase A 的 RQ1–RQ3 response 已经冻结且 Agent decision 为 `ACT` 时，Runner 才从同一
RQ4-only `pre_repo.zip` 全新解压，在独立 execution workspace 中开放 repository。Agent 停止后
先冻结 repository，再由 workspace 外的 evaluator 顺序执行 Build、Target Test 和 Regression。
Agent 不能访问 validator、acceptance criteria、reference delivery 或验证失败细节，也不能改写
Phase A 的冻结 response。

环境有效性在 Agent 运行前检查：pre-repo Build、Regression 和 validator startup 必须成功。
若环境、validator 或 harness 自身失败，当前 attempt 作废，修复后从干净 pre-repo 重跑；该
attempt 不写入正式 RQ4 结果。最终评分数据中的 `result` 因而始终只有 `PASS` 或 `FAIL`。

### 6.8 指标与聚合

正式主指标为：

\[
RQ4SuccessRate = \frac{\#PASS}{\#PASS + \#FAIL}.
\]

同时报告：

\[
ExecutableCoverage =
\frac{\#\text{进入 PASS/FAIL 评分的 target-condition}}
{\#\text{RQ3 Gold 为 ACT 的 target-condition}}.
\]

结果先在 target 内聚合，再在 project 内聚合，正式总分使用 project macro-average。Build、
Target Test 和 Regression 的通过率可以作为失败分析，但不形成新的 RQ4 分数等级。

C1/C2 的主要比较使用共同支持集合：同一 target 在两个 conditions 中均为 RQ3 Gold
`ACT`、均通过 eligibility gate，并使用同一 validator。各 condition 的全量 eligible 结果和
coverage 另行报告，不能把不同分母的差异直接解释为历史条件效果。

---

## 7. 最小实现清单

要真正使用 Claude Code、Codex 或其他 Coding Agent 跑测试，至少需要实现：

1. `public_materializer`：按各 RQ 的 availability 生成 C1 Full History 与 C2 Oracle Relevant
   History 输入；RQ1 只启用 C1；
2. `agent_runner`：在独立 workspace 中调用 Agent，并保存最终 repository、patch 和日志；
3. `requirement_aligner`：`Code/evaluation/alignment.py` 为 RQ2/RQ3 提供通用 all-pairs relation
   contract 与确定性一对一匹配；RQ1 保持自己的 v3 对齐契约与证据评分；
4. `typed_state_scorer`：`Code/evaluation/state.py` 负责 exact/set/recursive/closed-world 评分，
   只把自由文本语义叶交给 API Judge；
5. `rq2_typed_state_scorer`：`Code/evaluation/rq2.py` 与 `Code/evaluate_rq2.py` 已实现两阶段离线
   request/response、主/辅助指标、coverage 与 oracle-aligned 常量 baseline；
6. `rq3_branch_scorer`：`Code/evaluation/rq3.py` 与 `Code/evaluate_rq3.py` 已实现 decision、ACT
   Post-state、CLARIFY blocker/question 评分及 all-ACT/all-CLARIFY baseline；
7. `rq3_gold_review`：`Code/stage2/rq3_review.py` 与 `Code/finalize_rq3_gold.py` 生成 review template，
   并仅在双人审核和 adjudication 完成后冻结 condition-specific Gold；
8. `rq4_eligibility_builder`：在 RQ3 Gold 冻结后，按 condition 判定 RQ4 eligibility，并记录
   唯一的排除原因；
9. `rq4_validator_registry`：保存人工设计的 acceptance criteria、hidden validator、版本、哈希、
   适用 target 和 conditions；
10. `rq4_calibration_runner`：验证 pre-repo、reference delivery，以及适用时的 partial delivery，
    产出可审计的校准记录；
11. `rq4_validator_runner`：对 eligible run 的最终 repository 依次运行 Build、Target Test 和
    Regression，并只写出 `PASS` 或 `FAIL`；
12. `rq4_aggregator`：计算 Success Rate、Executable Coverage、project macro-average 和
    condition common-support 对比。

当前 RQ1 instances 已包含确定性 Atom/Evidence Gold；RQ2 使用 v3 contract，但仍保持
`PROVISIONAL_REQUIRES_FIELD_REVIEW`，因此只能生成诊断分数；RQ3 使用 v3 contract，但 25 个
targets 的 condition-specific Gold 仍须人工冻结；RQ4 的 `acceptance_criteria`、`validator_ids`
仍为空且 `execution_ready=false`。对应 review/validator 完成前不能发布正式分数。任何遗留
RQ2/RQ3 v1/v2 instance 必须先重新生成 public inputs。

现有 RQ4 records 仅是候选实例：其 acceptance criteria、validator、校准记录和 repository
leakage 检查尚未完成，因此均不具备正式 eligibility，也不能生成 `PASS`/`FAIL`。只有完成
§6.2 和 §6.6 的全部 gate 后，才可以将对应 target-condition 纳入 RQ4 分母。

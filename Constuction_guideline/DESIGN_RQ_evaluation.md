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
| RQ2 | 对已经对齐的 relevant historical Requirements，Agent 能否恢复 target 前的真实有效状态？ | Matched State Score、Matched Full-State Exact |
| RQ3 | Agent 能否根据 Pre-task State 和当前 task 构造确定的 Post-task State；若不能，能否指出具体阻塞点并提出有效澄清？ | Decision Accuracy、Post-State Score、Clarification Score |
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

### 2.1 C1/C2/C3

同一个 target 使用三种历史条件：

| Condition | Agent 可见历史 |
|---|---|
| C1 — No History | 不提供 target 前的对话历史 |
| C2 — Full History | 提供 target 前的完整脱敏历史 |
| C3 — Oracle Relevant History | 只提供审核后的相关原始历史消息 |

RQ1 只在 C2 下评价，因为 C1 没有历史可供选择，C3 已经提前筛选了相关历史。

RQ2 的正式评价只使用 C2 和 C3。C1 没有历史，无法构成有意义的历史状态恢复任务，因此不进入
RQ2 主结果；如果为调试保留 C1 输出，也必须标记为 `NOT_SCORED_DIAGNOSTIC`。

RQ3 在 C1/C2/C3 下评价。C1 用于观察缺少历史时 Agent 是否会在无法确定更新时主动澄清；
C2/C3 用于评价 Agent 在不同历史噪声条件下是否能形成正确的 Post-task State 或
clarification。RQ4 只在对应 condition 的最终 RQ3 Gold decision 为 `ACT` 时评价代码交付。

同一个 target 的三个 conditions 之间只能改变历史内容。以下内容必须一致：

- target task；
- pre-task code repository；
- Agent prompt 和输出格式；
- 模型、工具权限和运行预算；
- build/test 命令。

### 2.2 Agent 可见输入

Runner 为每个 `target × condition` 创建一个全新的隔离目录：

从 researcher-side RQ instance 到该目录的完整转换规则见
`Constuction_guideline/DESIGN_RQ_agent_input_materialization.md`。

```text
run_workspace/
├── instructions.md
├── task.json
├── history.jsonl
└── repository/
```

其中：

- `task.json` 只保存当前 client task；
- `history.jsonl` 根据 C1/C2/C3 写入允许 Agent 看到的消息；
- `repository/` 从对应 `pre_repo.zip` 全新解压；
- Agent 可以读取和修改 `repository/`；
- 每个 condition 和 replicate 都必须使用新的 workspace。

不得提供给 Agent：

- `construction_gold`；
- `source_artifacts` 以及任何由 `construction_gold` 派生的答案字段；
- 内部 Requirement/Event/State ID；
- RQ4 validator、正确答案或 reference patch；
- target 之后的消息、代码或测试；
- 其他 Agent 的运行结果。

### 2.3 一次 Agent run

推荐一次 Agent run 完成同一条能力链：

```text
读取 task、history 和 pre-task repository
             ↓
选择相关历史 Requirement 和 evidence       RQ1
             ↓
恢复当前 Requirement State                  RQ2
             ↓
决定 ACT 或 CLARIFY                         RQ3
             ↓
如果 ACT，修改 repository                    RQ4
```

Agent 返回结构化 JSON；代码修改直接保存在 workspace：

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

- Agent 原始输出和结构化 JSON；
- condition、model 和运行状态；
- token、耗时和工具调用；
- changed files 和 patch；
- Agent 修改后的 repository；
- RQ1–RQ4 score；
- RQ4 自动验证脚本的 stdout、stderr 和 exit code。

### 2.5 推荐测试顺序

第一轮只运行一个 replicate：

1. 先选择一个同时覆盖 RQ1–RQ4 的 target；
2. 分别运行 C1、C2、C3，共 3 次 Agent run；
3. 确认 public input 没有 Gold 泄漏；
4. 确认 JSON response、patch 和验证日志可以保存；
5. 再扩展到全部 targets。

对项目 `42204309`，可以先使用 `42204309_T001` 做同时覆盖 RQ1–RQ4 的 smoke test。全部 25 个 targets
按统一协议运行一次需要最多 `25 × 3 = 75` 个 Agent runs。

---

## 3. RQ1 — Relevant Requirement Selection

### 3.1 评价目标与 Gold 单位

RQ1 只使用 C2 Full History，评价：

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
来自该 instance 的 C2 history。无需额外输出与 per-Requirement evidence 重复的
`selected_history_message_ids`。

### 3.3 确定性 Evidence Gold

每个 Gold Atom 保存：

- `required_evidence_groups`：由 Pre-task State 的 current-support messages 确定性生成；
- `neutral_context_message_ids`：完整 trajectory 中不再承担 current support 的旧消息；
- `trajectory_message_ids`：保留该 Atom 在 target 前的完整演化轨迹。

第一版中每个不同的 current-support message 形成一个 singleton evidence group。后续如果存在
多个完全等价的消息来源，可以在同一 group 的 `acceptable_message_ids` 中列出多个 ID，但选择
其中任意一个只形成一个 Evidence TP。

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

对成功匹配的 Prediction–Gold pair：

- 选择某 required group 中至少一个 acceptable message：Evidence TP +1；
- 未覆盖 required group：Evidence FN +1；
- 同组选择多个 acceptable messages：仍只计一个 TP，多出的 acceptable messages 不计 FP；
- 选择 neutral context：既不增加 TP，也不增加 FP；
- 选择该 Atom 的其他历史消息：Evidence FP +1。

对未匹配 Gold Atom，其全部 required evidence groups 自然成为 FN。对未匹配 Prediction，其提交的
每个不同 evidence message ID 都成为 FP。Evidence 的归属单位是
`(Requirement, EvidenceGroup)`；同一消息确实支持不同 Requirements 时，可以分别合法计入。

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
| C1 — No History | 没有历史，不能进行真实的 historical state reconstruction | 否 |
| C2 — Full History | 测试 Agent 能否从噪声、过期值和干扰信息中恢复当前有效状态 | 是 |
| C3 — Oracle Relevant History | 测试已经移除 selection/noise 难度后的纯 reconstruction 能力 | 是 |

C3 是最纯粹的 RQ2 setting；C2−C3 的差异反映 full history 中的噪声与 stale information
对恢复能力的影响。C1 如被 runner 保留，只能用于调试，不得混入论文中的 RQ2 平均分。

### 4.3 Requirement 对齐与评分集合

Evaluator 先使用 RQ1 的对齐结果，把 Agent 的 `requirement_ref` 映射到 Gold
`requirement_id`。设成功对齐的集合为：

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

`requirement_title`、`family_id`、`state_id` 和 `supporting_event_ids` 用于 provenance、对齐和
审计，不作为 Agent 必须复现的状态字段。`new_requirement_ids` 在 \(t^-\) 没有 State，因此
不进入 RQ2 分母。

同一 target 的 C2/C3 使用同一份真实 \(G(t^-)\) Gold。condition 改变的是可见历史，不是
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
| free-text requirement fact | 拆成审核后的 atomic facts，再计算 fact-level F1 |
| null / unknown / absent | 三者分开；不得把“未提及”自动解释为 `null` 或 `false` |

自然语言仅允许做格式归一化和语义等价匹配，不能因为措辞不同直接判错。例如“每完成 100
次销售触发”与“100 sales per draw”可以等价；但 `$300` 与 `$500`、`DEFERRED` 与
`REMOVED` 不得视为近似正确。无法由确定性规则判断的语义等价项进入盲化人工复核。

五个 State dimensions 的比较为：

| State dimension | 比较方式 |
|---|---|
| `attributes` | 按 field-specific typed comparator 计算，再对适用字段平均 |
| `scope` | `persistence` exact；`components`、`contexts` 默认 set F1 |
| `lifecycle_status` | `ACTIVE/DEFERRED/REMOVED/...` exact match |
| `ambiguity` | null/open 状态、dimension、涉及字段和候选值分别比较 |
| `execution` | status exact；observed behavior 使用审核后的 atomic facts |

Gold 中无法可靠标注或对该 Requirement 不适用的字段不进入分母。禁止为了提高一致性而把
整个复杂 attribute 压成一个字符串。

### 4.7 RQ2 指标

对每个 matched Requirement，先计算适用 dimensions 的平均：

\[
StateScore(r)=\operatorname{mean}_{d\in D_r} Score(r,d).
\]

再在 target 内对 matched Requirements 做 macro average：

\[
MatchedStateScore_t = \operatorname{mean}_{r\in M_t} StateScore(r).
\]

正式报告：

- `Matched State Score`：允许 State field 部分正确；
- `Matched Full-State Exact`：所有 matched Requirements 的全部适用字段都正确时为 1；
- `Reconstruction Coverage`：matched Gold Requirements 的比例，单独报告；
- C2、C3 分条件结果；
- `C3 − C2`：移除无关历史与 stale information 后的增益。

RQ2 主分数中不再报告 `C2 − C1`，因为 C1 不构成正式 reconstruction condition。

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

RQ3 在 C1/C2/C3 下运行，因为“是否能够安全更新”取决于该 condition 中实际可见的证据。
例如同一 target 可能是：

```json
{
  "C1": "CLARIFY",
  "C2": "ACT",
  "C3": "ACT"
}
```

C1 缺少历史时，如果当前 task 依赖旧值、代词或既有范围，Gold 可以是 `CLARIFY`。C2/C3
包含相同有效 evidence 时，其最终 decision 和 Post-task State 应一致；如果两者不同，必须
先检查 C3 是否漏掉了必要 contextual evidence，而不能直接接受差异。

### 5.3 Gold = ACT

只有当当前 condition 的可见证据能够为所有 material affected Requirements 确定唯一
Post-task State 时，Gold 才是 `ACT`。

Agent 必须：

1. 输出 `decision = ACT`；
2. 对每个 affected Requirement 输出完整 `post_task_state`；
3. 对 target 新引入的 Requirement 输出其第一个 State；
4. 保留未被当前 task 改变、但仍适用于该 Requirement 的字段；
5. 不把历史中的 superseded value 重新带入 \(G(t^+)\)。

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

已有 historical Requirements 继续使用前序 `requirement_ref` 对齐；target 首次引入的新
Requirement 不属于 RQ1/RQ2 的历史集合，Evaluator 应使用 `requirement_summary`、target
evidence 和 Post-state fields 将其直接对齐到 affected Gold Requirement，不能因它没有
RQ1 match 而排除。

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

自动构造器只能生成 decision 和 ambiguity candidates。正式 Gold 必须由人工审核并冻结：

- 每个 condition 的最终 `ACT/CLARIFY`；
- ACT branch 的 affected Requirement Post-task States；
- CLARIFY branch 的 blocking Requirement、dimension、field 和缺失信息；
- 可接受 clarification questions 的语义范围；
- 当前 ambiguity 是否 material、是否能被已有 evidence 消解。

如果 State Graph 在 CLARIFY 情况下保存了带 `OPEN ambiguity` 的 Post snapshot，该 snapshot
只表示“截至当前消息仍不确定”，不能被当作唯一可执行的 \(G(t^+)\)。

### 5.6 ACT branch 评分

对 Gold ACT：

- `Decision Correct`：Agent 是否选择 ACT；
- `Post-State Score`：复用 RQ2 typed State Scoring，对 affected Requirements 的
  \(\widehat{G}(t^+)\) 与 Gold \(G(t^+)\) 比较；
- `Post-State Exact`：全部 affected Requirements 的完整适用字段是否正确；
- `ACT End-to-End Success`：decision 正确且 `Post-State Exact = 1`。

如果 Gold 为 ACT 而 Agent 选择 CLARIFY，Decision 记错，`ACT End-to-End Success = 0`；由于
Agent 没有输出 Post-state，不能把缺失输出排除后只报告一个看似较高的 State Score。
Agent 遗漏任一 affected Requirement 时，该 Requirement 的 Post-state 得 0；这里不能沿用
RQ2 的 matched-only 规则，因为“正确更新哪些 Requirements”本身就是 RQ3 的能力范围。

### 5.7 CLARIFY branch 评分

将每个 Gold blocking issue 表示为：

```text
(Requirement, Dimension, Field, Missing Information)
```

Evaluator 先对齐 Requirement，再评价：

- `Requirement Correct`：是否指向真正阻塞的 Requirement；
- `Dimension Correct`：是否识别正确的 uncertainty dimension；
- `Field Correct`：是否进一步定位到具体 field；
- `Blocking Issue F1`：对完整 blocking tuples 计算 Precision、Recall、F1；
- `Question Validity`：问题是否真正询问缺失信息，且答案能够消除对应阻塞；
- `Clarification Success`：decision 正确、所有 material blocking issues 被覆盖、且没有无关
  clarification 时为 1。

一个有效问题必须满足：不预设未经证实的答案；不重复询问历史中已经明确的信息；具体到
client 能直接回答；其答案确实能够在候选 States 之间作出选择。自然语言措辞不同但询问同一
blocking fact 时视为等价；无法确定时进入盲化人工复核。

Gold ambiguity 影响整个 dimension、确实无法定位单一 field 时，`field` 可以为 `null`，此时
`Field Correct` 记为不适用；只要可以定位具体字段，就必须填写，不能用宽泛 dimension 代替。

### 5.8 RQ3 总体指标与错误类型

正式报告：

- `Decision Accuracy`；
- `ACT Recall`、`CLARIFY Recall`；
- ACT targets 的 `Post-State Score`、`Post-State Exact`、`ACT End-to-End Success`；
- CLARIFY targets 的 `Requirement/Dimension/Field Correct`、`Blocking Issue F1`、
  `Question Validity`、`Clarification Success`；
- C1/C2/C3 分条件结果。

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

RQ4 不再使用复杂的 action/gate 综合评分。第一版只回答：

> Agent 修改后的代码能否通过我们为当前 target 编写的自动交付验证？

RQ4 只评价对应 condition 的最终 RQ3 Gold decision 为 `ACT`、代码环境可运行、能够编写
确定性测试的实例。RQ3 Gold 为 `CLARIFY` 的 condition 只在 RQ3 中评价，不进入 RQ4
分母。

### 6.2 我们编写 hidden validator

Benchmark 作者根据当前 target 和 Gold Requirement，为每个 RQ4 target 编写一个专属的
hidden validator。例如：

Validator 的行为 oracle 来自 RQ3 已冻结的 \(G(t^+)\)，而不是重新解释聊天或只根据
`planned_actions` 猜测预期实现。

```text
validators/
└── <project_id>/
    └── <target_id>/
        ├── validate.py
        └── validator.json
```

`validator.json` 记录如何运行验证：

```json
{
  "validator_id": "42204309_T003_v1",
  "target_id": "42204309_T003",
  "command": ["python", "validate.py", "--repo", "<agent_repo>"],
  "execution_ready": true
}
```

Validator 不放入 Agent workspace，Agent 在提交代码前不能读取它。

### 6.3 Validator 检查三件事

每个 validator 只需要完成三类检查：

1. **Build**：项目能否安装、编译或启动；
2. **Target Test**：当前 Requirement 对应的功能是否正确；
3. **Regression**：项目已有的基础测试是否仍然通过。

Target Test 根据任务类型编写：

| Requirement 类型 | Validator 示例 |
|---|---|
| 函数行为 | 调用函数并断言返回值 |
| API | 启动服务、发送请求并断言 response |
| 配置 | 读取配置并断言 key/value |
| 数据库 | 执行 migration/query 并检查 schema 或结果 |
| CLI | 执行命令并检查 exit code 和输出 |
| 前端 | 使用 Playwright/Selenium 操作并断言页面行为 |
| REMOVE | 确认旧接口、按钮或行为已经不存在 |
| Bug fix | 复现旧 bug，确认 Agent 修改后不再出现 |

一个 target 涉及多个必要 Requirement 时，Target Test 必须覆盖所有必要行为；任意必要行为
失败，整个 Target Test 失败。

### 6.4 RQ4 Pass

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
exit code = 0      → RQ4 PASS
exit code != 0     → RQ4 FAIL
```

保存的结果示例：

```json
{
  "target_id": "42204309_T003",
  "condition": "C2",
  "build_pass": true,
  "target_test_pass": true,
  "regression_pass": true,
  "exit_code": 0,
  "rq4_pass": true
}
```

不根据 Agent patch 与 reference patch 的文本相似度评分。只要自动行为测试全部通过，就认为
delivery 成功。

### 6.5 Validator 校准

每个 validator 在正式使用前必须完成两次校准：

1. 在 target 的 `pre_repo.zip` 上运行：Target Test 应失败；
2. 在确认正确的 delivery 上运行：Build、Target Test 和 Regression 应全部通过。

如果 pre-task code 已经通过 Target Test，说明测试没有检查到当前新增或修改的要求；如果
正确 delivery 仍失败，说明 validator 本身需要修正。

### 6.6 不能自动验证的任务

以下 target 不进入自动 RQ4：

- Requirement 无法转换成确定性断言；
- 缺少必要外部服务且无法模拟；
- Code Environment 无法安装或运行；
- Requirement 仍存在阻塞实现的歧义；
- 只能进行主观视觉或风格判断。

这些 target 可以继续用于 RQ1–RQ3，但标记为 `RQ4_NOT_EXECUTABLE`。

### 6.7 失败与环境错误

- Agent timeout、修改后 build 失败或 Target Test 失败：RQ4 FAIL；
- Agent 运行前 `pre_repo` 无法安装或 validator 自身崩溃：环境错误，修复后重跑，不给
  Agent 记 0；
- Agent 不修改代码但最终测试全部通过：仍然 PASS，因为 RQ4 评价行为结果，不要求必须产生
  patch。

---

## 7. 最小实现清单

要真正使用 Claude Code、Codex 或其他 Coding Agent 跑测试，至少需要实现：

1. `public_materializer`：按各 RQ 的 availability 生成安全输入；RQ2 不生成正式 C1 run；
2. `agent_runner`：在独立 workspace 中调用 Agent，并保存 JSON、patch 和日志；
3. `requirement_aligner`：当前已由 `Code/evaluation/rq1.py` 实现 all-pairs relation contract、
   无人工复核的一对一对齐、RQ1 正式指标及 target-level macro 聚合，结果也供 RQ2 使用；
4. `rq2_typed_state_scorer`：读取 field comparator specs，只在 matched Requirements 上评价
   \(G(t^-)\)，并另报 coverage；
5. `rq3_branch_scorer`：先评价 ACT/CLARIFY，再分别评价 Post-state 或 blocking
   clarification；
6. `rq4_validator_runner`：只对最终 RQ3 Gold 为 ACT 的 condition 执行 target-specific
   hidden validator，根据 exit code 生成 `rq4_pass`。

当前 RQ1 instances 已包含确定性 Atom/Evidence Gold；RQ2/RQ3 仍包含 provisional Gold，且 RQ4 的 `acceptance_criteria`、
`validator_ids` 为空、`execution_ready=false`。因此现阶段可以测试 materialization 和 Agent
运行流程，但在 RQ2 field comparator review、RQ3 branch Gold review 和 RQ4 hidden
validators 完成前不能发布对应正式分数。当前生成器已经输出 RQ1/RQ2/RQ3 v2 response
contracts；任何遗留 v1 instance 必须先重新生成 public inputs。

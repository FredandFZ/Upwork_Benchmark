# ReqMemBench RQ 实例构建设计

## 1. 文档状态与适用范围

本文定义 ReqMemBench 在已经获得 `gold_state` 和时间对齐的代码环境 `C_env / C(t^-)` 后，如何构建可运行、可评分、无未来信息泄漏的 RQ evaluation instances。

本文的权威语义来源依次为：

1. `Constuction_guideline/ReqMemBench_RP_V2.md` 中的四个 Research Questions；
2. 论文 `Task Formulation`、`Instance Construction` 和 `Experimental Design and Evaluation Protocol`；
3. 当前 Stage 1 Requirement annotation、Requirement State Graph 和 Stage 2 Gold State schema；
4. 当前 code-state reconstruction 产物及其 boundary / checksum / validation reports。

本文只使用 RP V2 定义的四个 RQ：RQ1 Relevant Requirement Selection、RQ2 Current Requirement State Reconstruction、RQ3 Memory-or-Clarify Decision 和 RQ4 Requirement-to-Code Execution。

本文设计的目标是形成一份可以直接指导后续 schema、builder、prompt、scorer、hidden tests 和质量审查实现的设计契约。本文不重新标注 Requirement lifecycle，也不修改已有 Gold State。

---

## 2. 核心设计结论

### 2.1 基本实例单位是一个真实 target task

ReqMemBench 的基本单位不是单个 Requirement，也不是为四个 RQ 人工编写四道题，而是一个真实 target time 上的完整 client task：

\[
I_i = \left(P, t_i^*, H_{<t_i^*}, C_{t_i^{*-}}, q_{t_i^*}\right).
\]

同一条 client message 可能同时 INTRODUCE、MODIFY、REMOVE 或使多个 Requirements 产生 ambiguity，因此必须保持 message-level atomicity。

### 2.2 一个 core instance，四个 evaluation views

每个 target 只构建一次共享的 Core Instance：

```text
Selected Target
    + Pre/Post Gold State
    + Requirement State Graph
    + Pre-task Repository
    + Sanitized Pre-task History
            ↓
      Core RQ Instance
            ↓
    ┌───────┼────────┬────────┐
    RQ1     RQ2         RQ3      RQ4
    Select  Reconstruct Decide   Execute
```

四个 RQ 使用同一事实基础，但读取不同 gold fields、采用不同 eligibility 和 metrics。不得分别生成互相独立、可能相互矛盾的 RQ Gold。

### 2.3 公开输入与 hidden gold 严格分离

Agent 可见：

- 由 condition 决定的历史消息；
- 当前 target task；
- target 前一刻的 repository；
- 通用任务说明、工具和资源预算。

Agent 不可见：

- Requirement / Event / State IDs；
- `affected_requirement_ids`、`primary_rq_targets`；
- Pre/Post Gold State；
- Requirement State Graph；
- relevant-history gold；
- expected action、acceptance criteria 和 hidden tests；
- target message 之后的任何消息、状态、代码或测试。

### 2.4 Gold State 是状态真值，不等于完整 RQ Gold

当前 `gold_states.json` 和 `requirement_state_graph.json` 已经提供：

- target task；
- task events；
- directly affected Requirements；
- Pre-task / Post-task state IDs；
- attributes、scope、lifecycle、ambiguity、execution；
- supporting Event provenance。

但构建完整 RQ instance 还需要派生并审核：

- 哪些未被当前 task 修改的历史 Requirements 仍然约束当前 action；
- RQ1 的完整 temporal evidence trajectory；
- 哪些 OPEN ambiguities 对当前 task 具有阻塞性；
- condition-specific 的 Evidence Sufficiency；
- RQ4 的 expected actions、可执行 acceptance criteria 和 hidden validators。

`primary_rq_targets` 只是 target-selection 阶段对 benchmark value 的标签，不是最终 `rq_eligibility`，也不能直接充当 RQ Gold。

---

## 3. 形式化定义

对于 project $P$ 中到达时间为 $t^*$ 的 target task $q_{t^*}$，定义：

- $H_{<t^*}$：严格早于 target message 的、已脱敏的完整项目历史；
- $C_{t^{*-}}$：尚未应用 target message 中任何变化的 pre-task repository；
- $G_P(t^{*-})$：Pre-task Project Gold State；
- $G_P(t^{*+})$：原子应用 target message 中全部 Events 后的 Post-task Project Gold State；
- $\mathcal{A}(q)$：target message 直接产生 Event 的 affected Requirement set；
- $\mathcal{N}(q)$：由 target 首次引入、在 Pre-task Gold 中不存在的 new Requirement set；
- $\mathcal{K}(q)$：target 不直接修改、但执行时必须继承的 applicable constraint set；
- $\mathcal{R}(q)=\mathcal{A}(q)\cup\mathcal{K}(q)$：完成当前 task 所需的完整 relevant Requirement set；
- $\mathcal{R}^{hist}(q)$：与当前 task 相关且在 target 前已经存在的 historical Requirement set。

其中：

\[
\mathcal{R}^{hist}(q)
=
\left(\mathcal{A}(q)\setminus\mathcal{N}(q)\right)
\cup
\mathcal{K}(q).
\]

这里必须区分 `affected` 与 `relevant`：

- `affected` 表示当前消息改变了该 Requirement；
- `relevant` 表示正确理解或执行当前 task 必须使用该 Requirement；
- 一个 project-persistent 安全约束可以 relevant 但不 affected；
- 一个新 Requirement 可以 affected，但不存在 pre-task historical evidence。

如果只把 `affected_requirement_ids` 当作 RQ1 Gold，会漏掉当前任务必须继承的历史约束；如果把全部 `preserved_requirement_ids` 当作 relevant，又会把绝大多数无关历史错误加入 Gold。

### 3.1 Applicable constraint 的判定

一个 preserved Requirement $r$ 进入 $\mathcal{K}(q)$，当且仅当满足以下 causal-necessity test：

> 在其他输入不变的情况下，删除 $r$ 的历史证据，会改变当前 task 的正确状态解释、Act/Clarify 决策、代码行为或验收标准。

候选约束可由以下信息确定性提出：

- `PROJECT_PERSISTENT` persistence；
- Requirement 与 target 的 component/context overlap；
- `requirements_to_code` 中的 shared code paths；
- target task 所触及的 API、数据、认证、安全、隐私、部署或跨模块接口；
- Post-task acceptance criteria 对其他 Requirement 的依赖。

component overlap 只能生成 candidate，不能单独决定 Gold。最终 `inherited_constraint_requirement_ids` 必须通过人工审核或双人 adjudication。

### 3.2 Relevant evidence 的两个层级

对每个 $r\in\mathcal{R}^{hist}(q)$，保存两个不同 evidence sets：

1. `current_support_event_ids`：直接支持 $G_r(t^{*-})$ 当前状态的最小 Event 集合，来自 state node 的 `supporting_event_ids`；
2. `trajectory_event_ids`：target 前为了观察 introduction、modification、override、defer/resume、removal、ambiguity/resolution 和 execution evolution 而需要保留的有序 Event trajectory。

C3 不能只暴露 `current_support_event_ids`。如果只给最终支持证据，相当于提前替 Agent 消除了旧值和 override，无法继续测试 RQ2 temporal reconciliation。C3 应删除 unrelated history，但保留 relevant Requirements 的完整必要 trajectory。

Event IDs 只在 hidden gold 中使用。Agent 实际看到的是这些 Events 对应的原始脱敏 messages。

---

## 4. 当前输入产物与 join contract

### 4.1 必需输入

| Artifact | 当前作用 |
| --- | --- |
| `outputs/stage2/<project_id>/gold_states.json` | target IDs、task、task Events、affected/preserved IDs、Pre/Post state references |
| `outputs/stage2/<project_id>/requirement_state_graph.json` | 将 state IDs 展开为完整 state，并取得 Event edges 与 provenance |
| `outputs/stage2/<project_id>/target_time_selection/selected_target_times.json` | target-selection 来源、history metadata、初步 RQ tags |
| `outputs/stage1_runs/<project_id>/normalized_project.json` | 稳定的 message IDs、speaker、timestamp、text 和 milestone |
| PII-clean project history | 最终提供给 Agent 的历史文本 |
| `Code Environment/<project_id>/targets/<target>/pre_repo.zip` | $C(t^-)$ |
| target `manifest.json` 和 `reports/target_index.json` | code-state boundary、Requirement-to-code map、fixture 和 checksum |
| code reconstruction validation report | build/test/leakage/secret validation |

### 4.2 Join keys

Builder 必须只通过稳定 IDs join：

```text
project_id
target_id
target_task.source_message_id == before_message_id
requirement_id
state_id
event_id
source_message_id
```

禁止用 message text、目录顺序或相似字符串作为主 join key。

### 4.3 Pre/Post State 展开

当前 `gold_states.json` 中的 Project Gold snapshot 保存 `requirement_id + state_id`。RQ builder 必须从 State Graph 展开每个 state 为：

```json
{
  "attributes": {},
  "scope": {
    "persistence": null,
    "components": [],
    "contexts": []
  },
  "lifecycle_status": null,
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": []
}
```

展开失败、重复 state ID 或 `requirement_id` 不一致时，整个 target 构建失败，不能静默跳过该 Requirement。

---

## 5. 三个受控 History Conditions

同一个 core instance 物化为以下三个输入条件。除历史输入外，repository、target task、system prompt、agent scaffold、工具、预算、重试策略和停止条件必须相同。

### 5.1 C1 — No History

\[
I_{C1}(t^*) = C_{t^{*-}} + q_{t^*}.
\]

Agent 不获得任何 target 之前的 conversation message。代码本身仍是可观察证据，因此 C1 测量“current code + current task”能够支持多少状态理解与行动。

不得向 C1 附加由历史生成的 Requirement catalog、state summary 或 affected Requirement IDs，否则它不再是严格的 No History。

### 5.2 C2 — Full History

\[
I_{C2}(t^*) = H_{<t^*} + C_{t^{*-}} + q_{t^*}.
\]

`H_{<t^*}` 必须：

- 按稳定 conversation order 排列；
- 只包含 `message_id < target_message_id`；
- 保留 client、freelancer 和可用 execution feedback；
- 同时包含 relevant、stale 和 irrelevant information；
- 使用 PII-clean text，但不得改写 requirement semantics；
- 为每条消息公开稳定的 `message_id`，以支持 RQ1 evidence selection。

RQ1 只在 C2 下评分。

### 5.3 C3 — Oracle Relevant History

\[
I_{C3}(t^*) = H^{rel}_{<t^*} + C_{t^{*-}} + q_{t^*}.
\]

C3 由 `trajectory_event_ids` 映射到 source messages，再加入理解代词、问答或引用关系所必需的少量 contextual messages。所有消息仍按原始顺序排列。

C3 必须满足：

- `C3 message IDs` 是 `C2 message IDs` 的子集；
- 包含 relevant Requirement 的必要旧值和后续变化；
- 不把历史总结为当前答案；
- 不公开 Event type、Requirement ID、state label 或 gold rationale；
- 不包含 target message 本身；
- 不因 context-window budget 进一步截断关键 trajectory。

### 5.4 Evidence-neutral contextual messages

某些消息本身不改变 Requirement State，但为理解紧邻消息中的 “this”、 “that option” 或简短确认不可缺少。Gold 中将消息分为：

- `CORE`：直接承载 Requirement Event 或当前状态证据；
- `CONTEXT`：仅用于解释 CORE evidence；
- `IRRELEVANT`：与当前 task 无因果关系。

RQ1 的 primary evidence recall 以 CORE 为正例；选择 CONTEXT 不计 false positive；选择 IRRELEVANT 计 false positive。C3 同时包含 CORE 和必要 CONTEXT。

---

## 6. Agent 运行协议与公共输出

### 6.1 推荐使用同一次运行捕获四阶段结果

为了分析 error propagation，推荐同一 target-condition run 先生成简短结构化 task record，再按 decision 修改 repository：

```text
Observe history/task/repo
        ↓
Select evidence
        ↓
State current requirements
        ↓
ACT or CLARIFY
        ↓
Patch / no speculative patch
```

结构化 record 只要求结论和 evidence references，不要求暴露私有 chain-of-thought。

### 6.2 Agent response schema

推荐公共响应保存为：

```json
{
  "schema_version": "rq-agent-response-v1",
  "instance_id": "42204309_T003_C2",
  "selected_history_message_ids": [8, 21, 156],
  "requirements": [
    {
      "requirement_ref": "agent-local-small-block-prize",
      "requirement_summary": "Small Block prize mechanism",
      "evidence_message_ids": [8, 21, 156],
      "current_state": {
        "attributes": {},
        "lifecycle_status": "ACTIVE",
        "scope": {
          "persistence": "PROJECT_PERSISTENT",
          "components": ["BACKEND", "SMART_CONTRACT"],
          "contexts": ["PRIZE_SYSTEM", "SMALL_BLOCK"]
        },
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "ACT",
  "clarification": null,
  "planned_actions": [
    {
      "requirement_ref": "agent-local-small-block-prize",
      "action": "MODIFY",
      "summary": "Update the prize count and draw interval while preserving unchanged rules."
    }
  ]
}
```

`requirement_ref` 是 Agent 自己生成的局部标识，不要求猜测 hidden Requirement ID。Scorer 使用 evidence message overlap、规范化 title/attributes 和一对一 maximum-weight matching 将 prediction 对齐到 Gold Requirement。所有自动匹配结果必须保存 confidence；低于阈值或存在并列时进入 adjudication，不允许由 LLM judge 静默决定 primary score。

这种设计避免向 C1 暴露历史 Requirement catalog，也避免要求模型准确猜出内部 `REQ_*` 命名。

### 6.3 Repository output

当 `decision = ACT` 且任务可执行时，Agent 在解压后的 workspace 中提交代码变化。Evaluator 记录：

- unified diff；
- changed-file list；
- final repository hash；
- public command logs；
- hidden validator results；
- timeout、tool error 和 invalid response。

当 `decision = CLARIFY` 时，Agent 必须给出具体 clarification question，且不得对被阻塞维度做 speculative source change。

---

## 7. RQ1 — Relevant Requirement Selection

### 7.1 研究问题

> Can the agent identify historical requirements and evidence that are relevant to the current task while ignoring irrelevant project history?

### 7.2 Eligibility

RQ1 只在 C2 下运行和计分，并至少满足：

- $\mathcal{R}^{hist}(q)$ 非空；
- Full History 中同时存在 relevant evidence 与 unrelated/stale history；
- 当前 task 对历史存在真实依赖，而不是仅凭 target message 即可完整作答。

新 Requirement 本身不进入 historical requirement selection，但记录在 `new_requirement_ids`，用于诊断 Agent 是否错误检索不存在的旧 requirement。

### 7.3 RQ1 Gold

```json
{
  "relevant_requirement_ids": ["REQ_SMALL_BLOCK_PRIZE"],
  "directly_affected_historical_requirement_ids": ["REQ_SMALL_BLOCK_PRIZE"],
  "inherited_constraint_requirement_ids": [],
  "new_requirement_ids": [],
  "evidence": {
    "REQ_SMALL_BLOCK_PRIZE": {
      "current_support_event_ids": ["..."],
      "trajectory_event_ids": ["..."],
      "core_message_ids": [8, 21, 156],
      "context_message_ids": []
    }
  }
}
```

### 7.4 Metrics

RQ1 至少报告：

- Requirement selection Precision / Recall / F1；
- CORE evidence message Precision / Recall / F1；
- Current-support evidence recall；
- Temporal-trajectory evidence recall；
- irrelevant-history selection rate；
- new-requirement false retrieval rate。

Requirement selection 从已对齐的 response requirement items 得到；evidence selection 直接使用稳定 message IDs 评分。

### 7.5 边界规则

- 被 override 或 removed 的旧消息仍可能是 temporal trajectory 的 relevant evidence，不等于 distractor；
- 与 target component 相同但不会改变正确 action 的历史，不自动算 relevant；
- 当前 target message 不属于 historical evidence；
- supporting Event 在同一 source message 中影响多个 Requirements 时，message 可以同时支持多个 Gold entries；
- Agent 选择全部历史会获得高 recall，但因大量 IRRELEVANT false positives 得到低 precision。

---

## 8. RQ2 — Current Requirement State Reconstruction

### 8.1 研究问题

> Can the agent reconcile requirement evolution and recover the currently valid requirement state immediately before the target task?

RQ2 的 primary Gold 是 $G_P(t^{*-})$ 在 $\mathcal{R}^{hist}(q)$ 上的投影，不是项目结束状态，也不是仅复述 target message 后的 Post-task State。

Post-task State 用于构造 RQ3/RQ4 的正确 decision 和 action；如果需要，可另外报告 task-transition interpretation 作为 secondary diagnostic，但不能与 primary Pre-task reconstruction 混为同一分数。

### 8.2 State dimensions

每个 relevant historical Requirement 评分以下五个 state dimensions，并加一个 selection dimension：

1. `selection`：是否恢复了正确的 relevant Requirement set；
2. `attributes`：当前有效 key/value，旧值不得继续有效；
3. `lifecycle`：如 ACTIVE、DEFERRED、REMOVED；
4. `scope`：persistence、components、contexts；
5. `ambiguity`：OPEN/closed、dimension 和 material description；
6. `execution`：如 FAILED、CLAIMED_WORKING、VERIFIED_WORKING。

`null` 是合法 Gold。模型不能因为没有 evidence 就猜测一个非空状态。

### 8.3 RQ2 Gold

```json
{
  "gold_requirement_ids": ["REQ_SMALL_BLOCK_PRIZE"],
  "states": {
    "REQ_SMALL_BLOCK_PRIZE": {
      "state_id": "REQ_SMALL_BLOCK_PRIZE_S003",
      "attributes": {},
      "lifecycle_status": "ACTIVE",
      "scope": {},
      "ambiguity": null,
      "execution": null
    }
  }
}
```

`state_id` 和 `requirement_id` 仅用于 evaluator join，不公开给 Agent。

### 8.4 Field matching

- scalar：类型规范化后的 exact match；
- numeric/currency：单位规范化后比较，禁止把 `$500` 与 `$5,000` 视为文本近似；
- boolean：exact match；
- unordered sets：set Precision / Recall / F1；
- ordered business rules：保持顺序并按 list element 评分；
- attributes object：按 Gold keys 评分，遗漏为 0，额外冲突值计 false positive；
- lifecycle：exact match；
- ambiguity：status 与 dimension 为 primary exact fields，description 用于人工诊断；
- execution：status 为 primary，observed behavior 采用预定义 fact units，而不使用开放式文风评分。

### 8.5 State scores

对 instance $i$，定义：

\[
S_{state}^{(i)}=
\frac{1}{6}
\left(
S_{sel}+S_{attr}+S_{life}+S_{scope}+S_{amb}+S_{exec}
\right),
\]

其中没有 Gold applicability 的 dimension 不进入分母。必须同时报告：

- `state_e2e`：遗漏 Gold Requirement 时，其适用 dimensions 计 0；
- `state_conditional_on_match`：只在成功对齐的 Requirement 上测状态质量。

前者反映完整重建能力，后者将 selection failure 与 state reasoning failure 分开。

### 8.6 典型错误

- 使用被后续 Event override 的旧 attributes；
- 将 TASK_LOCAL 扩大为 PROJECT_PERSISTENT；
- 把 REMOVED Requirement 当成 ACTIVE；
- 丢失没有在 target message 中重复的 persistent fields；
- 把 Freelancer implementation claim 当成 client requirement value；
- 忽略 FAILED execution state；
- 把已被后续明确信息解决的冲突错误标成 OPEN ambiguity。

---

## 9. RQ3 — Memory-or-Clarify Decision

### 9.1 研究问题

> Given exactly the evidence available in the current condition, does the agent know enough to act, or should it ask the client for clarification?

RQ3 是 evidence-sufficiency decision，不是一般的 conflict detection。一个历史冲突如果已经被较晚且更权威的 evidence 解决，应属于 RQ2 temporal reconstruction，而不是 RQ3 `CLARIFY`。

### 9.2 Condition-specific decision Gold

Requirement truth $G_P(t)$ 在 C1/C2/C3 间不改变，但 Agent 可用 evidence 不同。因此 RQ3 decision Gold 按 condition 保存：

\[
D^*_{i,c} =
\begin{cases}
\mathrm{CLARIFY}, & \text{if evidence in condition }c\text{ cannot determine a safe action};\\
\mathrm{ACT}, & \text{otherwise.}
\end{cases}
\]

典型情况：

- 历史中已有清晰 persistent rule：C1 可能是 CLARIFY，C2/C3 为 ACT；
- 历史与 target 合并后仍存在真实 blocking ambiguity：C1/C2/C3 均为 CLARIFY；
- target message 明确解决旧 ambiguity：C2/C3 为 ACT；
- ambiguity 存在但不影响当前 task：ACT。

C2 和 C3 包含相同的 relevant evidence，因此其 normative decision Gold 应相同。若两者不同，说明 C3 evidence construction 或 C2 context delivery 存在错误。

此外保存一个 condition-invariant 的 `project_decision_gold`，表示在完整合法项目证据下 task 是 ACT 还是 CLARIFY。它用于区分：

- 项目本身存在 genuine ambiguity；
- 项目状态其实明确，但 C1 因主动移除 history 而只能安全 clarification。

RQ3 primary policy score 使用 `decision_by_condition`；同时报告相对于 `project_decision_gold` 的 autonomous resolution 和 missing-history gap。不得把二者混成一个 accuracy。

### 9.3 Blocking ambiguity

不能使用“Post-task State 中存在任意 OPEN ambiguity”直接派生 CLARIFY。必须同时满足：

1. ambiguity 在综合当前 task 后仍 OPEN；
2. ambiguity 属于 $\mathcal{R}(q)$；
3. ambiguity 影响当前必须决定的 attribute、scope、lifecycle 或 execution action；
4. 不同解释会产生 materially different implementation / response；
5. code state 或同 condition 中的其他可靠 evidence 不能安全消除它。

Gold 保存：

```json
{
  "project_decision_gold": "CLARIFY",
  "decision_by_condition": {
    "C1": "CLARIFY",
    "C2": "CLARIFY",
    "C3": "CLARIFY"
  },
  "blocking_ambiguities": [
    {
      "requirement_id": "REQ_AAVE_PRIZE_POOL_YIELD",
      "ambiguity_event_id": "REQ_AAVE_PRIZE_POOL_YIELD_E002",
      "dimension": "LIFECYCLE",
      "reason": "The client suggests it may be unnecessary but does not authorize removal."
    }
  ],
  "safe_subactions": []
}
```

### 9.4 Multi-requirement task

如果 task 的一部分可以安全执行、另一部分被 ambiguity 阻塞：

- task-level primary decision 为 `CLARIFY`；
- `safe_subactions` 记录可独立执行的部分；
- Agent 不得对 blocked dimensions 猜测；
- 是否允许先执行 safe subactions 由 action policy 明确记录，不能由 scorer 临时决定。

### 9.5 Metrics

RQ3 报告：

- Accuracy；
- Macro F1；
- ACT recall；
- CLARIFY recall；
- Unsupported Autonomy Rate：Gold CLARIFY、Agent ACT；
- Unnecessary Clarification Rate：Gold ACT、Agent CLARIFY；
- clarification target accuracy：问题是否指向正确 Requirement 和 dimension。
- project-decision accuracy 与 memory-enabled actionability rate，作为独立 secondary metrics。

安全性分析中，Unsupported Autonomy 的严重性高于措辞不完美。

---

## 10. RQ4 — Requirement-to-Code Execution

### 10.1 研究问题

> Can the agent translate the correct requirement state into an appropriate development action and, when executable, a correct code change in the current repository?

RQ4 的输入是对应 condition 的完整实例：

\[
I_c(t^*) = H^{(c)}_{<t^*} + C_{t^{*-}} + q_{t^*},
\]

其中 C1 的 $H^{(c)}$ 为空，C2 为 Full History，C3 为 Oracle Relevant History。

其语义 Gold 来自 Pre/Post Requirement State delta、relevant inherited constraints 和 RQ3 policy decision，而不是唯一的 reference patch。

### 10.2 Eligibility

一个 target 进入 executable RQ4，至少满足：

- 对应 `pre_repo.zip` 存在且 checksum 验证通过；
- repository boundary 与 target message 一致；
- target 具有可识别的 code impact；
- expected behavior 可以被 deterministic validator 检查；
- public environment tests 能运行；
- target answer 没有提前泄漏到 public tests、README、TODO 或 manifest；
- `implementation_mode` 不是纯 `non_code_action`；
- reconstructed/simulated substrate 已被明确标记。

`primary_rq_targets` 包含 RQ4 不自动意味着 executable eligibility。必须以 validator readiness 为准。

### 10.3 Requirement-level action taxonomy

论文主表使用以下 action classes：

- `IMPLEMENT`：Pre-task 不存在，Post-task 建立可执行 Requirement；
- `MODIFY`：attributes、scope、lifecycle activation 或 failed behavior 需要改变；
- `REMOVE`：Requirement 变为 REMOVED，或公开行为必须取消；
- `PRESERVE`：历史 Requirement 本身不变，但当前修改必须继续满足它；
- `CLARIFY`：当前 condition 的 evidence 不足，不得猜测实现。

内部可以保存更细的 operation，如 `DEFER`、`RESUME`、`REPAIR`、`VERIFY`，但论文 aggregation 必须映射到上述主 taxonomy，并保留 mapping table。

### 10.4 Expected action Gold

```json
{
  "task_action_by_condition": {
    "C1": "CLARIFY",
    "C2": "APPLY_CHANGES",
    "C3": "APPLY_CHANGES"
  },
  "requirement_actions": {
    "REQ_SMALL_BLOCK_PRIZE": {
      "action": "MODIFY",
      "before_state_id": "REQ_SMALL_BLOCK_PRIZE_S003",
      "after_state_id": "REQ_SMALL_BLOCK_PRIZE_S004"
    },
    "REQ_SECURITY_CONSTRAINT": {
      "action": "PRESERVE",
      "before_state_id": "REQ_SECURITY_CONSTRAINT_S002",
      "after_state_id": "REQ_SECURITY_CONSTRAINT_S002"
    }
  },
  "acceptance_criteria": [],
  "validator_ids": []
}
```

### 10.5 Validation layers

每个 executable target 至少包含：

1. **Environment gate**：install、build、lint/format、public smoke tests；
2. **Target behavior tests**：验证 target 新增或修改的 Gold behavior；
3. **Negative/removal tests**：验证 removed、deferred 或 forbidden old behavior 不再存在；
4. **Inherited-constraint tests**：验证 relevant preserved Requirements 仍满足；
5. **Regression tests**：覆盖未受影响但高风险的现有功能；
6. **Temporal fixture tests**：对 runtime-failure target，先确认 pre-state defect 可复现，再确认 patch 修复；
7. **No-speculation gate**：Gold CLARIFY 时，blocked source area 不得发生 speculative change；
8. **Security/leakage gate**：不写入 secrets，不读取或输出 hidden gold。

public tests 只用于确认环境完整性，不能把目标常量、预期接口名或修复方式暴露给 Agent。Requirement-specific validators 必须 hidden。

### 10.6 RQ4 metrics

至少报告：

- requirement-level action accuracy；
- task-level exact action success；
- build success；
- target hidden-test pass rate；
- inherited-constraint pass rate；
- regression-free rate；
- clarification-policy success；
- full task success：所有 mandatory gates 同时通过。

完整 task 中任意一个 mandatory affected Requirement 失败，则 task-level result 为 FAIL；同时保留 requirement-level partial results 用于诊断。

对于 C1，需同时报告：

- policy correctness：证据不足时是否正确 clarification；
- implementation success：仅在 Gold ACT 的 runs 上计算；
- autonomous coverage：Agent 实际选择 ACT 的比例。

这样不会把安全 clarification 错误统计为 coding failure，也不会把永远 clarification 的 Agent 误判为高 coding performance。

---

## 11. Unified Core Instance Schema

推荐 researcher-side core record 为：

```json
{
  "schema_version": "rq-core-instance-v1",
  "instance_id": "42204309_T003",
  "project_id": "42204309",
  "target_id": "42204309_T003",
  "target_message_id": 158,
  "turns": 157,
  "history_turn_count": 157,
  "target_task": {
    "speaker": "client",
    "text": "..."
  },
  "artifacts": {
    "pre_repo": ".../pre_repo.zip",
    "pre_repo_sha256": "...",
    "code_manifest": ".../manifest.json",
    "gold_state_ref": "42204309_T003_GOLD"
  },
  "task_transition": {
    "task_event_ids": [],
    "affected_requirement_ids": [],
    "new_requirement_ids": [],
    "pre_task_states": {},
    "post_task_states": {}
  },
  "relevance_gold": {
    "relevant_historical_requirement_ids": [],
    "inherited_constraint_requirement_ids": [],
    "evidence_by_requirement": {}
  },
  "condition_inputs": {
    "C1": {"history_message_ids": []},
    "C2": {"history_message_ids": []},
    "C3": {"history_message_ids": []}
  },
  "rq_eligibility": {
    "RQ1": {"C1": false, "C2": true, "C3": false},
    "RQ2": {"C1": true, "C2": true, "C3": true},
    "RQ3": {"C1": true, "C2": true, "C3": true},
    "RQ4": {"C1": true, "C2": true, "C3": true}
  },
  "rq_gold": {
    "RQ1": {},
    "RQ2": {},
    "RQ3": {},
    "RQ4": {}
  },
  "quality": {
    "automatic_validation": "PASS",
    "human_review": "PENDING",
    "adjudication": null
  }
}
```

这里的 `rq_eligibility.RQ4 = true` 表示该 condition 下可以评价正确 development action。若 decision Gold 为 CLARIFY，它可以评价 policy action，但不一定进入 executable-code success 分母。建议另存 `execution_eligible_by_condition`，避免两个概念混用。

---

## 12. 目录布局

当前实例构造阶段按项目直接输出四个 RQ 文件夹。`private/public` 的运行时拆分留给后续
evaluation runner；现阶段每个 JSON 都是 researcher-side construction record，不能原样
交给 Agent：

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

顶层 `turns` 与 `history_turn_count` 同值，均表示 target 前的规范化消息数量；保留
`turns` 用于后续难度分类。实例内的 `construction_gold`、内部 Requirement/Event/State ID
与 source provenance 不得进入 Agent workspace。三个 condition 引用同一个 history pool
和 repository blob；RQ4 运行时必须在独立干净 workspace 中解压。

---

## 13. RQ Instance Construction Pipeline

### Stage A — Artifact validation

1. 读取 selected targets；
2. join Gold State、State Graph、normalized history 和 code manifest；
3. 验证 target message ID、pre-repo boundary 和 checksum；
4. 验证 Pre/Post state IDs 全部可展开；
5. 验证同一 target message 的 Events 被原子包含；
6. 验证 code reconstruction report 已通过。

任一硬校验失败时，该 target 状态为 `BUILD_BLOCKED`，不得生成正式实例。

### Stage B — State and transition expansion

1. 展开完整 $G_P(t^{*-})$ 和 $G_P(t^{*+})$；
2. 计算 new / affected / preserved sets；
3. 对 affected Requirements 计算 field-level delta；
4. 保留 unchanged fields，避免把 target 未重复的值误判为删除；
5. 收集 lifecycle、ambiguity 和 execution transitions。

### Stage C — Task relevance derivation

1. 将 historical affected Requirements 加入 direct relevant set；
2. 根据 persistence、scope、code paths 和 acceptance dependencies 提出 inherited-constraint candidates；
3. 应用 causal-necessity test；
4. 人工确认 `inherited_constraint_requirement_ids`；
5. 保存排除原因，避免后续版本无依据改变 relevant set。

### Stage D — Evidence construction

1. 从 State Graph 提取每个 relevant Requirement 的 Event trajectory；
2. 映射为 source message IDs；
3. 标记 CORE / CONTEXT / IRRELEVANT；
4. 构造 C2 full slice；
5. 构造 C3 ordered oracle subset；
6. 验证 C3 是 C2 子集并包含完整必要 temporal trajectory。

### Stage E — RQ Gold derivation

- RQ1：relevant Requirements + evidence sets；
- RQ2：relevant Pre-task states 六维 Gold；
- RQ3：按 condition 进行 evidence-sufficiency audit；
- RQ4：从 Pre/Post delta、inherited constraints 和 RQ3 decision 生成 action Gold。

所有可确定字段由规则生成。Human review 只审核 task-specific relevance、blocking ambiguity、condition sufficiency 和 acceptance criteria，不重新改写 Requirement lifecycle truth。

### Stage F — Validator construction

1. 从 Post-task state delta 写 behavioral acceptance criteria；
2. 为 unchanged inherited constraints 写 preservation criteria；
3. 为 removed/forbidden behavior 写 negative criteria；
4. 为 runtime defect 写 pre-fail/post-pass fixture；
5. 实现 hidden validators；
6. 在 untouched pre repo 上执行，确认 target tests 在预期位置失败；
7. 在 canonical post reconstruction 或独立 reference implementation 上执行，确认全部通过；
8. 检查 validator 没有绑定到唯一实现细节。

### Stage G — Materialization and final audit

1. 写入 C1/C2/C3 public input；
2. 写入 private Gold；
3. 计算所有文件 checksums；
4. 执行 future leakage、secret、PII 和 hidden-file scan；
5. 执行 schema validation；
6. 双人 review 高风险 target；
7. 冻结 schema version 和 input fingerprint。

---

## 14. 自动校验不变量

### 14.1 Temporal boundary

- 所有 C2/C3 history message IDs 严格小于 target message ID；
- `pre_repo` 尚未应用任何 target Event；
- `post_task_gold_state` 已应用 target message 的全部 Events；
- target 同消息 Events 不得部分应用；
- public package 不包含后续 code、test、TODO、commit objects 或 conversation。

### 14.2 Gold consistency

- 每个 state reference 在 Graph 中唯一存在；
- Pre/Post snapshot 与 state chain replay 一致；
- new Requirements 只在 Post State 中首次出现；
- affected set 与 target Event owners 一致；
- inherited constraints 必须来自 Pre State，且 Post State 保持或有明确 transition；
- RQ2 Gold 只引用 target 前已经建立的 state；
- RQ3 blocking ambiguity 必须指向真实 OPEN ambiguity 或 condition-specific evidence gap；
- RQ4 action 必须可追溯到 state delta、inherited constraint 或 RQ3 decision。

### 14.3 Condition consistency

- C1 history 为空；
- C3 是 C2 的有序子序列；
- C2 与 C3 的 target task 和 repository hash 相同；
- C2/C3 normative decision Gold 相同；
- RQ1 仅 C2 eligible；
- 三个 conditions 使用相同 agent scaffold 和 budget。

### 14.4 Executable consistency

- pre repo clean install/build/smoke PASS；
- manifest `before_message_id` 等于 target message ID；
- repository SHA-256 与 index 一致；
- target hidden tests 在 pre-state 不得全部通过；
- reference post-state 必须通过 target + regression tests；
- known historical defects 只能存在于对应 pre boundary，不得扩散到无关 targets；
- simulated 与 observed code layers 必须在 metadata 中可区分。

---

## 15. 人工审查协议

### 15.1 必审内容

- target 是否仍然是一个可独立理解的真实 task；
- inherited constraints 是否满足 causal-necessity；
- C3 是否删除了噪声但保留了 temporal reasoning；
- ambiguity 是否真正阻塞当前 action；
- C1 evidence sufficiency 是否判断合理；
- expected action 是否覆盖一个 message 中的全部 Requirements；
- hidden tests 是否验证 behavior 而非唯一 patch；
- reconstruction simulation 是否足以支持论文中的 claim。

### 15.2 双人 review 与 adjudication

以下 target 强制双人 review：

- RQ3 Gold 为 CLARIFY；
- REMOVE / DEFER / RESUME；
- 多 Requirement task；
- runtime failure / verification；
- 存在 inherited constraints；
- target 涉及 shared files 或多个 components；
- simulated code layer 中的 RQ4。

Reviewer 独立给出 PASS/FAIL 和理由；不一致时由第三人 adjudicate。最终报告需按字段统计 agreement，而不是只报告整条 instance agreement。

---

## 16. Metrics Aggregation 与实验切片

### 16.1 聚合层级

先在 Requirement field 上评分，再聚合到 task，最后进行 project-level macro average：

```text
Field → Requirement → Task → Project → Benchmark
```

这样不会让 Requirements 更多、attributes 更大的项目获得不成比例的权重。

同时报告 95% confidence intervals。显著性比较使用 project-level paired bootstrap 或适合配对实验的检验；不得把同一 project 的多个 targets 当作完全独立样本。

### 16.2 History strata

沿用论文定义：

- Short：0–25 pre-task turns；
- Medium：26–50；
- Long：>50。

`history_turn_count` 是实验切片变量，不参与 target quality 判断，也不能作为 target-selection evidence。

### 16.3 必须分层报告的因素

- C1 / C2 / C3；
- history stratum；
- event type 和 lifecycle transition；
- ambiguity dimension；
- single vs multi-Requirement；
- observed vs reconstructed/simulated code substrate；
- runtime-failure target；
- agent framework + backbone model + exact version。

### 16.4 诊断解释

- C3 > C2：selection / retrieval / context management 是瓶颈；
- C2 > C1：历史提供有效增益；
- C1 > C2：full history 产生干扰；
- C3 ≈ C2 但 RQ2 低：主要问题是 temporal state reasoning；
- RQ2 高、RQ4 低：主要问题是 execution；
- RQ3 中 Unsupported Autonomy 高：Agent 在证据不足时过度猜测；
- RQ3 中 Unnecessary Clarification 高：Agent 没有有效使用已有 memory。

---

## 17. 项目 42204309 的落地示例

当前项目已经具有：

- 25 个 selected targets；
- 每个 target 对应的 `gold_state`；
- 25 个通过 boundary audit 的 `C(t^-)` repositories；
- project-level Requirement State Graph；
- state-to-code manifest、repo checksum 和 validation report；
- T008、T010、T020 的历史 defect fixtures。

这些产物已经满足 Core Instance 的主要 join 前提，但仍需生成 `relevance_gold`、condition-specific RQ3 Gold、RQ4 acceptance criteria 和 hidden validators。

### 17.1 T003：状态更新与代码执行

Target `42204309_T003` 位于 message 158。client 将：

- Small Block 改为 1 × $500 every 100 sales；
- Big Block 改为 1 × $10,000 every 10,000 sales。

Gold 显示该 message 不仅修改两个 prize mechanism Requirements，还同步修改 FAQ、About page 和 Mission page content，共五个 affected Requirements。正确实例必须：

- RQ1 找到此前定义 Small/Big Block 规则的 temporal evidence；
- RQ2 恢复 target 前仍有效的旧 winner count、amount、interval、ticket reset、counted sale types 和 scope；
- RQ3 判断 message 158 给出的新数值足以 ACT，而不是因历史多个版本而重复询问；
- RQ4 在 contract/backend/frontend/content simulation 中一致更新 changed fields，同时保留未改变的 ticket window、reset 和 sale-type rules。

如果 hidden tests 只检查 `winner_count = 1`，而不检查 interval、content projection 和 preserved fields，该 RQ4 instance 是不完整的。

### 17.2 T004：真实 blocking ambiguity

Target `42204309_T004` 位于 message 159：

> “With this adjustment, the Aave integration becomes quite unnecessary.”

Post-task Gold 为 `REQ_AAVE_PRIZE_POOL_YIELD` 保持原 lifecycle，同时产生 `LIFECYCLE` OPEN ambiguity：client 表达了可能不再需要，但没有明确授权 remove。

因此：

- 这不是“较新消息自动覆盖旧 Requirement”的普通 RQ2 case；
- RQ3 正确 decision 是 CLARIFY；
- RQ4 不应直接删除 Aave integration；
- clarification 应询问是否正式移除/停用，而不是再次询问已经明确的 prize 数值。

### 17.3 T010：runtime failure + ambiguity

Target `42204309_T010` 同时包含失败 mint、no-referral mint #1 的 allocation ambiguity，以及 NFT display failures。其 pre repo 已有 `unconfirmed_rows_counted_seed` historical defect fixture。

此类 instance 必须同时检查：

- pre-state bug 是否真实可复现；
- Agent 是否区分可修复的 runtime failure 与必须 clarification 的 mint #1 allocation rule；
- Agent 是否修复独立故障但不猜测 unresolved allocation；
- 多 Requirement partial-safe action policy 是否与 Gold 一致。

---

## 18. 实施顺序

推荐按以下顺序实现：

1. 定义并校验 `rq-core-instance-v1` schema；
2. 实现 Gold State / State Graph / C_env join；
3. 实现 Pre/Post state expansion 和 field delta；
4. 实现 C1/C2 history materialization；
5. 实现 relevant trajectory 和 C3 materialization；
6. 生成人工 review packet，完成 inherited relevance 与 blocking ambiguity 审核；
7. 派生 RQ1–RQ3 Gold 和 scorer；
8. 先选择 3–5 个覆盖 MODIFY、REMOVE/DEFER、CLARIFY、RUNTIME_FAILURE 的 pilot targets；
9. 为 pilot 构造 RQ4 hidden validators 并跑 agent end-to-end；
10. 修正 schema 后冻结 v1，再扩展到全部 targets；
11. 输出 project / benchmark statistics 和 review agreement。

不建议一开始就为 25 个 targets 全量手写 hidden tests。先通过小规模 pilot 验证 response schema、Requirement matching、condition-specific decision 和 code validator 的可用性，再批量扩展。

---

## 19. Definition of Done

一个 RQ instance 只有在以下条件全部满足时才可进入正式 benchmark：

- [ ] target、Gold State、State Graph、history 和 pre repo join 成功；
- [ ] pre/post temporal boundary 通过；
- [ ] C1/C2/C3 输入按定义生成；
- [ ] C3 保留 relevant temporal trajectory 且无 gold labels；
- [ ] direct relevant 与 inherited constraints 已审核；
- [ ] RQ1 evidence labels 可追溯到原消息；
- [ ] RQ2 六维 Gold 完整且 state IDs 可展开；
- [ ] RQ3 按 condition 保存 ACT/CLARIFY Gold；
- [ ] blocking ambiguity 与 clarification target 已审核；
- [ ] RQ4 action taxonomy 与 Pre/Post delta 一致；
- [ ] executable target 具有 behavior-level hidden validators；
- [ ] pre-state、reference post-state 和 regression validation 结果符合预期；
- [ ] public package 无 future leakage、PII、secret、hidden gold 和 answer-revealing tests；
- [ ] 自动校验 PASS；
- [ ] 人工 review / adjudication 完成；
- [ ] schema version、fingerprint 和 checksums 已冻结。

完成后，ReqMemBench 的每个真实 target task 都可以在同一个事实基础上回答：

\[
\mathrm{Select}
\rightarrow
\mathrm{Reconstruct}
\rightarrow
\mathrm{Decide}
\rightarrow
\mathrm{Execute},
\]

并把最终失败明确分解为 relevant-history selection、current-state reconstruction、evidence-sufficiency decision 或 requirement-to-code execution failure。

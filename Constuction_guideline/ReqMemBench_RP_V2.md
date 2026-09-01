# ReqMemBench — Benchmark Landscape, Research Gap, and Core Research Questions

# 1. Benchmark Landscape and Research Gap

## 1.1 Core Claim

我们关注真实软件项目生命周期中的长期 Client–Agent 交互，以及 Coding Agent 是否能够利用这些历史信息持续维护项目当前真正有效的需求状态。

ReqMemBench 的核心研究问题是：

> **Can coding agents maintain and act on evolving client requirements throughout the lifecycle of a software project?**
>
> More specifically, given the historical record of a real software project before a target time $t^*$, the current code state, and a new client task, can a coding agent reconstruct the currently valid requirement state—including lifecycle, scope, temporal validity, and unresolved ambiguity—and act correctly on the task?

我们将这一过程形式化为：

$$
H_{<t^*} + C_{t^{*-}} + q_{t^*}
\rightarrow
G_P(t^{*-})
\rightarrow
\mathrm{Action}
$$

其中：

- $H_{<t^*}$：目标任务之前真实发生的项目历史，包括 client–freelancer conversations、milestones、feedback 和历史决策；
- $C_{t^{*-}}$：执行当前任务之前的项目代码状态；
- $q_{t^*}$：时间点 $t^*$ 上 client 提出的当前任务；
- $G_P(t^{*-})$：Agent 根据历史应当恢复出的当前 Project-level Requirement State；
- $\mathrm{Action}$：Agent 基于这一状态采取的行为，包括直接实现、忽略已经失效的历史要求，或者在证据不足时请求 clarification。

因此，一个 benchmark instance 并不是简单的：

**Previous Tasks → Next Task**

而是：

**Longitudinal Project History + Current Code + Current Task**

↓

**Reconstruct Current Requirement State**

↓

**Take the Correct Development Action**

历史可以跨越多个 milestone 和 session：

$$
M_1 \rightarrow M_2 \rightarrow \cdots \rightarrow M_k
$$

而 target task $t^*$ 可以位于项目生命周期中的任意一个有效时间点，而不必固定等同于整个 milestone。

这里真正困难的地方，并不是简单地把 previous milestones 作为更多 context 提供给 Agent。长期项目历史中包含大量具有不同语义状态的信息：

- 一些 requirement 与当前任务无关；
- 一些 requirement 只对过去某个 task 或 milestone 有效；
- 一些 requirement 是整个项目持续存在的约束；
- 一些已经被后续要求修改、覆盖、延期或删除；
- 还有一些历史信息存在冲突或者仍然具有 unresolved ambiguity。

因此，Coding Agent 必须从一个不断演化的项目历史中恢复：

> **What does the client actually require at this point in the project?**

并进一步根据这个状态决定：

> **What should I do now?**

---

## 1.2 Benchmark Landscape

现有 Coding Benchmark 已经分别研究了 repository context、真实软件工程任务、multi-turn coding、continual learning、long-context memory 和 iterative requirement refinement。

为了分析 ReqMemBench 所处的位置，我们从以下维度比较相关工作：

- 是否包含 repository / executable code context；
- 是否存在 longitudinal / multi-turn project history；
- 是否包含 evolving requirements；
- 是否需要恢复 requirement 的当前状态，包括 scope、persistence、update、override 和 removal；
- 是否评价 Agent 在历史证据不足时进行 clarification；
- 是否最终要求将历史 requirement 落实到 executable code。

其中 ✓ 表示明确评估，△ 表示部分涉及，✗ 表示基本未涉及。

| Benchmark | Venue / Year | Main Evaluation Setting | Repository Context | Longitudinal History | Evolving Requirements | Requirement State Reconstruction | Memory-or-Clarify | Requirement → Code | Main Limitation for Our Setting |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| **CrossCodeEval** | NeurIPS 2023 | 基于真实 repository 的 cross-file code completion，要求模型发现并利用跨文件依赖。 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | 主要解决 **static repository context retrieval**。Context 来自当前代码，而不是长期 client interaction 中不断变化的 requirements。 |
| **RepoBench** | ICLR 2024 | Repository-level code completion，并评价 retrieval、completion 和 retrieval+completion。 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | 将 context 扩展到 repository level，但 repository 仍然主要作为静态上下文，不建模 requirement evolution。 |
| **SWE-bench** | ICLR 2024 | 给定真实 GitHub repository 和 issue，生成能够解决当前 issue 的 patch。 | ✓ | ✗ | ✗ | ✗ | ✗ | △ | Evaluation unit 主要是单个 issue，不要求理解该 issue 之前长期形成的 client requirement state。 |
| **BigCodeBench** | ICLR 2025 | 在复杂 instruction 下组合 function、library 和 API 完成实际编程任务。 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 提升单次 instruction complexity，但 task specification 基本仍然是完整、静态的。 |
| **SWE-Lancer** | ICML 2025 | 使用真实 Upwork freelance software engineering tasks，包括 coding 和 managerial tasks。 | ✓ | ✗ | ✗ | ✗ | ✗ | △ | 提供真实 client-originated tasks，但 benchmark evaluation 主要仍然是 task-level，没有恢复同一项目生命周期中的 requirement trajectory。 |
| **LongMemEval** | ICLR 2025 | 测试多 session conversational memory，包括 retrieval、temporal reasoning、knowledge update 和 abstention。 | ✗ | ✓ | △ | ✓ | △ | ✗ | 已研究历史信息如何被更新和失效，但目标是 conversational memory，而不是 software requirement state，也没有 executable implementation。 |
| **ConvCodeWorld** | ICLR 2025 | 利用 compilation、execution 和 verbal feedback 构造 multi-turn code generation。 | ✗ | ✓ | △ | ✗ | ✗ | △ | 历史主要由当前 implementation 的 feedback 构成，重点是 feedback-driven repair，而非维护长期 requirement state。 |
| **SWE-Bench-CL** | 2025 | 将同一 repository 的 issues 按时间排列，研究 continual learning、transfer 和 forgetting。 | ✓ | ✓ | △ | ✗ | ✗ | ✗ | 时间结构与长期项目相似，但历史主要被视为过去 coding experience，而不是 client requirements 的持续状态。 |
| **SWE-ContextBench** | 2026 | 构造相关 coding task sequences，要求 Agent 检索并复用过去 execution trajectory 或 summary。 | ✓ | ✓ | ✗ | ✗ | ✗ | △ | 主要回答 **whether previous coding experience helps a new task**，而不是判断过去用户要求现在是否仍然有效。 |
| **SR-Eval** | 2025/2026 | 将 requirement 拆成多轮 refinement，并逐轮修改代码和执行测试。 | ✓ | ✓ | **✓** | △ | ✗ | **✓** | 已研究 stepwise requirement refinement，但 requirements 主要围绕连续 task refinement 构造，没有显式恢复 persistent / local / modified / removed / ambiguous requirement state。 |
| **RECODE-H** | 2025 | 使用 multi-turn simulated human feedback 持续修改 research code。 | ✓ | ✓ | △ | ✗ | ✗ | △ | 重点是根据 human feedback 改进已有 implementation，而不是判断长期历史 requirement 当前是否仍应适用。 |
| **LoCoEval** | 2026 | Repository-oriented long-horizon conversational benchmark，包含 iterative requirements、noise 和 retrospective questions。 | ✓ | **✓** | **✓** | △ | ✗ | △ | 与本工作最接近，但核心评价目标更偏向 **long-horizon context management**，没有系统地将当前 requirement state 与最终 coding action 建立完整的可执行评价链。 |
| **ReqMemBench** | Proposed | 从真实项目生命周期中恢复 history、current code 和 evolving client requirements，在任意 $t^*$ 评价 Agent 对当前 requirement state 的理解与执行。 | ✓ | **✓** | **✓** | **✓** | **✓** | **✓** | 核心评价对象是 **longitudinal requirement state reconstruction and action**。 |

---

## 1.3 Research Gap

现有 Coding Benchmark 已经覆盖了这一问题的许多组成部分。

CrossCodeEval 和 RepoBench 研究了如何从大型 repository 中找到正确的代码上下文；SWE-bench 和 SWE-Lancer 将 evaluation 推进到真实软件工程任务；ConvCodeWorld 和 RECODE-H 研究了 multi-turn feedback-driven coding；SWE-Bench-CL 和 SWE-ContextBench 开始关注 Coding Agent 如何跨任务积累和利用历史经验；SR-Eval 已经明确研究 iterative requirement refinement；LoCoEval 则进一步将 long-horizon conversational context 和 evolving requirements 引入 repository-level development。

因此，我们不能再简单地声称：

> “Existing coding benchmarks do not contain history.”

也不能将 Research Gap 定义为：

> “Existing benchmarks do not contain evolving requirements.”

因为近期工作已经开始覆盖这两个方向。

我们认为真正仍然缺少的是：

> **A systematic evaluation of whether coding agents can reconstruct and act on the current requirement state of a long-running software project.**

在真实的软件项目中，历史并不是一系列独立的 previous tasks，也不仅仅是可以供 Agent 复用的 experience。

项目历史实际上不断定义和修改一个隐藏的 **Requirement State**。

例如：

- 一个 requirement 可以在早期被 **introduced**；
- 随后被 **modified**；
- 某些 requirement 可能只适用于特定 task 或 milestone；
- 某些 requirement 可以持续约束后续整个项目；
- 一个旧 requirement 可以被新的 requirement **overridden**；
- 一个 requirement 可以被 **deferred** 或 **removed**；
- 两条历史信息可能互相冲突；
- 某些 requirement 可能始终存在 unresolved ambiguity。

因此，在时间点 $t^*$，真正决定 Agent 应该如何处理当前任务的，并不是历史文本本身，而是历史文本经过时间演化之后所形成的：

$$
G_P(t^{*-})
$$

即 **the current valid project requirement state before the task**。

这使得 History-aware Coding Agent 面临的问题从：

> **Can the agent retrieve and reuse useful information from previous tasks?**

进一步变成：

> **Can the agent reconstruct what the client currently requires, determine whether the historical evidence is sufficient for action, and faithfully act on that state in the current codebase?**

ReqMemBench 因而将长期软件开发中的 history usage 建模为以下过程：

**Longitudinal Project History**

↓

**Relevant Requirements**

↓

**Current Requirement State**

- Scope
- Persistence
- Lifecycle
- Modification / Override
- Removal / Deferral
- Ambiguity

↓

**Act or Clarify**

↓

**Implementation**

↓

**Executable Verification**

现有工作分别评价了 retrieval、memory、continual learning、iterative refinement、feedback utilization 或 functional correctness，但尚未系统地评价这条从：

> **Historical Interaction → Current Requirement State → Development Action**

的完整链路。

这构成了 ReqMemBench 的主要 Research Gap。

---

# 2. Core Research Questions

基于上述核心问题，我们将 ReqMemBench 划分为四个 Research Questions。

它们并不是四个彼此独立的任务，而是一个 Coding Agent 在长期项目中处理当前任务时依次需要完成的四个能力阶段：

$$
\mathrm{Select}
\rightarrow
\mathrm{Reconstruct}
\rightarrow
\mathrm{Decide}
\rightarrow
\mathrm{Execute}
$$

---

## RQ1: Relevant Requirement Selection

### Research Question

> **Can the agent identify historical requirements that are relevant to the current task while ignoring irrelevant project history?**

### What It Measures

真实项目历史中通常包含大量 conversations，包括需求讨论、bug feedback、设计决策、付款沟通、过去 milestone 的实现细节以及已经无关的功能。

因此，Agent 首先需要确定：

$$
H_{<t^*}
\rightarrow
H^{\mathrm{rel}}_{t^*}
$$

即哪些历史信息真正与当前 task $q_{t^*}$ 有关。

RQ1 主要评价 Agent 是否能够：

- 找到当前任务涉及的 historical requirements；
- 找到定义这些 requirements 的关键 historical evidence；
- 避免将无关 historical requirements 错误带入当前任务。

### Example

假设当前任务要求修改 Dashboard。

历史中同时存在：

- Dashboard 数据格式要求；
- NFT minting requirement；
- Logo design discussion；
- 一个已经结束 milestone 的 recruitment script。

正确的 Agent 应该检索 Dashboard 相关历史 requirement，而不是简单地将整个历史中的所有要求都应用到当前任务。

因此，RQ1 回答的是：

> **Which parts of the project history matter now?**

---

## RQ2: Current Requirement State Reconstruction

### Research Question

> **Can the agent reconstruct the current valid state of relevant requirements by correctly reasoning about their scope, persistence, lifecycle, updates, overrides, and removals?**

### What It Measures

找到相关 requirement 并不意味着该 requirement 当前仍然有效。

Agent 还必须根据完整的 historical trajectory 判断：

> **What is the current state of this requirement at $t^*$?**

因此，我们将原来的 **Scope & Persistence** 和 **Temporal Validity & Conflict Resolution** 合并到同一个 RQ。

这是因为：

- requirement 是否跨 milestone 持续；
- requirement 当前适用于什么 component/context；
- requirement 是否已经被修改；
- requirement 是否被新版本覆盖；
- requirement 是否已经 removed 或 deferred；

本质上都属于同一个问题：

$$
\mathrm{Historical\ Events}
\rightarrow
G_r(t^{*-})
$$

即通过 requirement lifecycle 恢复其当前状态。

RQ2 主要评价 Agent 是否能够正确识别：

- **Scope**：该 requirement 适用于哪些 component / context；
- **Persistence**：是 TASK_LOCAL、MILESTONE_LOCAL 还是 PROJECT_PERSISTENT；
- **Lifecycle**：当前是 ACTIVE、DEFERRED、REMOVED 等状态；
- **Modification**：历史 requirement 是否经过修改；
- **Override**：多个版本中哪一个当前有效；
- **Temporal Validity**：旧 requirement 是否已经失效；
- **Conflict**：历史中的冲突信息应该如何根据时间和 evidence 解析。

### Example 1 — Persistence

历史中出现：

> “All deliverables should include a Dockerfile.”

如果这一要求是 project-persistent，则后续 milestone 中即使 client 没有再次重复，它仍然应该继续生效。

相反：

> “For this migration script, use Firebase.”

如果它只属于当前 task，则 Agent 不应该错误地把 Firebase 推广成整个项目的永久技术栈。

### Example 2 — Requirement Update

假设：

$$
M_1:\ \mathrm{Deploy\ on\ AWS}
$$

随后：

$$
M_3:\ \mathrm{We\ are\ moving\ everything\ to\ Azure}
$$

到了：

$$
M_5
$$

Agent 不应因为 AWS 出现在更早历史中就继续使用 AWS。

正确的 requirement state 应为：

$$
\mathrm{CloudProvider} = \mathrm{Azure}
$$

### Example 3 — Removed Requirement

如果 client 早期要求：

> “Add the big block prize.”

但后来明确表示：

> “Remove the big block prize.”

那么在之后的任务中，该 requirement 虽然仍然属于历史的一部分，但它的当前 lifecycle state 应为：

$$
\mathrm{LifecycleState} = \mathrm{REMOVED}
$$

因此不能再次被实现。

RQ2 回答的是：

> **Given everything that happened before now, what does the client currently require?**

---

## RQ3: Memory-or-Clarify Decision

### Research Question

> **Can the agent determine when the historical evidence is sufficient for action and when unresolved ambiguity requires clarification from the client?**

### What It Measures

一个高质量的 Coding Agent 既不能忽视可靠的历史 requirement，也不能在证据不足的情况下擅自猜测。

因此，在恢复 requirement state 后，Agent 还必须判断：

$$
\mathrm{EvidenceSufficient?}
$$

如果：

$$
\mathrm{EvidenceSufficient} = \mathrm{True}
$$

则应该直接使用历史 requirement。

如果：

$$
\mathrm{EvidenceSufficient} = \mathrm{False}
$$

并且 ambiguity 会影响当前 implementation，则应该请求 clarification。

因此 RQ3 评价 Agent 是否能够区分：

**Use Memory**

与：

**Ask the Client**

### Example 1 — Memory Is Sufficient

假设 client 在多个 milestone 中均明确要求：

> “All user identifiers must be hashed before logging.”

并且没有任何后续 requirement 修改这一规则。

当前 task 再次涉及 logging 时，Agent 应该直接复用这一 project-persistent requirement，而不是重复询问 client。

### Example 2 — Clarification Is Required

如果历史中依次出现：

- PostgreSQL；
- MongoDB；
- SQLite；

但没有任何明确的信息说明哪一个是最终决定，而当前 task 又必须添加数据库相关 functionality。

那么历史无法形成唯一、可靠的 requirement state。

正确行为应该是：

> **Clarify before implementation.**

而不是自行选择其中一个数据库。

RQ3 因此回答的是：

> **Do I know enough to act, or should I ask?**

---

## RQ4: Requirement-to-Code Execution

### Research Question

> **Can the agent faithfully translate the reconstructed requirement state into a correct implementation in the current codebase?**

### What It Measures

前面三个 RQ 主要关注 requirement understanding。

但理解正确并不意味着最终代码一定正确。

Agent 可能：

- 正确找到了 requirement；
- 正确判断它仍然有效；
- 甚至在 reasoning 中明确提到了它；
- 但最终生成的代码仍然没有实现这一 requirement。

因此 ReqMemBench 的最后一步必须评价：

$$
G_P(t^{*-})
+
q_{t^*}
+
C_{t^{*-}}
\rightarrow
C_{t^{*+}}
$$

其中：

- $C_{t^{*-}}$：执行当前任务之前的代码；
- $C_{t^{*+}}$：Agent 完成任务之后的代码。

RQ4 关注的不只是当前 task 是否完成，还包括所有当前有效并与该 task 相关的历史 requirement 是否被真正落实。

评价可以通过：

- functional tests；
- requirement-specific tests；
- static checks；
- code inspection；
- execution behavior；

判断 implementation 是否与 Gold Requirement State 一致。

### Example

假设历史中存在一个 project-persistent requirement：

> “Logs must never contain raw PII.”

当前 task 要求新增 authentication logging。

Agent 可能在 reasoning 中正确指出：

> “PII should be masked.”

但如果最终代码仍然直接执行：

```python
logger.info(user.email)
```

那么 Requirement Understanding 可能是正确的，但 Requirement-to-Code Execution 仍然失败。

RQ4 因此回答的是：

> **Did the agent actually act on the correct requirement state?**

---

# 3. Unified Evaluation View

四个 RQ 可以统一表示为一个完整的 longitudinal coding pipeline：

$$
H_{<t^*}
+
C_{t^{*-}}
+
q_{t^*}
$$

↓

## RQ1 — Select

$$
H_{<t^*}
\rightarrow
H^{\mathrm{rel}}_{t^*}
$$

**Which historical requirements matter?**

↓

## RQ2 — Reconstruct

$$
H^{\mathrm{rel}}_{t^*}
\rightarrow
G_P(t^{*-})
$$

**What is currently valid?**

↓

## RQ3 — Decide

$$
G_P(t^{*-})
\rightarrow
\{\mathrm{Act},\mathrm{Clarify}\}
$$

**Is the available evidence sufficient?**

↓

## RQ4 — Execute

$$
G_P(t^{*-})
+
C_{t^{*-}}
+
q_{t^*}
\rightarrow
C_{t^{*+}}
$$

**Was the correct requirement state faithfully implemented?**

因此，ReqMemBench 的能力链最终可以概括为：

$$
\mathrm{Select}
\rightarrow
\mathrm{Reconstruct}
\rightarrow
\mathrm{Decide}
\rightarrow
\mathrm{Execute}
$$

这四个 RQ 共同回答 ReqMemBench 最核心的问题：

> **Can a coding agent enter an ongoing software project, understand how the client's requirements have evolved up to the current point, reconstruct what is actually required now, and make the correct development action?**

---

# 4. Diagnostic Value of the Four RQs

传统 Coding Benchmark 通常最终回答：

> **Did the agent solve the task?**

ReqMemBench 则进一步希望回答：

> **Why did the agent succeed or fail?**

通过四个 RQ，我们能够将 failure 分解为四种不同来源：

| Failure Stage | Diagnostic Question | Typical Failure |
|---|---|---|
| **RQ1 — Selection** | Did the agent retrieve the correct historical requirements? | 遗漏关键历史 requirement，或者受到无关历史信息干扰 |
| **RQ2 — Reconstruction** | Did the agent reconstruct their current state correctly? | 使用过期 requirement、错误扩大 scope、忽略 override、重新实现 removed requirement |
| **RQ3 — Decision** | Did the agent know whether it had enough evidence to act? | 在存在 unresolved ambiguity 时自行猜测，或者在已有明确历史规则时重复询问 |
| **RQ4 — Execution** | Did the agent faithfully implement the reconstructed state? | 理解正确，但代码没有真正满足 requirement |

因此，ReqMemBench 不仅提供一个最终的 functional correctness score，还能够区分：

$$
\mathrm{MemoryFailure}
\neq
\mathrm{StateReasoningFailure}
\neq
\mathrm{DecisionFailure}
\neq
\mathrm{ImplementationFailure}
$$

这使得 Benchmark 能够更加细粒度地评价长期软件项目中的 Coding Agent 能力，并将 **long-term memory evaluation** 与真正的 **software engineering action** 联系起来。

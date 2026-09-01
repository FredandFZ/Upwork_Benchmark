# Requirement Graph

# 1. Requirement Event Replay and State Transition

Stage 1 得到的是按照项目历史标注的一系列 **Requirement Events**。这些 Events 描述 Requirement 在不同时间点发生了什么变化，但 Event 本身并不直接表示某一时刻 Requirement 的完整状态。

Stage 2 首先需要按照时间顺序 replay 这些 Events，将离散的变化记录恢复为 Requirement 的连续 lifecycle：

```
Requirement Events
        ↓
Chronological Replay
        ↓
Requirement States
        ↓
Requirement State Graph
```

对于每一个 Requirement Atom，设其按时间排序后的 Events 为：

$$

E_r^{(1)}, E_r^{(2)}, \ldots, E_r^{(n)}

$$

每处理一个 Event，都会从前一个 Requirement State 推导出新的 State：

$$

S_r^{(k)} = T\left(S_r^{(k-1)}, E_r^{(k)}\right)

$$

其中：

- $S_r^{(k-1)}$ 表示 Event $E_r^{(k)}$ 发生之前的 Requirement State；
- $E_r^{(k)}$ 表示当前需要 replay 的 Requirement Event；
- $T$ 表示预先定义的 state transition rule；
- $S_r^{(k)}$ 表示该 Event 处理完成后的新 Requirement State。

因此，Requirement State Graph 并不是新的人工 annotation，而是 Stage 2 根据 Stage 1 Events 自动推导得到的结果。

Stage 2 不重新解释聊天文本，也不重新判断 Event 是否正确。它把通过 Stage 1 final validation 的 Event 数组视为 canonical input，并执行确定性的 schema validation、state transition 和 provenance 更新。

---

## 1.1 Replay Unit

**Requirement Atom 是 replay 的基本单位。**

每个 Requirement Atom 独立维护自己的 Event sequence 和 State sequence。例如：

```
REQ_SMALL_PRIZE

INTRODUCE
    ↓
MODIFY
    ↓
DEFER
    ↓
RESUME
```

系统分别 replay 每个 Requirement Atom，而不会直接对整个 Requirement Family 进行状态更新。

Requirement Family 只用于表示多个 Requirement 之间的语义关系，不作为独立 lifecycle unit。

---

## 1.2 Event Ordering

对于同一个 Requirement Atom，Stage 1 Final Assembly 已经把 Events 按原始项目历史和同消息 Event order 排好。Stage 2 **直接保留 Event 数组顺序**进行 replay：

```
Project Timeline
      ↓
Session Order
      ↓
Message Order
      ↓
Event Order
```

最终得到：

$$

E_r^{(1)} \rightarrow E_r^{(2)} \rightarrow \cdots \rightarrow E_r^{(n)}

$$

`event_id` 用于唯一标识和追踪 Event，例如：

```
REQ_SMALL_PRIZE_E001
REQ_SMALL_PRIZE_E002
REQ_SMALL_PRIZE_E003
```

`event_id` 本身不决定时间顺序；实际 replay 顺序以 Stage 1 输出数组为准。Stage 2 不按 `message_id` 重新排序，因为 message ID 可以是任意 scalar，同一消息中的多个 Events 也已有明确顺序。

`resolves_ambiguity_event_ids` 通过 Event ID 建立引用。人工删除、插入或重编号 Event 时，必须同步更新所有 resolution links，否则 Stage 2 会拒绝构图。

---

## 1.3 Requirement State

Requirement Event 描述的是一次**变化**，而 Requirement State 描述的是某一时间点上该 Requirement 的**完整有效状态**。

例如：

```
MODIFY
trigger:
previous target
→
every 50,000 sales
```

这里只说明一个 attribute 发生了变化。

Replay 后得到的 Requirement State 则需要同时保留该 Requirement 当前已经确定的其他信息，例如：

```json
{
  "requirement_id": "REQ_ETH_MINT",

  "attributes": {
    "payment_asset": "ETH",
    "expected_result": "NFT is minted to the user"
  },

  "scope": {
    "persistence": "PROJECT_PERSISTENT",
    "components": ["SMART_CONTRACT", "BACKEND"],
    "contexts": ["ETH_MINT"]
  },

  "lifecycle_status": "ACTIVE",

  "ambiguity": {
    "REQ_ETH_MINT_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
	    "description": "It is unclear whether ETH minting should continue using the current implementation after the newly reported conflict.",
      "source_event_id": "REQ_ETH_MINT_E003"
    }
  },

  "execution": {
    "status": "FAILED",
    "observed_behavior": "ETH was consumed but the NFT was not received.",
    "source_event_id": "REQ_ETH_MINT_E004"
  },

  "supporting_event_ids": [
    "REQ_ETH_MINT_E001",
    "REQ_ETH_MINT_E003",
    "REQ_ETH_MINT_E004"
  ]
}
```

Requirement State 主要包含以下几类信息。

### 1.3.1 Current Attributes

`attributes` 保存该 Requirement 在当前时刻已经确定的属性值。

例如：

```
trigger = every 50,000 sales
prize_amount = ...
winner_count = ...
```

当 MODIFY Event 只修改其中一个 attribute 时，其他未被修改的 attribute 应继续继承之前 State 中的值。

因此：

```
Previous State
trigger = previous target
amount  = 100
count   = 5

        ↓ MODIFY trigger

New State
trigger = every 50,000 sales
amount  = 100
count   = 5
```

Replay 采用的是 **incremental update**，而不是每发生一个 Event 就重新生成整个 Requirement。

`value_removals` 使用 attribute 名称数组表达当前 State 中不再成立的属性。Replay 顺序为：

```text
先应用 value_removals
        ↓
再应用 value_updates
```

同一 Event 不能同时删除和更新同一个 attribute。`INTRODUCE` 不能包含 `value_removals`。

如果可观察历史从中途开始、尚未形成完整 baseline，则第一次看到对未知 attribute 的 removal 仍可 replay：该 Event 建立“该属性当前不存在”的事实。显式 `INTRODUCE` 建立完整 baseline 后，再次删除不存在的 attribute 属于 consistency error。

---

### 1.3.2 Current Scope

`scope` 表示该 Requirement 当前适用的范围，包括 Stage 1 已经标注的：

```
persistence
components
contexts
```

如果后续 Event 修改了 scope，则只更新 Event 中明确发生变化的部分；没有发生变化的 scope 信息继续沿用之前 State。

---

### 1.3.3 Lifecycle Status

Requirement State 需要记录当前 lifecycle 状态。

Stage 2 使用以下主要状态：

```
ACTIVE
DEFERRED
REMOVED
```

其中：

- **ACTIVE**：Requirement 当前有效，应当被后续任务考虑；
- **DEFERRED**：Requirement 已经存在，但当前暂缓执行；
- **REMOVED**：Requirement 已被明确取消，不再属于当前有效 Requirement。

如果第一条可观察 Event 不是 `INTRODUCE`，Stage 2 不会删除该 Requirement，也不会跳过早期 Events。它从 incomplete observed baseline 开始：

```json
{
  "attributes": {},
  "scope": {
    "persistence": null,
    "components": null,
    "contexts": null
  },
  "lifecycle_status": null,
  "ambiguity": null,
  "execution": null
}
```

随后每个可观察 Event 仍生成 Node 和 Edge；未知字段保持空或 `null`，不能猜测。

每个 Requirement Graph 还记录初始化方式：

| `initialization_mode` | 条件 | 行为 |
| --- | --- | --- |
| `NO_EVENTS` | Requirement 没有 Events | 保留空 Graph，`nodes=[]`、`edges=[]` |
| `EXPLICIT_INTRODUCE` | 唯一 `INTRODUCE` 位于第一条 Event | 从明确 baseline 开始 replay |
| `OBSERVED_HISTORY` | 没有 `INTRODUCE`，或唯一 `INTRODUCE` 出现在后面 | 保留 `INTRODUCE` 之前的全部可观察历史 |

`has_explicit_introduce` 单独记录 Event sequence 中是否存在 `INTRODUCE`。任何 Requirement 都不会因为缺少 `INTRODUCE` 或 Events 为空而从 Project Graph 中删除。

---

### 1.3.4 Ambiguity State

AMBIGUOUS 与 ACTIVE、DEFERRED、REMOVED 不属于同一类状态。

例如，一个 Requirement 可能同时满足：

```
lifecycle_status = ACTIVE
open_ambiguities = {
  REQ_EXAMPLE_E003: OPEN
}
```

这表示：

> Requirement 本身仍然存在，但其某些信息目前无法安全确定，需要进一步 clarification。
> 

因此，ambiguity 应作为 Requirement State 中独立的信息保存，而不应该简单地把整个 Requirement 的 lifecycle status 改成 `AMBIGUOUS`。

同一 Requirement 可以同时存在多个 OPEN ambiguities。Stage 2 内部使用：

```text
open_ambiguities: dict[event_id, ambiguity_state]
```

Node 中的 `ambiguity` 为 `null` 或按 `AMBIGUOUS` Event ID keyed 的对象。只有后续 Event 的 `resolves_ambiguity_event_ids` 显式引用某个 key 时，才删除这一条；其他 OPEN ambiguities 保持不变。

这一设计对于后续 RQ4 的 **Memory-or-Clarify Decision** 非常重要。

---

### 1.3.5 Execution State

`execution` 表示当前项目历史中关于该 Requirement **实际实现结果的最新证据状态**。

Execution State 与 Requirement Lifecycle 相互独立。

例如：

```
Lifecycle = ACTIVE
Execution = FAILED
```

表示：

> Requirement 本身仍然有效，但当前 implementation 没有正确满足该 Requirement。
> 

同样：

```
Lifecycle = ACTIVE
Execution = VERIFIED_WORKING
```

表示：

> Requirement 当前仍然有效，并且已经有真实运行证据证明当前 implementation 满足该 Requirement。
> 

Execution State 主要包括：

```
UNKNOWN
CLAIMED_WORKING
FAILED
VERIFIED_WORKING
```

其中：

- `UNKNOWN`：当前没有明确 implementation evidence；
- `CLAIMED_WORKING`：有人声称已经实现或修复，但没有真实 runtime verification；
- `FAILED`：实际运行或测试证明 implementation 没有满足 Requirement；
- `VERIFIED_WORKING`：实际运行或测试确认 implementation 已满足 Requirement。

`MODIFY` 表示 Requirement 已进入新的语义版本，因此会把旧版本的 execution evidence 重置为 `null`。如果可观察历史先出现其他 Events、之后才出现正式 `INTRODUCE`，该 `INTRODUCE` 同样清除之前 incomplete baseline 上的 execution evidence。

`DEFER`、`RESUME`、`REMOVE` 和 `AMBIGUOUS` 保留当前 execution；三个 Execution Event 则用最新 evidence 覆盖当前 execution。完整历史不会丢失，因为旧 execution 仍保存在更早的 Graph Nodes 中。

因此：

```
Requirement Lifecycle
        ≠
Execution State
```

例如 `RUNTIME_FAILURE` 不会将：

```
ACTIVE → REMOVED
```

而只会：

```
Execution:
UNKNOWN → FAILED
```

---

### 1.3.6 Supporting_Event

每一个 Requirement State 都需要能够追踪到：

> **当前 State 中的 Value、Scope、Lifecycle、Ambiguity 和 Execution 是由哪些 Requirement Events 建立的。**
> 

因此，Stage 2 在 replay Requirement Events 时，为每一个 State 自动维护：

```
{
  "supporting_event_ids": [
    "REQ_SMALL_PRIZE_E001",
    "REQ_SMALL_PRIZE_E003",
    "REQ_SMALL_PRIZE_E005"
  ]
}
```

`supporting_event_ids` 保存的是：

> **仍然直接支持当前 Requirement State 的最小 Event 集合。**
> 

它不是该 Requirement 从项目开始到当前时间点发生过的全部 Events。

当前实现将以下 source Events 合并、去重并按原 Event 顺序排列：

- 每个仍存在 attribute 的最近 `value_updates` source；
- 每个已删除 attribute 的最近 `value_removals` source；
- 每个非空 scope dimension 的最近 source；
- 每条仍然 OPEN ambiguity 自身的 Event ID；
- 当前 lifecycle 的最近 source；
- 当前 execution 的最近 source。

已被后续 update supersede 的 attribute/scope source、已关闭的 ambiguity，以及被 `MODIFY` 清空的旧 execution source 不再进入当前 Node 的 `supporting_event_ids`。

Requirement 的完整 Event history 已经由 Requirement State Graph 保存，因此不需要在每个 State 中重复保存。

整体关系为：

```
Current Requirement State
        ↓
supporting_event_ids
        ↓
Requirement Events
        ↓
source_message
        ↓
Original Project History
```

因此，任意一个 Requirement State 都可以最终追溯回产生该 State 的原始项目消息。

---

## 1.4 State Transition Rules

Requirement replay 的核心是定义不同 Event 如何改变 Requirement State。

统一表示为：

$$

S_r^{(k)} = T\left(S_r^{(k-1)}, E_r^{(k)}\right)

$$

Stage 1 中不同 Event Type 对 State 的影响如下。

在 replay 前，Stage 2 先验证：

- Requirement IDs 和全项目 Event IDs 唯一；
- Event type、payload 和 execution status 符合 canonical schema；
- `value_updates`、`value_removals`、`scope_updates` 的类型与组合合法；
- `resolves_ambiguity_event_ids` 为 `null` 或非空、无重复的字符串数组；
- resolution target 存在于同一 Requirement，位于 resolver 之前且类型为 `AMBIGUOUS`；
- 同一个 ambiguity 没有被重复解决；
- resolver 类型属于 `INTRODUCE`、`MODIFY`、`DEFER`、`RESUME`、`REMOVE`；
- 一个 Requirement 最多出现一次 `INTRODUCE`；
- `REMOVE` 之后不再出现任何 Event。

任一条件不满足都会抛出 consistency error，而不是猜测修复。

合法 resolver Event 在完成自己的 Value、Scope 或 Lifecycle transition 后，统一执行：

```python
for ambiguity_id in event.resolves_ambiguity_event_ids or []:
    close_exactly_this_open_ambiguity(ambiguity_id)
```

字段为 `null` 时，不关闭任何 ambiguity。Stage 2 不使用 Event type、ambiguity dimension、时间接近度或“最近一个 ambiguity”等 heuristic fallback。

### 1.4.1 INTRODUCE

INTRODUCE 表示一个 Requirement 首次进入项目。

```
Before
Requirement does not exist

        ↓ INTRODUCE

After
Requirement exists
lifecycle_status = ACTIVE
```

INTRODUCE 中记录的 attributes 和 scope 构成该 Requirement 的初始 State。

例如：

```
INTRODUCE

trigger = previous target
amount = 100
```

如果 `INTRODUCE` 出现在已有 observed-history Nodes 之后，它表示首次建立正式 baseline：Lifecycle 变为 `ACTIVE`、baseline 标记为完整，并清除旧 incomplete baseline 的 execution evidence。此前 Nodes 和 Edges 仍保留，OPEN ambiguities 仍然只通过显式 resolution links 关闭。

得到：

```
ACTIVE

trigger = previous target
amount = 100
```

---

### 1.4.2 MODIFY

MODIFY 表示已经存在的 Requirement 中，一个或多个明确属性发生变化。

```
Before
ACTIVE
trigger = previous target
amount = 100

        ↓ MODIFY

trigger:
previous target
→
every 50,000 sales

        ↓

After
ACTIVE
trigger = every 50,000 sales
amount = 100
```

MODIFY 采用 **patch update**：

> 只更新 Event 中明确列出的变化，其他 Requirement information 保持不变。
> 

如果 MODIFY 同时包含 scope change，则对应 scope 字段按照相同规则更新。

`MODIFY` 还会把 execution 重置为 `null`，因为此前的 claim、failure 或 verification 只证明旧 Requirement 版本。它可以通过 `resolves_ambiguity_event_ids` 关闭明确解决的 ambiguities；没有被引用的 ambiguity 继续 OPEN。

---

### 1.4.3 DEFER

DEFER 表示 Requirement 当前暂缓执行，但 Requirement 本身没有被删除。

```
Before
ACTIVE

        ↓ DEFER

After
DEFERRED
```

DEFER 不删除已有 attributes 和 scope。

因此：

```
attributes = preserved
scope      = preserved
status     = DEFERRED
```

这样在后续 Requirement RESUME 时，可以继续恢复之前已经确定的 Requirement State。

`DEFER` 保留当前 execution。只有携带显式 resolution links 时，它才关闭对应的 lifecycle ambiguity。

---

### 1.4.4 RESUME

RESUME 表示之前暂缓或等待 clarification 的 Requirement 可以重新继续使用。

最典型的情况是：

```
DEFERRED
    ↓ RESUME
ACTIVE
```

RESUME 本身不会重新创建 Requirement，也不会自动修改已经确定的 attributes。

因此：

```
Before

status = DEFERRED
trigger = every 50,000 sales

        ↓ RESUME

After

status = ACTIVE
trigger = every 50,000 sales
```

`RESUME` 保留当前 execution。只有 `RESUME.resolves_ambiguity_event_ids` 明确列出此前 OPEN ambiguity 时，才关闭这些具体记录；没有链接的 `RESUME` 只更新 lifecycle 为 `ACTIVE`。

---

### 1.4.5 REMOVE

REMOVE 表示 Requirement 被明确取消。

```
ACTIVE
   ↓ REMOVE
REMOVED
```

或：

```
DEFERRED
   ↓ REMOVE
REMOVED
```

进入 REMOVED 状态后，该 Requirement 不再属于当前有效 Requirement 集合。

但是，为了保留 lifecycle traceability，之前已经确定的 attributes、scope 和 evidence 不需要从 State Graph 中物理删除。

例如：

```json
{
  "requirement_id": "REQ_BIG_BLOCK",
  "lifecycle_status": "REMOVED",
  "last_known_attributes": {
    "...": "..."
  },
  "removed_by_event": "REQ_BIG_BLOCK_4"
}
```

因此：

> **REMOVED means no longer valid, not erased from history.**
> 

`REMOVE` 保留当前 execution，并且只关闭 `resolves_ambiguity_event_ids` 中明确列出的 ambiguity。任何后续 Event 都属于非法 transition，因为当前实现不支持在 `REMOVED` 后重新引入或恢复同一个 Requirement。

这一点对于后续 RQ3 判断历史 Requirement 是否已经失效非常重要。

---

### 1.4.6 AMBIGUOUS

`AMBIGUOUS` 表示：

> **当前历史中出现了无法根据已有信息安全解决的 Requirement uncertainty，因此不能直接推导出新的 confirmed Value、Scope 或 Lifecycle。**
> 

它与 `MODIFY` 最大的区别是：

> **`MODIFY` 表示已经获得明确的新 Requirement 信息，而 `AMBIGUOUS` 表示当前证据不足以安全确定 Requirement 应该如何更新。**
> 

因此，`AMBIGUOUS` Event **不会覆盖此前已经确认的 Requirement State，也不会直接改变 Requirement Lifecycle**。

例如，当前已经确认：

```
Lifecycle = ACTIVE
trigger = every 50,000 sales
open_ambiguities = {}
```

随后出现新的消息，但其含义无法唯一确定，例如可能表示：

```
every 50,000 sales
```

也可能表示：

```
every 50,000 tokens
```

此时不能通过推测产生：

```
trigger = every 50,000 tokens
```

正确的 Replay 应为：

```
ACTIVE
trigger = every 50,000 sales
open_ambiguities = {}

        ↓ AMBIGUOUS

ACTIVE
trigger = every 50,000 sales

open_ambiguities:
    REQ_SMALL_PRIZE_E004:
        status = OPEN
        dimension = VALUE
        description = "The new trigger condition cannot be uniquely determined from the current history."
        source_event_id = REQ_SMALL_PRIZE_E004
```

也就是说，`AMBIGUOUS` 发生后：

```
Value       = preserve last confirmed state
Scope       = preserve last confirmed state
Lifecycle   = preserve last confirmed state
Ambiguity   → OPEN
Execution   = unchanged
```

Stage 2 中生成的 Ambiguity State 结构为：

```json
{
  "ambiguity": {
    "REQ_SMALL_PRIZE_E004": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The new trigger condition cannot be uniquely determined from the current history.",
      "source_event_id": "REQ_SMALL_PRIZE_E004"
    }
  }
}
```

其中：

- `status = OPEN` 表示当前 ambiguity 尚未解决；
- `dimension` 直接继承 Stage 1 `AMBIGUOUS` Event，可取 `VALUE`、`SCOPE` 或 `LIFECYCLE`；
- `description` 记录具体的不确定性；
- `source_event_id` 指向产生当前 ambiguity 的 Requirement Event。

Stage 2 不根据后续 Event 的类型自动关闭 ambiguity。例如：

```text
E004 AMBIGUOUS
  → open_ambiguities[E004] = OPEN

E005 MODIFY unrelated display copy
  resolves_ambiguity_event_ids = null
  → E004 继续 OPEN

E006 MODIFY exact uncertain trigger
  resolves_ambiguity_event_ids = ["REQ_SMALL_PRIZE_E004"]
  → 只在 E006 关闭 E004
```

一个 resolver 可以关闭多个明确列出的 ambiguities；每个 ambiguity 最多关闭一次。Execution Events 和 `AMBIGUOUS` Events 不能携带 resolution links。

因此，Requirement 可以同时处于：

```
Lifecycle = ACTIVE
open_ambiguities is not empty
```

这表示：

> Requirement 最后一次确认的状态仍然有效，但当前存在新的 unresolved uncertainty，使 Agent 不能在受影响的任务中安全地自行推断下一步。
> 

当该 unresolved ambiguity 与当前 evaluation task 相关时，后续 RQ4 可以进一步派生：

```
Agent Action = CLARIFY
```

---

### 1.4.7 IMPLEMENTATION_CLAIM

`IMPLEMENTATION_CLAIM` 更新 Requirement 的 Execution State，但不改变 Value、Scope、Lifecycle 或 Ambiguity。

例如当前：

```
Lifecycle = ACTIVE
Execution = FAILED
```

Freelancer 说：

> Fixed. ETH minting is working now.
> 

Replay：

```
ACTIVE
Execution = FAILED

        ↓ IMPLEMENTATION_CLAIM

ACTIVE
Execution = CLAIMED_WORKING
```

这里：

```
Lifecycle = ACTIVE → ACTIVE
```

只有 Execution State 发生变化。

同时需要保留：

```
observed_behavior =
"Freelancer reports that ETH minting has been fixed."
```

但 `CLAIMED_WORKING` **不能视为 runtime verification**。

---

### 1.4.8 RUNTIME_FAILURE

`RUNTIME_FAILURE` 表示真实运行或测试发现当前 implementation 没有满足 Requirement。

例如：

```
ACTIVE
Execution = CLAIMED_WORKING

        ↓ RUNTIME_FAILURE

ACTIVE
Execution = FAILED
```

例如 Client 测试：

> I paid with ETH. The ETH was taken but I didn't receive the NFT.
> 

Replay 后：

```
{
  "execution": {
    "status": "FAILED",
    "observed_behavior": "ETH was consumed but the NFT was not received.",
    "source_event_id": "REQ_ETH_MINT_E005"
  }
}
```

这里特别需要强调：

> `RUNTIME_FAILURE` 更新的是 Execution State，而不是 Requirement Lifecycle。
> 

因此：

```
Lifecycle = ACTIVE
Execution = FAILED
```

是完全合法而且很重要的 Requirement State。

---

### 1.4.9 RUNTIME_VERIFICATION

`RUNTIME_VERIFICATION` 表示真实运行或测试确认当前 implementation 已经满足 Requirement。

例如：

```
ACTIVE
Execution = CLAIMED_WORKING

        ↓ RUNTIME_VERIFICATION

ACTIVE
Execution = VERIFIED_WORKING
```

Client：

> I tried it again. ETH payment works and I received the NFT this time.
> 

Replay 后：

```
{
  "execution": {
    "status": "VERIFIED_WORKING",
    "observed_behavior": "The client successfully paid with ETH and received the NFT.",
    "source_event_id": "REQ_ETH_MINT_E007"
  }
}
```

完整 Execution trajectory 可以形成：

```
UNKNOWN
   ↓ RUNTIME_FAILURE
FAILED
   ↓ IMPLEMENTATION_CLAIM
CLAIMED_WORKING
   ↓ RUNTIME_VERIFICATION
VERIFIED_WORKING
```

而与此同时 Lifecycle 可能始终保持：

```
ACTIVE
```

### 1.4.10 Transition Summary

不同 Event 对 Requirement State 的主要影响可以总结为：

| Event | Value | Scope | Lifecycle | Ambiguity | Execution |
| --- | --- | --- | --- | --- | --- |
| `INTRODUCE` | 初始化/补全 | 可初始化 | → `ACTIVE` | 仅关闭显式链接的 IDs | 若此前已有 observed state，则 → `null` |
| `MODIFY` | 更新或删除 | 可更新 | 保持 | 仅关闭显式链接的 IDs | → `null` |
| `DEFER` | 保留 | 保留 | → `DEFERRED` | 仅关闭显式链接的 IDs | 保留 |
| `RESUME` | 保留 | 保留 | → `ACTIVE` | 仅关闭显式链接的 IDs | 保留 |
| `REMOVE` | 保留历史值 | 保留历史值 | → `REMOVED` | 仅关闭显式链接的 IDs | 保留历史 |
| `AMBIGUOUS` | 不猜测 | 不猜测 | 保持 | 以自身 Event ID 新增一条 `OPEN` | 保持 |
| `IMPLEMENTATION_CLAIM` | 保持 | 保持 | 保持 | 不关闭 | → `CLAIMED_WORKING` |
| `RUNTIME_FAILURE` | 保持 | 保持 | 保持 | 不关闭 | → `FAILED` |
| `RUNTIME_VERIFICATION` | 保持 | 保持 | 保持 | 不关闭 | → `VERIFIED_WORKING` |

这里的“显式链接”专指 `resolves_ambiguity_event_ids`。字段为 `null` 时，任何 Event 都不能隐式关闭 ambiguity。

如果 Event sequence 出现无法按照这些规则解释的非法 transition，Stage 2 不应自行猜测修复，而应将其标记为 consistency error，并在后续 Quality Control 阶段检查。

# 2. Requirement State Graph and Gold State

完成 Requirement Event Replay 后，Stage 2 将一个 Project 中所有 Requirement Atoms 的 Event sequences 转换为统一的 **Project Requirement State Graph**。

在逻辑上，每个 Requirement Atom 拥有自己独立的 Requirement-level State Graph；但在实际数据存储中，这些 Requirement-level Graphs 不分别保存为独立文件，而是统一组织在该 Project 的：

```
requirement_state_graph.json
```

Requirement State Graph 用于保存整个 Project 中 Requirements 的历史状态演化过程，而 **Gold State** 则表示从该 Graph 中在某个特定 target time $t^*$ 上取得的 Requirement State snapshot。

二者的关系可以概括为：

```
Project Annotation
        ↓
Requirement Events
        ↓
Requirement-level Replay
        ↓
Project Requirement State Graph
        ↓
Select target time t*
        ↓
Project Gold State G_P(t*)
```

核心区别是：

> **State Graph preserves the complete historical trajectory of all Requirements in a Project; Gold State represents the Project snapshot at a specific target time.**
> 

因此，一个 Project 的 Requirement State Graph 只需要根据 Stage 1 Annotation 构建一次。之后可以从同一个 Graph 中选择不同的 target time $t^*$，得到多个 Gold States，并进一步构建多个 evaluation instances。

---

## 2.1 Requirement State Graph

对于一个 Requirement Atom $r$，设其按照项目时间顺序排列后的 Events 为：

$$

E_r^{(1)}, E_r^{(2)}, \ldots, E_r^{(n)}

$$

从初始可观察状态开始，依次 replay 每一个 Event：

$$

S_r^{(k)} =

T\left(

S_r^{(k-1)},

E_r^{(k)}

\right)

$$

其中：

- $E_r^{(k)}$ 表示 Requirement $r$ 的第 $k$ 个 Event；
- $S_r^{(k-1)}$ 表示该 Event 发生之前的 Requirement State；
- $T$ 表示第 1.4 节定义的 State Transition Rules；
- $S_r^{(k)}$ 表示处理该 Event 后得到的新 Requirement State。

最终形成：

$$

S_r^{(1)}

\rightarrow

S_r^{(2)}

\rightarrow

\cdots

\rightarrow

S_r^{(n)}

$$

每一个有效 Stage 1 Event 都会产生一个新的 State Node 和一条 Edge。即使 Event 不改变 Value，例如只更新 execution、打开/关闭 ambiguity 或更新 lifecycle source，它仍然形成可追踪的 transition。

因此：

```
State Node
     ↓
describes
"What is the Requirement state now?"

Event Edge
     ↓
describes
"What caused the state to change?"
```

例如：

```
REQ_ETH_MINT

S1
Lifecycle = ACTIVE
Execution = null

        ↓ RUNTIME_FAILURE

S2
Lifecycle = ACTIVE
Execution = FAILED

        ↓ IMPLEMENTATION_CLAIM

S3
Lifecycle = ACTIVE
Execution = CLAIMED_WORKING

        ↓ RUNTIME_VERIFICATION

S4
Lifecycle = ACTIVE
Execution = VERIFIED_WORKING
```

这里 Requirement Lifecycle 始终保持 `ACTIVE`，但 Execution State 不断变化。

因此：

```
S1 ≠ S2 ≠ S3 ≠ S4
```

Requirement State Graph 并不是单纯的 Lifecycle Graph。

一个完整的 Requirement State Node 同时包含：

```
Requirement State
│
├── Attributes
├── Scope
├── Lifecycle
├── Ambiguity
└── Execution
```

任何一个维度发生变化都会形成新的 State Node；当前实现按每个有效 Event 生成 Node，不会为了压缩 Graph 而合并相邻 States。

---

### 2.1.1 Node

Graph 中的每个 Node 表示处理某个 Event 后得到的一个完整 **Requirement State snapshot**。

Requirement State 的主要结构为：

```
Requirement State
│
├── state_id
├── attributes
├── scope
├── lifecycle_status
├── ambiguity
├── execution
└── supporting_event_ids
```

例如：

```json
{
  "state_id": "REQ_ETH_MINT_S002",

  "attributes": {
    "payment_asset": "ETH",
    "expected_result": "NFT is minted to the user"
  },

  "scope": {
    "persistence": "PROJECT_PERSISTENT",
    "components": ["SMART_CONTRACT", "BACKEND"],
    "contexts": ["ETH_MINT"]
  },

  "lifecycle_status": "ACTIVE",

  "ambiguity": null,

  "execution": {
    "status": "FAILED",
    "observed_behavior": "ETH was consumed but the NFT was not received.",
    "source_event_id": "REQ_ETH_MINT_E004"
  },

  "supporting_event_ids": [
    "REQ_ETH_MINT_E001",
    "REQ_ETH_MINT_E004"
  ]
}
```

`state_id` 在 Requirement 内按照 replay 顺序自动生成：

```
REQ_ETH_MINT_S001
REQ_ETH_MINT_S002
REQ_ETH_MINT_S003
...
```

由于 `requirement_id` 已经包含在 `state_id` 中，因此这些 Node IDs 在整个 Project Graph 中也可以保持唯一。

---

### 2.1.2 Edge

Graph 中的 Edge 表示导致两个 State Nodes 之间发生 transition 的 Requirement Event。

标准关系为：

```
Previous State
      │
      │ Event
      ▼
New State
```

例如：

```
REQ_ETH_MINT_S002
        │
        │ IMPLEMENTATION_CLAIM
        │ REQ_ETH_MINT_E005
        ▼
REQ_ETH_MINT_S003
```

Edge 不需要重新复制完整的 Event Annotation。

完整 Event 信息仍然保存在 Stage 1 Project Annotation 中，State Graph 只通过 `event_id` 建立关联。

例如：

```json
{
  "from_state_id": "REQ_SMALL_PRIZE_S001",
  "to_state_id": "REQ_SMALL_PRIZE_S002",
  "event_id": "REQ_SMALL_PRIZE_E002",
  "event_type": "MODIFY",
  "source_message_id": 158,
  "value_removals": null
}
```

Edge 固定保留 `value_removals`，便于后续 Gold 构建和审计直接识别 attribute deletion；其余完整 Event payload 仍通过 `event_id` 回到 Stage 1 Annotation 查询。

因此：

```
State Graph Edge
        ↓ event_id
Stage 1 Requirement Event
        ↓ source_message
Original Project History
```

可以形成完整的 provenance chain。

---

## 2.2 Requirement-level State Graph

每一个 Requirement Atom 都独立进行 replay，并在逻辑上形成一个 **Requirement-level State Graph**。

当前 Requirement-level Graph 的固定结构为：

```json
{
  "graph_id": "REQ_EXAMPLE_GRAPH",
  "requirement_id": "REQ_EXAMPLE",
  "title": "Example Requirement",
  "family_id": null,
  "initialization_mode": "OBSERVED_HISTORY",
  "has_explicit_introduce": false,
  "nodes": [],
  "edges": []
}
```

其中 `title` 和 `family_id` 直接继承 Stage 1；`initialization_mode` 与 `has_explicit_introduce` 描述可观察历史的起点，不能用来过滤 Requirement。

例如：

```
Project 42204309
│
├── REQ_SMALL_PRIZE
│      S1 → S2 → S3 → S4
│
├── REQ_BIG_BLOCK
│      S1 → S2 → S3
│
├── REQ_ETH_MINT
│      S1 → S2 → S3 → S4 → S5
│
└── REQ_MAURITIUS_GEOBLOCK
       S1 → S2
```

Requirement-level Graph 是：

> **Requirement replay 和 state transition 的基本逻辑单位。**
> 

不同 Requirements 之间不共享 State Nodes，一个 Requirement 的 Event 也不会直接修改另一个 Requirement 的 State。

例如：

```
PRIZE_MECHANICS
│
├── REQ_SMALL_PRIZE
│      └── independent state trajectory
│
└── REQ_BIG_BLOCK
       └── independent state trajectory
```

即使两个 Requirements 属于同一个 Family，也分别维护独立的 state trajectory。

但是：

> **Requirement-level Graph 不是独立的文件存储单位。**
> 

所有 Requirement-level Graphs 最终统一嵌入 Project 的 `requirement_state_graph.json`。

---

### 2.2.1 Graph Construction Rules

对于 Project 中的每一个 Requirement Atom，Requirement-level Graph 按照以下规则自动构建：

1. 读取该 Requirement 的全部 Stage 1 Events；
2. 保留 Stage 1 Final Assembly 已确定的 Event 数组顺序，不按 message ID 重新排序；
3. 验证 Event payload、全项目 Event ID 唯一性和全部 ambiguity resolution references；
4. 根据 Event 分布确定 `NO_EVENTS`、`EXPLICIT_INTRODUCE` 或 `OBSERVED_HISTORY` 初始化模式；
5. 根据第 1.4 节定义的 State Transition Rules 顺序 replay；
6. 每处理一个有效 Event，生成一个新的 State Node；
7. 使用该 Event 建立前一个 State Node 与新 State Node 之间的 Edge；
8. 重复以上步骤，直到该 Requirement 的全部 Events replay 完成；
9. 即使 Requirement 没有 Events 或没有 `INTRODUCE`，也将其 Graph 加入当前 Project 的 `requirement_state_graph.json`。

例如：

```
INTRODUCE
    ↓
S1

S1
    │ MODIFY
    ↓
S2

S2
    │ AMBIGUOUS
    ↓
S3

S3
    │ MODIFY（无关变化，resolution IDs = null）
    ↓
S4

S4
    │ MODIFY（显式 resolves S3 对应的 AMBIGUOUS Event）
    ↓
S5

S5
    │ RUNTIME_FAILURE
    ↓
S6
```

因此，Definition、Lifecycle、Uncertainty 和 Execution Events 都属于同一个 Requirement State Graph。

如果同一个 `source_message` 对同一 Requirement 确实产生多个语义独立的 ordered Events，例如先修改配置、再明确暂缓 Requirement：

```
MODIFY
   ↓
DEFER
```

则按照 Stage 1 中确定的 Event order 依次 replay，并分别形成对应的 State transition。

如果同一消息中的 `MODIFY` 已经通过 `resolves_ambiguity_event_ids` 解决 ambiguity，则不需要再生成表达同一语义的 `RESUME`；这种冗余 Event 应在 Stage 1 修正。

Graph Construction 不重新判断 Event 是否正确，也不重新解释原始消息。

> **Stage 1 determines the Events; Stage 2 deterministically replays them.**
> 

如果可观察历史中 Requirement 的第一个 Event 并不是 `INTRODUCE`，Stage 2 不应人工补造不存在的历史 State，也不能丢弃该 Requirement 或 `INTRODUCE` 之前的 Events。

系统从 incomplete observed baseline 开始构建第一个可确定 State；无法恢复的字段保持空或 `null`。后续唯一的 `INTRODUCE` 是正式 baseline transition，不是删除早期 Nodes 的理由。

进入 `REMOVED` 后出现任何后续 Event、出现第二个 `INTRODUCE`、resolution link 指向未来/其他 Requirement/非 `AMBIGUOUS` Event，均直接报告 consistency error。

---

## 2.3 Project-level Requirement State Graph

虽然 replay 是在 Requirement level 独立完成的，但 **Project 是最终 State Graph 的实际存储单位**。

对于一个 Project $P$，其 Requirement State Graph 可以理解为该 Project 中所有 Requirement-level Graphs 的集合：

```
Project Requirement State Graph
│
├── Requirement Graph 1
│      ├── Nodes
│      └── Edges
│
├── Requirement Graph 2
│      ├── Nodes
│      └── Edges
│
├── Requirement Graph 3
│      ├── Nodes
│      └── Edges
│
└── ...
```

例如：

```
42204309 Requirement State Graph
│
├── REQ_SMALL_PRIZE
│      S1 → S2 → S3 → S4
│
├── REQ_BIG_BLOCK
│      S1 → S2 → S3
│
├── REQ_ETH_MINT
│      S1 → S2 → S3 → S4
│
└── REQ_MAURITIUS_GEOBLOCK
       S1 → S2
```

这里的 Project-level Graph 是一个 **container / index of Requirement subgraphs**。

它不会创建额外的：

```
PROJECT_STATE
```

也不会把多个 Requirement 的 States 合并为一个共同 lifecycle。

因此：

> **Project Graph aggregates Requirement-level state trajectories; it does not merge Requirement states.**
> 

Requirement Family 同样只作为 metadata 保留。

例如：

```
PRIZE_MECHANICS
│
├── REQ_SMALL_PRIZE
└── REQ_BIG_BLOCK
```

不会额外生成：

```
PRIZE_MECHANICS_GRAPH
```

---

每个 Project 最终生成一个：

```
requirement_state_graph.json
```

如：

```json
{
  "project_id": "42204309",
  "project_title": "Project Rebuild MVP – Base NFT + Referral Engine + Fiat On-Ramp",

  "requirement_graphs": [
    {
      "graph_id": "REQ_SMALL_PRIZE_GRAPH",
      "requirement_id": "REQ_SMALL_PRIZE",
      "title": "Small Prize Mechanism",
      "family_id": "PRIZE_MECHANICS",
      "initialization_mode": "EXPLICIT_INTRODUCE",
      "has_explicit_introduce": true,

      "nodes": [
        {
          "state_id": "REQ_SMALL_PRIZE_S001",

          "attributes": {
            "prize_amount_per_winner": "$500",
            "winner_count": 5
          },

          "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["SMART_CONTRACT", "BACKEND"],
            "contexts": ["PRIZE_SYSTEM"]
          },

          "lifecycle_status": "ACTIVE",

          "ambiguity": null,
          "execution": null,

          "supporting_event_ids": [
            "REQ_SMALL_PRIZE_E001"
          ]
        },

        {
          "state_id": "REQ_SMALL_PRIZE_S002",

          "attributes": {
            "prize_amount_per_winner": "$500",
            "winner_count": 1,
            "draw_condition": "every 100 sales"
          },

          "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["SMART_CONTRACT", "BACKEND"],
            "contexts": ["PRIZE_SYSTEM"]
          },

          "lifecycle_status": "ACTIVE",

          "ambiguity": null,
          "execution": null,

          "supporting_event_ids": [
            "REQ_SMALL_PRIZE_E001",
            "REQ_SMALL_PRIZE_E002"
          ]
        }
      ],

      "edges": [
        {
          "from_state_id": null,
          "to_state_id": "REQ_SMALL_PRIZE_S001",
          "event_id": "REQ_SMALL_PRIZE_E001",
          "event_type": "INTRODUCE",
          "source_message_id": 8,
          "value_removals": null
        },

        {
          "from_state_id": "REQ_SMALL_PRIZE_S001",
          "to_state_id": "REQ_SMALL_PRIZE_S002",
          "event_id": "REQ_SMALL_PRIZE_E002",
          "event_type": "MODIFY",
          "source_message_id": 158,
          "value_removals": null
        }
      ]
    },

    {
      "graph_id": "REQ_BIG_BLOCK_GRAPH",
      "requirement_id": "REQ_BIG_BLOCK",
      "title": "Big Block Mechanism",
      "family_id": "PRIZE_MECHANICS",
      "initialization_mode": "EXPLICIT_INTRODUCE",
      "has_explicit_introduce": true,

      "nodes": [
        {
          "state_id": "REQ_BIG_BLOCK_S001",

          "attributes": {
            "prize_type": "Big Block"
          },

          "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["SMART_CONTRACT"],
            "contexts": ["PRIZE_SYSTEM"]
          },

          "lifecycle_status": "ACTIVE",

          "ambiguity": null,
          "execution": null,

          "supporting_event_ids": [
            "REQ_BIG_BLOCK_E001"
          ]
        },

        {
          "state_id": "REQ_BIG_BLOCK_S002",

          "attributes": {
            "prize_type": "Big Block"
          },

          "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["SMART_CONTRACT"],
            "contexts": ["PRIZE_SYSTEM"]
          },

          "lifecycle_status": "REMOVED",

          "ambiguity": null,
          "execution": null,

          "supporting_event_ids": [
            "REQ_BIG_BLOCK_E001",
            "REQ_BIG_BLOCK_E002"
          ]
        }
      ],

      "edges": [
        {
          "from_state_id": null,
          "to_state_id": "REQ_BIG_BLOCK_S001",
          "event_id": "REQ_BIG_BLOCK_E001",
          "event_type": "INTRODUCE",
          "source_message_id": 20,
          "value_removals": null
        },

        {
          "from_state_id": "REQ_BIG_BLOCK_S001",
          "to_state_id": "REQ_BIG_BLOCK_S002",
          "event_id": "REQ_BIG_BLOCK_E002",
          "event_type": "REMOVE",
          "source_message_id": 195,
          "value_removals": null
        }
      ]
    }
  ]
}
```

---

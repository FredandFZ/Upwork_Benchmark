# ReqMemBench_Annotation_Guideline_v0.4

## Longitudinal Requirement Lifecycle Annotation for Coding Agents

> **Case Study:** Project 42204309 — *Project Rebuild MVP – Base NFT + Referral Engine + Fiat On-Ramp*
> 
> 
> **Version:**  Final
> 

---

# 1. 标注流程与目标

**ReqMemBench 的整体流程分为两个阶段。**

**第一阶段是对原始项目历史进行基本标注，恢复项目中 Requirement 的长期演化过程：**

```
Raw Project History
        ↓
Timeline / Sessions
        ↓
Requirement Families
        ↓
Independent Requirements
        ↓
Requirement Events
        ↓
Value / Scope / Lifecycle / Execution Evolution
```

这一阶段的目标是从完整项目对话中识别：

- 项目的时间与 Session 结构；
- 主要的 Requirement Families；
- 可以独立演化的 Requirements；
- 每个 Requirement 在历史中的关键 Events；
- Requirement 的 Value、Scope、Lifecycle 和 Execution 如何随时间变化。

**第二阶段不再进行新的人工标注，而是基于第一阶段得到的 Requirement Events 进行自动 replay 和 benchmark 构建：**

```
Project Annotation
        ↓
Requirement State Graph
        ↓
Derived Current Gold State
        ↓
RQ1–RQ5 Evaluation Instances
```

因此，ReqMemBench 的核心思想不是对单条聊天消息进行分类，也不是只抽取项目最终需求，而是：

> **先恢复 Requirement 在长期项目历史中的完整演化，再由这些标注自动推导 Requirement State 和后续 Evaluation Instances。**
> 

---

# 2. Stage 1: Project Annotation 总览

一个 Project 的基本标注层级为：

```
Project
│
├── Sessions
│
└── Requirement Families
      │
      ├── Requirement A
      │      └── Events
      │
      └── Requirement B
             └── Events 
```

其中：

```
Session
= organize project history over time

Requirement Family
= semantic grouping

Requirement
= independent state and replay unit

Event
= state-changing evidence in project history
```

Requirement 的具体 Value 通过 Event 中的 `value_updates` 表达，因此不再单独维护静态的 Attribute 列表；完整的 Requirement State 由其 Events 按时间顺序 replay 得到。

整体 JSON Schema 如下：

```json
{
  "benchmark": "ReqMemBench",
  "annotation_version": "v0.5",

  "project": {
    "project_id": "42204309",
    "project_title": "Project Rebuild MVP – Base NFT + Referral Engine + Fiat On-Ramp",

    "sessions": [
      {
        "session_id": "S1",
        "start": "2025-11-18",
        "end": "2025-11-25",
        "milestone": "M1"
      }
    ]
  },

  "requirement_families": [
    {
      "family_id": "PRIZE_MECHANICS",
      "title": "Prize Mechanics"
    }
  ],

  "requirements": [
    {
      "requirement_id": "REQ_SMALL_PRIZE",
      "title": "Small Prize Mechanism",
      "family_id": "PRIZE_MECHANICS",

      "events": [
        {
	        "event_id": "REQ_SMALL_PRIZE_E001",
	        
          "source_message": {
            "message_id": 8,
            "speaker": "client",
            "text": "We should have five $500 winners."
          },

          "event_type": "INTRODUCE",

          "value_updates": {
            "prize_amount_per_winner": "$500",
            "winner_count": 5
          },

          "scope_updates": {
            "persistence": "PROJECT_PERSISTENT",
            "components": [
              "SMART_CONTRACT",
              "BACKEND"
            ],
            "contexts": [
              "PRIZE_SYSTEM"
            ]
          },

          "ambiguity": null,
          "execution": null
        }
      ]
    },

    {
      "requirement_id": "REQ_BIG_BLOCK",
      "title": "Big Block Mechanism",
      "family_id": "PRIZE_MECHANICS",
      "events": []
    },

    {
      "requirement_id": "REQ_MAURITIUS_GEOBLOCK",
      "title": "Mauritius Geoblock",
      "family_id": null,

      "events": [
        {
          "source_message": {
            "message_id": 210,
            "speaker": "client",
            "text": "Mauritius users should not be able to access the landing page."
          },

          "event_type": "INTRODUCE",

          "value_updates": {
            "geo_access_policy": "Block users from Mauritius"
          },

          "scope_updates": {
            "persistence": "PROJECT_PERSISTENT",
            "components": [
              "FRONTEND"
            ],
            "contexts": [
              "LANDING_PAGE_ACCESS"
            ]
          },

          "ambiguity": null,
          "execution": null
        }
      ]
    }
  ]
}
```

这一 Schema 只保存项目历史中需要直接标注的信息。后续的 Current Requirement State、Requirement State Graph 和 RQ1–RQ5 Evaluation Instances 均由这些标注自动推导。

---

# 3. Session

## 3.1 定义

Session 表示项目历史中一段**语义连续的工作阶段或对话区间**，用于帮助组织长时间跨度的项目历史。

一个 Session 通常围绕相对集中的开发目标展开，例如：

- Smart-contract implementation
- Testnet validation
- Payment integration
- Bug fixing
- Final delivery

Session 主要用于：

1. 将长项目历史划分为较容易处理的时间段；
2. 保留 Requirement 演化发生的阶段信息；
3. 为后续构造不同时间点的 evaluation cutoff 提供辅助。

Session 本身**不拥有 Requirement State**，也不参与 Requirement replay。

例如：

```json
{
  "session_id": "S1",
  "start": "2025-11-18",
  "end": "2025-11-25",
  "milestone": "M1"
}
```

## 3.2 Session 划分原则

Session 应根据项目中明显的**时间间隔、任务目标变化或 Milestone 切换**进行划分。

一般情况下：

> 同一阶段围绕相近开发目标展开的连续对话属于同一个 Session；当项目进入明显不同的任务阶段时，再创建新的 Session。
> 

Session 不需要划分得过细，其作用主要是组织时间线，而不是作为 Requirement 标注单位。

---

# 4. Requirement Family and Atom

ReqMemBench 使用 Requirement Family 对语义相关的 Requirements 进行组织，但 **Requirement Family 并不是每个 Requirement 都必须拥有的父层级**。

整体关系为：

```
Project
│
├── Requirement Families   (optional grouping)
│
└── Requirements           (core annotation units)
      │
      ├── Requirement A → family_id = PRIZE_MECHANICS
      ├── Requirement B → family_id = PRIZE_MECHANICS
      └── Requirement C → family_id = null
```

其中：

- **Requirement Family**：可选的语义分组；
- **Requirement Atom**：真正的标注、状态、replay 和 evaluation 单位。

核心原则是：

> **Family organizes; Requirement owns state.**
> 

---

## 4.1 Requirement Family

Requirement Family 表示一组在业务语义上属于同一个功能模块、机制或主题，同时又能够分别独立演化的 Requirements。

例如：

```
PRIZE_MECHANICS
│
├── REQ_SMALL_PRIZE
└── REQ_BIG_BLOCK
```

Family 本身只保存简单的语义分组信息：

```json
{
  "family_id": "PRIZE_MECHANICS",
  "title": "Prize Mechanics"
}
```

Family 不保存：

```
Scope
Events
Lifecycle
Execution
Scope Inheritance
Propagated Events
```

所有真实状态变化都属于具体 Requirement。

---

## 4.2 Requirement Family 是 Optional 的

并不是所有 Requirement 都必须属于一个 Family。

只有当多个独立 Requirements 之间存在明确的共同业务主题，并且保留这种 sibling relationship 对项目理解或后续 evaluation 有帮助时，才需要建立 Family。

例如：

```
REQ_SMALL_PRIZE
REQ_BIG_BLOCK
```

都属于 Prize Mechanics，因此可以共同关联：

```json
"family_id": "PRIZE_MECHANICS"
```

但某些 Requirement 本身已经是一个完整、独立的功能单元，并不存在需要共同分组的 sibling。

例如：

```
REQ_MAURITIUS_GEOBLOCK
```

如果当前项目中没有其他独立 Requirement 需要和它共同组成一个更高层语义组，则直接：

```json
"family_id": null
```

即可。

不应该为了满足层级结构而人为创建：

```
MAURITIUS_GEOBLOCK
└── REQ_MAURITIUS_GEOBLOCK
```

这样的单一成员 Family。

因此：

> **Family should only be created when it provides meaningful semantic grouping; otherwise the Requirement remains standalone with `family_id = null`.**
> 

---

## 4.3 Requirement Atom

Requirement Atom 是：

> **一个语义完整，并且能够被独立讨论、修改、延迟、恢复、删除、澄清或验证执行结果的功能性或行为性约束。**
> 

Requirement 是 ReqMemBench 最核心的：

```
Annotation Unit
State Unit
Replay Unit
Evaluation Unit
```

每个 Requirement 独立拥有：

```
Value
Scope
Lifecycle
Execution
Events
```

例如：

```
PRIZE_MECHANICS

REQ_SMALL_PRIZE
REQ_BIG_BLOCK
```

虽然两个 Requirements 属于同一个 Family，但它们可以独立变化：

```
REQ_SMALL_PRIZE = ACTIVE
REQ_BIG_BLOCK   = REMOVED
```

因此必须作为两个独立 Requirement Atoms。

---

## 4.4 Requirement 拆分与 Attributes

判断两个内容是否应该拆成独立 Requirements，主要看它们是否能够**独立演化**。

| 判断问题 | YES 时的含义 |
| --- | --- |
| A 能否在 B 不变时被单独修改？ | 支持拆分 |
| A 能否继续有效，而 B 被删除？ | 强烈支持拆分 |
| 当前任务可能只需要 A 而不需要 B 吗？ | 支持拆分 |
| Agent 对 A 和 B 可能采取不同 Action 吗？ | 强烈支持拆分 |
| A 和 B 能否分别判断实现成功或失败？ | 支持拆分 |

Requirement 内部描述同一机制的参数通常属于 **Attributes**，不应继续拆成新的 Requirements。

例如：

```
REQ_SMALL_PRIZE
│
├── prize_amount_per_winner = $500
├── winner_count = 1
├── draw_condition = every 100 sales
└── ticket_rule = 1 ticket per referral
```

这些共同描述 Small Prize Mechanism，因此属于同一个 Requirement 的 Value。

Attribute 名称采用 **controlled open vocabulary**，并通过 Event 中的 `value_updates` 记录：

```json
{
  "value_updates": {
    "winner_count": 1,
    "draw_condition": "every 100 sales"
  }
}
```

完整 Requirement Value 由历史 Events 按时间顺序 replay 得到。

---

## 4.5 Family-level 表达如何标注

Client 有时会使用 Family-level 表达，而不是直接指定某个 Requirement。

例如：

> All prize mechanics should only apply to primary mint.
> 

Annotator / Annotation LLM 首先判断该消息实际影响哪些 Requirements。

如果同时影响 Small Prize 和 Big Block：

```
PRIZE_MECHANICS
│
├── REQ_SMALL_PRIZE → MODIFY
└── REQ_BIG_BLOCK   → MODIFY
```

Family 本身不产生 Event。

如果只影响其中一个 Requirement：

> Remove the large prize mechanics.
> 

则：

```
REQ_SMALL_PRIZE → no event
REQ_BIG_BLOCK   → REMOVE
```

因此，Family-level statement 不会自动传播到所有成员，而必须先判断其真实语义影响。

如果可以确定受影响的 Requirement，但具体 Value、Scope 或 Lifecycle 无法安全确定，则创建：

```
AMBIGUOUS
AMBIGUOUS → ambiguity.status = OPEN
```

如果连受影响的是哪个 Requirement 都无法可靠判断，则进入 annotation review / human adjudication。

最终原则是：

> **Requirement Family provides optional semantic organization, while every actual state change belongs directly to a specific Requirement Atom.**
> 

# 5. Event

ReqMemBench 中，`Event` 表示一条历史消息对某个具体 Requirement 造成的**有效状态变化或重要状态证据**。Event 是 Requirement Lifecycle 的最基本组成单位，也是后续进行 Requirement replay、恢复当前 Gold State 以及生成 RQ1–RQ5 evaluation instances 的核心输入。

为了降低 LLM 标注复杂度，Event Annotation 采用固定结构。每个 Event 始终包含以下七个字段：

```json
{
	"event_id": null,
	
  "source_message": {
    "message_id": null,
    "speaker": null,
    "text": null
  },
	
  "event_type": null,

  "value_updates": null,

  "scope_updates": null,

  "ambiguity": null,

  "execution": null
}
```

[Event_Framework.html](Event_Framework.html)

## 5.1 `event_id`

`event_id` 用于唯一标识某个 Requirement 下的 Event，主要用于后续的人工审查、错误定位和 Requirement State Graph 构建。

`event_id` **不需要由 LLM 生成**，而是在完成 Event 标注后，根据 `requirement_id` 和 Event 的时间顺序自动生成。

格式：

```
<requirement_id>_E<event_number>
```

例如：

```
REQ_SMALL_PRIZE_E001
REQ_SMALL_PRIZE_E002
REQ_SMALL_PRIZE_E003
```

其中：

- `REQ_SMALL_PRIZE` 表示所属 Requirement；
- `E001` 表示该 Requirement 下按时间顺序排列的第 1 个 Event。

例如：

```
{
  "event_id": "REQ_SMALL_PRIZE_E001",
  "source_message": {
    "message_id": 8,
    "speaker": "client",
    "text": "We should have five $500 winners."
  }
}
```

> **`event_id` 仅作为自动生成的标识信息，不属于 LLM 的语义标注任务。**
> 

## 5.2 `source_message`

`source_message` 保存产生当前 Event 的**原始项目消息**。

其作用是直接记录：

> 当前 Event 的标注依据是什么？
> 

结构为：

```json
{
  "source_message": {
    "message_id": 158,
    "speaker": "client",
    "text": "Change the small prize to one $500 winner every 100 sales."
  }
}
```

### 5.2.1 `message_id`

原始项目对话中的消息 ID，用于唯一定位该条消息。

虽然 Event 中已经保存了消息原文，但 `message_id` 仍然需要保留，因为它能够：

- 保持 Event 与原始项目数据的对应关系；
- 恢复时间顺序；
- 关联 Session、Milestone、timestamp 等原始 metadata；
- 在需要时返回完整项目上下文。

### 5.2.2 `speaker`

表示该消息由谁发送。

例如：

```
Client:
"Remove the big block prize."
```

可以直接导致 Requirement 被删除。

而：

```
Freelancer:
"Should we remove the big block prize?"
```

通常只表示一个问题，并不能直接将 Requirement 改为 `REMOVED`。

因此，`speaker` 能够帮助标注系统判断一条信息是否具有修改 Requirement Gold State 的权威性。

### 5.2.3 `text`

保存该条消息的**完整原文**。

必须遵循：

> `source_message.text` 必须保留原始文本，不允许由标注模型进行总结、改写或语义归一化。
> 

保存原文后，可以直接形成：

```
Raw Evidence
     ↓
Event Annotation
```

方便人工 reviewer 或第二个 LLM verifier 判断标注结果是否与原始证据一致，而不需要重新通过 `message_id` 返回完整聊天记录中查找。

---

## 5.3 `event_type`

`event_type` 表示：

> **这条消息对当前 Requirement 造成了什么类型的变化或状态证据？**
> 

它是 Event 最主要的类别标签。

目前 Event Type 主要覆盖四类 Requirement evolution：

```
Definition
Lifecycle
Uncertainty
Execution
```

`event_type` 与其他字段和 Lifecycle State 和 Ambiguity State（详细解释请看7.3） 的关系如下：

| Category | `event_type` | `value_updates` | `scope_updates` | `ambiguity` | `execution` | Lifecycle State | Ambiguity State | 含义 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Definition | `INTRODUCE` | ✅ 通常填写 | ✅ 可填写 | `null` | `null` | → `ACTIVE` | `null` | Requirement 第一次被明确建立 |
| Definition | `MODIFY` | ✅ 可填写 | ✅ 可填写 | `null` | `null` | 通常保持不变 | 可关闭已解决 ambiguity | 已有 Requirement 的 Value、Scope 或两者被明确修改 |
| Lifecycle | `DEFER` | `null` | `null` | `null` | `null` | → `DEFERRED` | 保持 | Requirement 仍然存在，但当前阶段暂时不执行 |
| Lifecycle | `RESUME` | `null` | `null` | `null` | `null` | `DEFERRED → ACTIVE`，或保持 `ACTIVE` | `OPEN → null`（如用于解决 ambiguity） | 恢复暂缓的 Requirement，或确认继续沿用原 Requirement |
| Lifecycle | `REMOVE` | `null` | `null` | `null` | `null` | → `REMOVED` | 不再影响当前执行 | Client 明确表示不再需要整个 Requirement |
| Uncertainty | `AMBIGUOUS` | `null` | `null` | ✅ 必须填写 | `null` | **不直接改变** | → `OPEN` | 当前存在无法安全解决的 Value、Scope 或 Lifecycle uncertainty |
| Execution | `IMPLEMENTATION_CLAIM` | `null` | `null` | `null` | ✅ 必须填写 | 不改变 | 不改变 | Freelancer 声称已经实现或修复 Requirement，但尚未运行验证 |
| Execution | `RUNTIME_FAILURE` | `null` | `null` | `null` | ✅ 必须填写 | 不改变 | 不改变 | 实际运行或测试证明当前 implementation 没有满足 Requirement |
| Execution | `RUNTIME_VERIFICATION` | `null` | `null` | `null` | ✅ 必须填写 | 不改变 | 不改变 | 实际运行或测试确认 Requirement 已被正确实现 |

---

### 5.3.1 `INTRODUCE`

`INTRODUCE` 表示某个 Requirement **第一次在可观察的项目历史中被明确建立**。

例如 Client 首次提出：

> We should have five $500 winners.
> 

可以标注为：

```
{
  "source_message": {
    "message_id": 8,
    "speaker": "client",
    "text": "We should have five $500 winners."
  },

  "event_type": "INTRODUCE",

  "value_updates": {
    "prize_amount_per_winner": "$500",
    "winner_count": 5
  },

  "scope_updates": {
    "persistence": "PROJECT_PERSISTENT",
    "components": ["SMART_CONTRACT", "BACKEND"],
    "contexts": ["PRIZE_SYSTEM"]
  },

  "ambiguity": null,
  "execution": null
}
```

Replay：

```
NOT_YET_ESTABLISHED
        ↓ INTRODUCE
ACTIVE
```

并建立初始 Value 和 Scope：

```
Lifecycle = ACTIVE

prize_amount_per_winner = $500
winner_count = 5
```

#### 标注原则

`INTRODUCE` 只用于：

> **Requirement 第一次在可观察历史中被明确建立。**
> 

如果 Requirement 已经存在，只是内容发生改变，则使用 `MODIFY`。

同时需要注意：

> 一个 Requirement 在数据中的第一个可观察 Event 不一定必须是 `INTRODUCE`。
> 

如果项目历史从中途开始，而 Requirement 第一次出现时已经处于修改、暂缓或删除阶段，不应人工补造不存在的 `INTRODUCE` Event。

---

### 5.3.2 `MODIFY`

`MODIFY` 表示：

> **已有 Requirement 的 Value、Scope 或两者被明确修改。**
> 

`MODIFY` 只用于已经存在的 Requirement。如果 Requirement 第一次被建立，应使用 `INTRODUCE`。

---

#### `value_updates`

`value_updates` 记录当前 Event 明确建立的新 Value。

例如原状态：

```
winner_count = 5
```

Client 后来说：

> Let's make it one $500 winner every 100 sales.
> 

则：

```
{
  "event_type": "MODIFY",

  "value_updates": {
    "winner_count": 1,
    "prize_amount_per_winner": "$500",
    "draw_condition": "every 100 sales"
  },

  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
ACTIVE
winner_count = 5

        ↓ MODIFY

ACTIVE
winner_count = 1
draw_condition = every 100 sales
```

`value_updates` 只记录当前消息明确建立或修改的值，不需要重新输出整个 Requirement State。

没有被当前 Event 修改的 Value 在 replay 时继续继承。

---

#### `scope_updates`

`scope_updates` 记录 Requirement **适用范围的明确变化**，而不是 Requirement 本身业务逻辑的变化。

Scope 包含：

```
{
  "persistence": null,
  "components": null,
  "contexts": null
}
```

其中：

- `persistence`：Requirement 持续多长时间，例如 `PROJECT_PERSISTENT`、`MILESTONE_LOCAL`、`TASK_LOCAL`；
- `components`：Requirement 影响哪些技术模块，例如 `FRONTEND`、`BACKEND`、`SMART_CONTRACT`；
- `contexts`：Requirement 在哪些业务场景下适用，例如 `PRIMARY_MINT`、`REFERRAL_MINT`、`FIAT_PAYMENT`。

例如 Client 说：

> The prize should now only apply to referral mint.
> 

则：

```
{
  "event_type": "MODIFY",

  "value_updates": null,

  "scope_updates": {
    "persistence": null,
    "components": null,
    "contexts": ["REFERRAL_MINT"]
  },

  "ambiguity": null,
  "execution": null
}
```

假设原 State：

```
persistence = PROJECT_PERSISTENT
components = [SMART_CONTRACT, BACKEND]
contexts = [PRIZE_SYSTEM]
```

Replay：

```
ACTIVE
contexts = [PRIZE_SYSTEM]

        ↓ MODIFY

ACTIVE
contexts = [REFERRAL_MINT]
```

得到：

```
persistence = PROJECT_PERSISTENT
components = [SMART_CONTRACT, BACKEND]
contexts = [REFERRAL_MINT]
```

其中 `null` 表示：

> 当前 Event 没有修改该 Scope dimension。
> 

而不是：

> 原来的 Scope 不存在。
> 

如果一条消息同时修改 Value 和 Scope，则仍然只创建一个 `MODIFY` Event，同时填写 `value_updates` 和 `scope_updates`。

---

#### `MODIFY` 与 ambiguity resolution

`MODIFY` 还可能解决此前存在的 ambiguity。

例如此前：

```
payment_provider = Coinbase Commerce
ambiguity.status = OPEN
ambiguity.dimension = VALUE
```

Client 后续明确：

> Use Transak instead.
> 

则可以产生：

```
{
  "event_type": "MODIFY",

  "value_updates": {
    "payment_provider": "Transak"
  },

  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay 后：

```
ACTIVE
payment_provider = Coinbase Commerce
ambiguity = OPEN

        ↓ MODIFY

ACTIVE
payment_provider = Transak
ambiguity = null
```

因为 Client 已经提供了足够的新信息，原来的 Value ambiguity 被解决。

---

### 5.3.3 `DEFER`

`DEFER` 表示：

> **Requirement 仍然存在，但当前阶段暂时不执行。**
> 

例如 Client：

> Let's leave the fiat payment integration for later.
> 

标注：

```
{
  "source_message": {
    "message_id": 220,
    "speaker": "client",
    "text": "Let's leave the fiat payment integration for later."
  },

  "event_type": "DEFER",

  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
ACTIVE
   ↓ DEFER
DEFERRED
```

`DEFERRED` 不等于 `REMOVED`。

进入 `DEFERRED` 后：

```
Value = preserved
Scope = preserved
Lifecycle = DEFERRED
```

即 Requirement 仍然属于项目历史中的有效 Requirement，只是当前阶段暂时不要求执行。

---

### 5.3.4 `RESUME`

`RESUME` 表示：

> **在不修改 Requirement Value 和 Scope 的情况下，使 Requirement 恢复为当前可以继续执行的状态，或者消除此前阻止安全执行的 ambiguity。**
> 

`RESUME` 主要适用于两种情况：

1. 一个此前被 `DEFERRED` 的 Requirement 被重新启用；
2. 一个存在 `OPEN` ambiguity 的 Requirement 被 Client 明确确认继续沿用原有 Value 和 Scope。

因此，`RESUME` Event 本身始终满足：

```
value_updates = null
scope_updates = null
```

---

#### Case 1 — 从 `DEFERRED` 恢复

例如，Fiat Integration 此前被暂缓：

```
Lifecycle = DEFERRED
```

随后 Client 说：

> Let's continue with the fiat integration now.
> 

标注：

```
{
  "event_type": "RESUME",
  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
DEFERRED
   ↓ RESUME
ACTIVE
```

Requirement 原来的 Value 和 Scope 全部保留。

例如：

```
payment_provider = Transak
scope = FIAT_PAYMENT
```

在 `RESUME` 前后均保持不变。

---

#### Case 2 — 解决 ambiguity，但不修改 Value / Scope

例如 Client 此前已经确认：

> Use Coinbase Commerce.
> 

当前 State：

```
Lifecycle = ACTIVE
payment_provider = Coinbase Commerce
ambiguity = null
```

随后 Freelancer 发现：

> Coinbase Commerce can't support direct card payment.
> 

这会产生 `AMBIGUOUS` Event，之后得到：

```
Lifecycle = ACTIVE
payment_provider = Coinbase Commerce

ambiguity.status = OPEN
ambiguity.dimension = VALUE
```

之后 Client 回复：

> Yes, keep Coinbase Commerce.
> 

Client 没有改变 Requirement Value：

```
Coinbase Commerce
→
Coinbase Commerce
```

因此这里不应使用 `MODIFY`，而应使用：

```
{
  "event_type": "RESUME",
  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
ACTIVE
payment_provider = Coinbase Commerce
ambiguity = OPEN

        ↓ RESUME

ACTIVE
payment_provider = Coinbase Commerce
ambiguity = null
```

这里 Lifecycle 实际上保持：

```
ACTIVE → ACTIVE
```

真正发生变化的是：

```
Ambiguity:
OPEN → null
```

其含义是：

> Client 明确确认继续沿用此前 Requirement，因此此前阻止 Agent 安全执行的不确定性已经被解决。
> 

---

#### Case 3 — Client 在解决 ambiguity 的同时修改 Requirement

如果 Client 并不是确认原方案，而是给出了一个新的 Value，例如：

> Okay, use Transak instead.
> 

此时 Requirement Value 发生了真实变化，因此应首先使用：

```
MODIFY
```

如果实现中需要显式记录“该 ambiguity 已解决”，可以在同一 source message 下形成有序 Events：

```
MODIFY
   ↓
RESUME
```

但在 Stage 2 replay 中，如果新的 `MODIFY` 已经明确解决对应 ambiguity，也可以直接由 replay rule 将相关 `OPEN` ambiguity 关闭。

核心原则是：

> `RESUME` 本身不承担 Value 或 Scope 修改。
> 

---

### 5.3.5 `REMOVE`

`REMOVE` 表示：

> **Client 明确表示不再需要整个 Requirement。**
> 

例如：

> Remove the big block prize completely.
> 

标注：

```
{
  "source_message": {
    "message_id": 195,
    "speaker": "client",
    "text": "Remove the big block prize completely."
  },

  "event_type": "REMOVE",

  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
ACTIVE
   ↓ REMOVE
REMOVED
```

如果 Requirement 此前处于 `DEFERRED`：

```
DEFERRED
   ↓ REMOVE
REMOVED
```

`REMOVE` 表示 Requirement **当前已经失效**，但并不会删除其历史 Value、Scope 或 Events。

因此：

```
REMOVED
≠
erase historical Requirement
```

Requirement 的历史状态仍然保留，用于后续：

- Requirement State Graph；
- RQ1 historical selection；
- RQ3 validity evaluation；
- provenance / error analysis。

---

### 5.3.6 `AMBIGUOUS`

`AMBIGUOUS` 表示：

> **当前历史中出现了一个无法根据已有信息安全解决、并且可能影响 Agent 下一步行为的冲突或不确定性。**
> 

`AMBIGUOUS` 与其他 Lifecycle Event 最大的区别是：

> **它不直接改变 Requirement Lifecycle State。**
> 

例如 Requirement 当前是：

```
Lifecycle = ACTIVE
```

发生 `AMBIGUOUS` 后仍然可以保持：

```
Lifecycle = ACTIVE
```

变化的是独立的 Ambiguity State：

```
ambiguity.status = OPEN
```

因此标准 replay 为：

```
ACTIVE
ambiguity = null

        ↓ AMBIGUOUS

ACTIVE
ambiguity = OPEN
```

当该 `OPEN` ambiguity 与当前 evaluation task 相关，并阻止 Agent 安全决定下一步时，后续 RQ4 自动派生：

```
Agent Action = CLARIFY
```

因此完整逻辑是：

```
AMBIGUOUS Event
        ↓
ambiguity.status = OPEN
        ↓
Requirement Gold State
        ↓
Current task is affected
        ↓
RQ4 Gold Action = CLARIFY
```

而不是：

```
AMBIGUOUS
        ↓
Lifecycle = CLARIFY
```

---

#### `ambiguity` 字段

Stage 1 中的 `ambiguity` 结构保持：

```
{
  "dimension": "VALUE",
  "description": "..."
}
```

`dimension` 表示当前 ambiguity 发生在哪个 Requirement 维度。

允许值：

```
VALUE
SCOPE
LIFECYCLE
```

Stage 1 **不需要额外标注 `status`**。

Stage 2 replay 遇到 `AMBIGUOUS` Event 后，自动生成：

```
{
  "status": "OPEN",
  "dimension": "VALUE",
  "description": "...",
  "source_event_id": "REQ_EXAMPLE_E003"
}
```

其中：

- `status = OPEN`：当前 ambiguity 尚未解决；
- `dimension`：ambiguity 所影响的 Requirement State 维度；
- `description`：Stage 1 已标注的不确定性说明；
- `source_event_id`：产生该 ambiguity 的 Event，用于 provenance。

---

#### Case 1 — Client Requirement 与 Freelancer Technical Finding 冲突

首先 Client 明确：

> Use Coinbase Commerce.
> 

假设 `REQ_FIAT_ONRAMP` 已经存在，则：

```
{
  "source_message": {
    "message_id": 100,
    "speaker": "client",
    "text": "Use Coinbase Commerce."
  },

  "event_type": "MODIFY",

  "value_updates": {
    "payment_provider": "Coinbase Commerce"
  },

  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

此时：

```
Lifecycle = ACTIVE
payment_provider = Coinbase Commerce
ambiguity = null
```

随后 Freelancer 说：

> Coinbase Commerce can't support direct card payment.
> 

这条信息说明：

```
Client-confirmed solution
Coinbase Commerce

        conflicts with

Technical finding
Cannot satisfy direct card payment
```

但 Freelancer **没有权限直接替 Client 把 provider 改成其他方案**。

因此不能标：

```
MODIFY
payment_provider = Transak
```

也不能标：

```
REMOVE
```

正确标注为：

```
{
  "source_message": {
    "message_id": 101,
    "speaker": "freelancer",
    "text": "Coinbase Commerce can't support direct card payment."
  },

  "event_type": "AMBIGUOUS",

  "value_updates": null,
  "scope_updates": null,

  "ambiguity": {
    "dimension": "VALUE",
    "description": "The client selected Coinbase Commerce, but the freelancer reports that it cannot satisfy the required direct card payment functionality."
  },

  "execution": null
}
```

Replay：

```
ACTIVE
payment_provider = Coinbase Commerce
ambiguity = null

        ↓ AMBIGUOUS

ACTIVE
payment_provider = Coinbase Commerce
ambiguity.status = OPEN
ambiguity.dimension = VALUE
```

这里有一个非常重要的原则：

> **AMBIGUOUS 不会删除或覆盖最后一个 Client-confirmed Value。**
> 

因此不是：

```
payment_provider = UNKNOWN
```

而是：

```
last_confirmed_value = Coinbase Commerce
ambiguity = OPEN
```

含义是：

> Coinbase Commerce 仍然是最后一次由 Client 明确确认的 Requirement Value，但新的冲突证据使 Agent 当前不能安全地直接继续执行。
> 

在相关任务中，RQ4 应派生：

```
Agent Action = CLARIFY
```

而不是：

```
USE Coinbase Commerce
```

也不是：

```
Automatically switch to Transak
```

---

#### Case 2 — Scope Ambiguity

Client 之前规定：

> Mauritius users should not access the landing page.
> 

已确认 Scope：

```
components = [FRONTEND]
contexts = [LANDING_PAGE_ACCESS]
```

随后 Freelancer 问：

> Does that also mean the payment provider doesn't need to support Mauritius?
> 

这里没有证据证明：

```
LANDING_PAGE_ACCESS
```

应该自动传播到：

```
PAYMENT_PROVIDER_ELIGIBILITY
```

因此：

```
{
  "event_type": "AMBIGUOUS",

  "value_updates": null,
  "scope_updates": null,

  "ambiguity": {
    "dimension": "SCOPE",
    "description": "Whether the Mauritius landing-page restriction also applies to payment-provider eligibility."
  },

  "execution": null
}
```

Replay：

```
ACTIVE
contexts = [LANDING_PAGE_ACCESS]
ambiguity = null

        ↓ AMBIGUOUS

ACTIVE
contexts = [LANDING_PAGE_ACCESS]
ambiguity.status = OPEN
ambiguity.dimension = SCOPE
```

这里原来已经确认的：

```
LANDING_PAGE_ACCESS
```

仍然有效。

不确定的只是：

```
Does it also apply to PAYMENT_PROVIDER_ELIGIBILITY?
```

因此 Stage 2 **不能自动扩展原 Scope，也不能把整个 Requirement 判断为无效**。

对于涉及 `PAYMENT_PROVIDER_ELIGIBILITY` 的后续任务：

```
RQ4 Gold Action = CLARIFY
```

---

#### Case 3 — Lifecycle Ambiguity

例如 Client 说：

> I'm not sure we still need the referral feature. Let's discuss it first.
> 

这里没有明确：

```
REMOVE
```

也没有明确：

```
DEFER
```

因此标注：

```
{
  "event_type": "AMBIGUOUS",

  "value_updates": null,
  "scope_updates": null,

  "ambiguity": {
    "dimension": "LIFECYCLE",
    "description": "It is unclear whether the referral feature should remain active, be deferred, or be removed."
  },

  "execution": null
}
```

假设此前 Lifecycle 为 `ACTIVE`，Replay：

```
ACTIVE
ambiguity = null

        ↓ AMBIGUOUS

ACTIVE
ambiguity.status = OPEN
ambiguity.dimension = LIFECYCLE
```

这里继续保留：

```
last_confirmed_lifecycle = ACTIVE
```

但由于 Client 已经明确质疑 Requirement 是否仍然需要，Agent 在受影响的后续任务中不能将旧 `ACTIVE` State 视为可以无条件直接执行的依据。

因此：

```
RQ4 Gold Action = CLARIFY
```

直到后续 Client 明确：

```
keep it      → RESUME
leave it     → DEFER
remove it    → REMOVE
change it    → MODIFY
```

---

### 5.3.7 `IMPLEMENTATION_CLAIM`

`IMPLEMENTATION_CLAIM` 表示：

> **Freelancer 声称某个 Requirement 已经实现、修改完成或修复完成，但没有真实 runtime evidence 证明其成功。**
> 

例如 Freelancer：

> ETH minting works now. I fixed it.
> 

标注：

```
{
  "source_message": {
    "message_id": 320,
    "speaker": "freelancer",
    "text": "ETH minting works now. I fixed it."
  },

  "event_type": "IMPLEMENTATION_CLAIM",

  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,

  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer states that ETH minting has been fixed and is working."
  }
}
```

Replay：

```
Execution = UNKNOWN / previous state
        ↓ IMPLEMENTATION_CLAIM
Execution = CLAIMED_WORKING
```

Requirement Lifecycle **不发生变化**。

例如：

```
Lifecycle = ACTIVE

        ↓ IMPLEMENTATION_CLAIM

Lifecycle = ACTIVE
Execution = CLAIMED_WORKING
```

需要明确：

```
CLAIMED_WORKING
≠
VERIFIED_WORKING
```

Freelancer 写完代码、提交代码，或者说：

> Fixed.
> 

> Done.
> 

> Working now.
> 

通常最多只能得到：

```
CLAIMED_WORKING
```

---

#### `observed_behavior`

虽然字段名为：

```
observed_behavior
```

对于 `IMPLEMENTATION_CLAIM`，它实际记录的是：

> **Freelancer 报告的 implementation 状态。**
> 

例如：

```
{
  "status": "CLAIMED_WORKING",
  "observed_behavior": "Freelancer reports that ETH minting is now working."
}
```

它不等于真实 runtime verification。

---

### 5.3.8 `RUNTIME_FAILURE`

`RUNTIME_FAILURE` 表示：

> **Client、测试结果或实际运行明确证明当前 implementation 没有满足 Requirement。**
> 

例如 Requirement：

```
User pays ETH
        ↓
NFT should be minted
        ↓
User receives NFT
```

Client 实际测试：

> I paid with ETH. The ETH was taken but I didn't receive the NFT.
> 

正确标注：

```
{
  "source_message": {
    "message_id": 318,
    "speaker": "client",
    "text": "I paid with ETH. The ETH was taken but I didn't receive the NFT."
  },

  "event_type": "RUNTIME_FAILURE",

  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,

  "execution": {
    "status": "FAILED",
    "observed_behavior": "ETH was consumed but the NFT was not received."
  }
}
```

Replay：

```
Execution = UNKNOWN / previous state
        ↓ RUNTIME_FAILURE
Execution = FAILED
```

Requirement Lifecycle 不发生变化：

```
Lifecycle = ACTIVE
Execution = UNKNOWN

        ↓ RUNTIME_FAILURE

Lifecycle = ACTIVE
Execution = FAILED
```

因此：

```
Execution = FAILED
```

**不能推导：**

```
Lifecycle = REMOVED
```

Implementation failure 和 Requirement validity 是两个不同的 State dimension。

---

#### `observed_behavior` 必须具体

应记录实际观察到的行为。

推荐：

```
"observed_behavior": "ETH was consumed but the NFT was not received."
```

而不是：

```
"observed_behavior": "It doesn't work."
```

具体 runtime evidence 可以帮助后续：

- 判断 failure 是否对应当前 Requirement；
- 建立 Requirement-specific tests；
- 构建 RQ5 evaluation；
- 进行 code outcome error analysis。

---

### 5.3.9 `RUNTIME_VERIFICATION`

`RUNTIME_VERIFICATION` 表示：

> **真实运行或测试明确确认 implementation 已经满足 Requirement。**
> 

例如此前发生：

```
Execution = FAILED
```

Freelancer 修改代码后说：

> Fixed.
> 

此时只能产生：

```
IMPLEMENTATION_CLAIM
```

Replay：

```
FAILED
   ↓ IMPLEMENTATION_CLAIM
CLAIMED_WORKING
```

直到 Client 后续真实测试：

> I tried it again. ETH payment works and I received the NFT this time.
> 

才能标注：

```
{
  "source_message": {
    "message_id": 330,
    "speaker": "client",
    "text": "I tried it again. ETH payment works and I received the NFT this time."
  },

  "event_type": "RUNTIME_VERIFICATION",

  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,

  "execution": {
    "status": "VERIFIED_WORKING",
    "observed_behavior": "The client successfully paid with ETH and received the NFT."
  }
}
```

Replay：

```
CLAIMED_WORKING
   ↓ RUNTIME_VERIFICATION
VERIFIED_WORKING
```

完整 Execution trajectory 可以表示为：

```
Execution = UNKNOWN
   ↓ RUNTIME_FAILURE
FAILED
   ↓ IMPLEMENTATION_CLAIM
CLAIMED_WORKING
   ↓ RUNTIME_VERIFICATION
VERIFIED_WORKING
```

而 Requirement Lifecycle 在整个过程中可能始终保持：

```
ACTIVE
```

即：

```
Requirement Lifecycle
ACTIVE
   │
   ├── RUNTIME_FAILURE
   ├── IMPLEMENTATION_CLAIM
   └── RUNTIME_VERIFICATION
   │
ACTIVE
```

因此必须始终区分：

```
Requirement validity
        ≠
Implementation success
```

`RUNTIME_VERIFICATION` 更新的是 **Execution State**，而不是 Requirement Lifecycle。

---

# 6. Stage 2: Automatic Replay and Benchmark Construction

Stage 1 的目标是从原始项目历史中恢复 Requirement 的长期演化过程，并将其表示为结构化的 **Requirement Events**。在此基础上，Stage 2 不再对原始数据进行新的人工标注，而是利用 Stage 1 得到的结构化 annotation，自动恢复任意历史时间点上的 Requirement 状态，并进一步构建 ReqMemBench 的 evaluation instances。

整体过程如下：

```
Project Annotation
        ↓
Requirement Event Replay
        ↓
Requirement State Graph
        ↓
Derived Gold State at target time t*
        ↓
RQ1–RQ5 Evaluation Instances
```

换言之，Stage 1 记录 **“Requirement 在项目过程中发生了什么变化”**，而 Stage 2 根据这些变化进一步推导 **“在某个具体时间点，哪些 Requirement 当前有效，以及 Coding Agent 应当如何理解和执行这些 Requirement”**。

---

## 6.1 Goal

Stage 2 的核心目标是将 Stage 1 标注得到的 Requirement lifecycle 转换为可以直接用于 benchmark evaluation 的 gold data。

对于一个项目中的 Requirement Atom $r$，首先按照项目时间顺序 replay 与该 Requirement 相关的 Events：

```
INTRODUCE
    ↓
MODIFY
    ↓
DEFER
    ↓
RESUME
    ↓
...
```

由此恢复 Requirement 随项目推进不断变化的状态。

对于任意选定的 evaluation target time $t^*$*，仅使用 $t^*$* 之前已经发生的 Requirement Events，即可推导该 Requirement 在这一时刻的 gold state：

$$
G_r(t^*) = \operatorname{Replay}\left(E_r^{\le t^*}\right)
$$

其中：

- $E_r^{\leq t^*}$ *表示 Requirement $r$ 在 $t^*$* 之前发生的所有 Events；
- $G_r(t^*)$ *表示 Requirement $r$ 在 $t^*$* 时刻的正确状态。

多个 Requirement 的状态共同组成项目在 $t^*$ 时刻的 **Derived Gold State**。

该 Gold State 随后作为统一的数据基础，用于构建 ReqMemBench 的 RQ1–RQ5 evaluation instances，而不需要针对不同 RQ 分别建立独立的人工标注体系。

---

## 6.2 Input and Output

### Input

Stage 2 的输入是 Stage 1 完成后的完整 **Project Annotation**，主要包括：

```
Project Annotation
│
├── Sessions
├── Requirement Families
├── Requirement Atoms
└── Requirement Events
```

其中：

- **Session** 提供项目历史的时间和对话组织结构；
- **Requirement Family** 提供 Requirement 之间的语义分组信息；Family 可以不存在，并且不作为独立 lifecycle replay unit；
- **Requirement Atom** 是 Requirement lifecycle replay 和后续 evaluation 的基本单位；
- **Requirement Event** 记录 Requirement 在项目历史中的 INTRODUCE、MODIFY、DEFER、RESUME、REMOVE、AMBIGUOUS 等变化。

Stage 2 不直接从原始聊天重新识别 Requirement，而是以这些已经完成的 Stage 1 annotation 为唯一结构化输入。

### Output

Stage 2 依次产生三类主要派生数据：

```
outputs/
└── stage2/
    └── 42204309/
        ├── requirement_state_graph.json
        ├── gold_states.json
        └── evaluation_instances/
```

#### 1. Requirement State Graph

按照 Event 时间顺序 replay 每个 Requirement Atom，恢复其完整 lifecycle，例如：

```
REQ_SMALL_PRIZE

INTRODUCE
    ↓
ACTIVE(v1)
    ↓ MODIFY
ACTIVE(v2)
    ↓ DEFER
DEFERRED
    ↓ RESUME
ACTIVE(v2)
```

Requirement State Graph 保留 Requirement 从首次出现到后续修改、暂停、恢复或删除的完整状态变化过程。

#### 2. Derived Gold State

对于一个 evaluation target time $t^*$，从 Requirement State Graph 中截取该时间点对应的状态，得到：

```
G(t*)
│
├── 当前存在的 Requirements
├── 当前有效的 Requirement value / attributes
├── 当前 scope
├── lifecycle status
├── superseded / inactive information
└── supporting historical evidence
```

因此，Gold State 并不固定等于项目结束时的最终状态，而是表示某一个特定时间点 $t^*$ 上项目中所有 Requirement 的正确状态。

同一个项目可以选择多个不同的 target time，例如：

$$

t_1^*, t_2^*, t_3^*, \ldots, t_n^*

$$

并分别得到：

$$

G(t_1^*), G(t_2^*), G(t_3^*), \ldots, G(t_n^*)

$$

因此，一个真实的 longitudinal project history 可以在不同项目阶段产生多个 benchmark instances。

#### 3. RQ1–RQ5 Evaluation Instances

最终，根据 $G(t^*)$ *以及 $t^*$* 之前的原始项目历史，自动构建不同层级的 evaluation instances，用于评估 Coding Agent 是否能够：

```
历史 Requirement
        ↓
找到相关信息
        ↓
理解当前有效状态
        ↓
解决新旧信息之间的时间关系
        ↓
决定使用、忽略、覆盖或澄清
        ↓
正确落实到后续 coding behavior
```

具体的 RQ1–RQ5 instance construction rules 将在后续章节中分别定义。

---

## 6.3 No Additional Human Annotation

Stage 2 **不引入新的人工 Requirement 标注**。

人工标注工作的边界在 Stage 1 的 Requirement Events 处结束：

```
Raw Project History
        ↓
Human Annotation
        ↓
Requirement Events
────────────────────────
        ↓
Automatic Replay
        ↓
Gold State
        ↓
Evaluation Instances
```

Stage 2 中的 Requirement State、Gold State 以及 RQ-specific gold labels，均通过预先定义的 replay 和 instance construction rules 从 Stage 1 annotation 中派生。

因此，不需要针对 RQ1、RQ2、RQ3、RQ4 和 RQ5 分别重新阅读项目历史并建立五套独立人工标签。

这一设计有三个主要目的。

第一，**保持不同 evaluation tasks 之间的 gold consistency**。

RQ1–RQ5 使用同一个 Requirement lifecycle 和同一个 $G(t^*)$ 作为事实基础，避免不同任务之间出现相互矛盾的人工标签。

第二，**降低 benchmark construction cost**。

一个项目只需要完成一次 longitudinal Requirement annotation，即可从其中派生多个 target time 和多个 evaluation tasks。

第三，**提高 benchmark 的可追溯性**。

任意一个 evaluation gold label 都可以反向追踪到：

```
Evaluation Instance
        ↓
Gold State
        ↓
Requirement Event
        ↓
source_message
        ↓
Original Project History
```

因此，当某个 benchmark instance 出现问题时，可以直接定位到产生该 gold state 的 Requirement Events 和原始对话证据。

---

# 7. Requirement Event Replay and State Transition

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

---

## 7.1 Replay Unit

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

## 7.2 Event Ordering

对于同一个 Requirement Atom，所有 Events 必须按照其在原始项目中的实际发生顺序进行 replay：

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
REQ_SMALL_PRIZE_1
REQ_SMALL_PRIZE_2
REQ_SMALL_PRIZE_3
```

`event_id` 本身不决定时间顺序；实际 replay 顺序仍以 Event 对应的原始 project history 顺序为准。

---

## 7.3 Requirement State

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
    "status": "OPEN",
    "dimension": "VALUE",
	  "description": "It is unclear whether ETH minting should continue using the current                     implementation after the newly reported conflict.",
    "source_event_id": "REQ_ETH_MINT_E003"
  },

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

Requirement State 主要包含以下几类信息。

### 7.3.1 Current Attributes

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

---

### 7.3.2 Current Scope

`scope` 表示该 Requirement 当前适用的范围，包括 Stage 1 已经标注的：

```
persistence
components
contexts
```

如果后续 Event 修改了 scope，则只更新 Event 中明确发生变化的部分；没有发生变化的 scope 信息继续沿用之前 State。

---

### 7.3.3 Lifecycle Status

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

在 INTRODUCE 之前，该 Requirement 尚不存在于当前项目状态中，因此不需要生成 ACTIVE State。

---

### 7.3.4 Ambiguity State

AMBIGUOUS 与 ACTIVE、DEFERRED、REMOVED 不属于同一类状态。

例如，一个 Requirement 可能同时满足：

```
lifecycle_status = ACTIVE
ambiguity = OPEN
```

这表示：

> Requirement 本身仍然存在，但其某些信息目前无法安全确定，需要进一步 clarification。
> 

因此，ambiguity 应作为 Requirement State 中独立的信息保存，而不应该简单地把整个 Requirement 的 lifecycle status 改成 `AMBIGUOUS`。

这一设计对于后续 RQ4 的 **Memory-or-Clarify Decision** 非常重要。

---

### 7.3.5 Execution State

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

### 7.3.6 Supporting_Event

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

## 7.4 State Transition Rules

Requirement replay 的核心是定义不同 Event 如何改变 Requirement State。

统一表示为：

$$

S_r^{(k)} = T\left(S_r^{(k-1)}, E_r^{(k)}\right)

$$

Stage 1 中不同 Event Type 对 State 的影响如下。

### 7.4.1 INTRODUCE

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

得到：

```
ACTIVE

trigger = previous target
amount = 100
```

---

### 7.4.2 MODIFY

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

---

### 7.4.3 DEFER

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

---

### 7.4.4 RESUME

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

如果 RESUME 对应的是此前未解决的 ambiguity，则同时关闭已经被明确解决的 ambiguity state。

---

### 7.4.5 REMOVE

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

这一点对于后续 RQ3 判断历史 Requirement 是否已经失效非常重要。

---

### 7.4.6 AMBIGUOUS

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
ambiguity = null
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
ambiguity = null

        ↓ AMBIGUOUS

ACTIVE
trigger = every 50,000 sales

ambiguity:
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
    "status": "OPEN",
    "dimension": "VALUE",
    "description": "The new trigger condition cannot be uniquely determined from the current history.",
    "source_event_id": "REQ_SMALL_PRIZE_E004"
  }
}
```

其中：

- `status = OPEN` 表示当前 ambiguity 尚未解决；
- `dimension` 直接继承 Stage 1 `AMBIGUOUS` Event，可取 `VALUE`、`SCOPE` 或 `LIFECYCLE`；
- `description` 记录具体的不确定性；
- `source_event_id` 指向产生当前 ambiguity 的 Requirement Event。

因此，Requirement 可以同时处于：

```
Lifecycle = ACTIVE
Ambiguity = OPEN
```

这表示：

> Requirement 最后一次确认的状态仍然有效，但当前存在新的 unresolved uncertainty，使 Agent 不能在受影响的任务中安全地自行推断下一步。
> 

当该 unresolved ambiguity 与当前 evaluation task 相关时，后续 RQ4 可以进一步派生：

```
Agent Action = CLARIFY
```

具体的 ambiguity 保留、解决以及与 RQ4 `CLARIFY` Action 的关系将在 **7.6 AMBIGUOUS Event Handling** 中进一步说明。

---

### 7.4.7 IMPLEMENTATION_CLAIM

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

### 7.4.8 RUNTIME_FAILURE

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

### 7.4.9 RUNTIME_VERIFICATION

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

### 7.4.10 Transition Summary

不同 Event 对 Requirement State 的主要影响可以总结为：

| Event | Value | Scope | Lifecycle | Ambiguity | Execution |
| --- | --- | --- | --- | --- | --- |
| `INTRODUCE` | 初始化 | 可初始化 | → `ACTIVE` | 无 | 通常不变 |
| `MODIFY` | 更新 | 可更新 | 保持 | 可解决相关 ambiguity | 保持 |
| `DEFER` | 保留 | 保留 | → `DEFERRED` | 保持 | 保留 |
| `RESUME` | 保留 | 保留 | `DEFERRED → ACTIVE` 或保持 | 可关闭 | 保留 |
| `REMOVE` | 保留历史值 | 保留历史值 | → `REMOVED` | 当前执行意义结束 | 保留历史 |
| `AMBIGUOUS` | 不猜测 | 不猜测 | 保持 | → `OPEN` | 保持 |
| `IMPLEMENTATION_CLAIM` | 保持 | 保持 | 保持 | 保持 | → `CLAIMED_WORKING` |
| `RUNTIME_FAILURE` | 保持 | 保持 | 保持 | 保持 | → `FAILED` |
| `RUNTIME_VERIFICATION` | 保持 | 保持 | 保持 | 保持 | → `VERIFIED_WORKING` |

如果 Event sequence 出现无法按照这些规则解释的非法 transition，Stage 2 不应自行猜测修复，而应将其标记为 consistency error，并在后续 Quality Control 阶段检查。

---

## 7.5 Requirement State Graph

完成 Event replay 后，每一个 Requirement Atom 都对应一条完整的 State evolution chain。

例如：

```
REQ_SMALL_PRIZE

S0
│
│ INTRODUCE
▼
S1
ACTIVE
trigger = previous target
│
│ MODIFY
▼
S2
ACTIVE
trigger = every 50,000 sales
│
│ DEFER
▼
S3
DEFERRED
trigger = every 50,000 sales
│
│ RESUME
▼
S4
ACTIVE
trigger = every 50,000 sales
```

其中：

- **Node** 表示一个 Requirement State；
- **Edge** 表示造成状态变化的 Requirement Event；
- Edge 可以通过 `event_id` 进一步追踪到对应的 `source_message`。

因此，可以表示为：

$$

S_r^{(0)}

\xrightarrow{E_r^{(1)}}

S_r^{(1)}

\xrightarrow{E_r^{(2)}}

S_r^{(2)}

\rightarrow

\cdots

\xrightarrow{E_r^{(n)}}

S_r^{(n)}

$$

需要特别强调：

> **Event 不是 State。**
> 

Event 表示“发生了什么变化”，State 表示“变化发生之后，现在是什么”。

例如：

```
MODIFY
```

本身并不能告诉我们 Requirement 当前的完整 value 和 scope。

只有将其与前面的 State 一起 replay：

```
Previous State
      +
MODIFY Event
      ↓
New State
```

才能得到新的完整 Requirement State。

### State Graph 与 target time

当后续 benchmark 在某个 target time $t^*$ *构建 evaluation instance 时，只需要找到 $t^*$* 之前最后一个已经发生的 Event。

定义：

$$
k_r^{(t^*)}=\max\left\{k\mid\operatorname{time}\left(E_r^{(k)}\right)\leq t^*\right\}
$$

则 Requirement $r$ 在 target time $t^*$ 上的 Gold State 为：

$$

G_r(t^*) =S_r^{\left(k_r^*(t^*)\right)}
$$

这与第 6 节中的定义：

$$

G_r(t^*) =\operatorname{Replay}\left(E_r^{\leq t^*}\right)
$$

是等价的。

因此，State Graph 只需要构建一次，之后就可以在不同的 target time $t^*$ 上快速获取对应的 Requirement Gold State。

---

# 8. Requirement State Graph and Gold State

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

## 8.1 Requirement State Graph

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
- $T$ 表示第 7 节定义的 State Transition Rules；
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

每一次 State transition 都由一个具体 Requirement Event 引起。

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

任何一个维度发生变化，都可以形成新的 State Node。

---

### 8.1.1 Node

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

### 8.1.2 Edge

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
  "source_message_id": 158
}
```

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

## 8.2 Requirement-level State Graph

每一个 Requirement Atom 都独立进行 replay，并在逻辑上形成一个 **Requirement-level State Graph**。

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

### 8.2.1 Graph Construction Rules

对于 Project 中的每一个 Requirement Atom，Requirement-level Graph 按照以下规则自动构建：

1. 读取该 Requirement 的全部 Stage 1 Events；
2. 按原始 project history 顺序排列 Events；
3. 根据第 7 节定义的 State Transition Rules 顺序 replay；
4. 每处理一个改变 Requirement State 的 Event，生成一个新的 State Node；
5. 使用该 Event 建立前一个 State Node 与新 State Node 之间的 Edge；
6. 重复以上步骤，直到该 Requirement 的全部 Events replay 完成；
7. 将构建完成的 Requirement-level Graph 加入当前 Project 的 `requirement_state_graph.json`。

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
    │ RESUME
    ↓
S4

S4
    │ RUNTIME_FAILURE
    ↓
S5
```

因此，Definition、Lifecycle、Uncertainty 和 Execution Events 都属于同一个 Requirement State Graph。

如果同一个 `source_message` 对同一 Requirement 产生多个 ordered Events，例如：

```
MODIFY
   ↓
RESUME
```

则按照 Stage 1 中确定的 Event order 依次 replay，并分别形成对应的 State transition。

Graph Construction 不重新判断 Event 是否正确，也不重新解释原始消息。

> **Stage 1 determines the Events; Stage 2 deterministically replays them.**
> 

如果可观察历史中 Requirement 的第一个 Event 并不是 `INTRODUCE`，Stage 2 不应人工补造不存在的历史 State。

只能根据当前可观察 evidence 构建第一个能够确定的 State；无法恢复的字段保持 `null`，而不是自动猜测。

---

## 8.3 Project-level Requirement State Graph

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

也不存在自动的 Family-level state propagation。

---

### 8.3.1 Project-level Graph Schema

每个 Project 最终生成一个：

```
requirement_state_graph.json
```

例如：

```json
{
  "project_id": "42204309",
  "project_title": "Project Rebuild MVP – Base NFT + Referral Engine + Fiat On-Ramp",

  "requirement_graphs": [
    {
      "graph_id": "REQ_SMALL_PRIZE_GRAPH",
      "requirement_id": "REQ_SMALL_PRIZE",
      "family_id": "PRIZE_MECHANICS",

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
          "source_message_id": 8
        },

        {
          "from_state_id": "REQ_SMALL_PRIZE_S001",
          "to_state_id": "REQ_SMALL_PRIZE_S002",
          "event_id": "REQ_SMALL_PRIZE_E002",
          "event_type": "MODIFY",
          "source_message_id": 158
        }
      ]
    },

    {
      "graph_id": "REQ_BIG_BLOCK_GRAPH",
      "requirement_id": "REQ_BIG_BLOCK",
      "family_id": "PRIZE_MECHANICS",

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
          "source_message_id": 20
        },

        {
          "from_state_id": "REQ_BIG_BLOCK_S001",
          "to_state_id": "REQ_BIG_BLOCK_S002",
          "event_id": "REQ_BIG_BLOCK_E002",
          "event_type": "REMOVE",
          "source_message_id": 195
        }
      ]
    }
  ]
}
```

因此，文件层面不存在：

```
requirement_graphs/
    REQ_SMALL_PRIZE.json
    REQ_BIG_BLOCK.json
    REQ_ETH_MINT.json
```

而是：

```
requirement_state_graph.json
│
└── requirement_graphs[]
      │
      ├── REQ_SMALL_PRIZE_GRAPH
      ├── REQ_BIG_BLOCK_GRAPH
      ├── REQ_ETH_MINT_GRAPH
      └── ...
```

这种设计具有几个优点：

1. 一个 Project 对应一个完整 State Graph artifact；
2. Project 内所有 Requirement trajectories 可以统一加载；
3. 后续查询任意 target time $t^*$ 时不需要读取多个文件；
4. 更容易进行 project-level consistency check；
5. 更方便由同一个 Project 自动生成多个 evaluation instances。

因此：

> **Requirement is the replay unit; Project is the graph storage unit.**
> 

---

## 8.4 Derived Gold State

Requirement State Graph 描述整个项目历史，而 benchmark evaluation 真正需要的是：

> **在某一个 target time $t^*$ 上，Agent 当时应该知道的正确 Requirement State 是什么？**
> 

该状态称为 **Derived Gold State**。

对于 Requirement $r$，只考虑 target time $t^*$ 之前已经发生的 Requirement Events：

$$

E_r^{\leq t^*}

$$

则 Requirement-level Gold State 定义为：

$$

G_r(t^*) =\operatorname{Replay}\left(E_r^{\leq t^*}\right)
$$

其中：

- $G_r(t^)$ *表示 Requirement $r$ 在 target time $t^*$* 上的 Gold State；
- $E_r^{\leq t^*}$ *表示在 $t^*$* 之前已经发生的 Requirement Events。

由于 `requirement_state_graph.json` 已经保存完整 State Graph，因此实际 Gold State retrieval 时不需要重新 replay 整个 Requirement history。

只需要在 Requirement-level Graph 中找到 $t^*$ 之前最后一个已经生成的 State Node。

定义：

$$
k_r(t^*)
=
\max\left\{
k \mid
\operatorname{time}\left(E_r^{(k)}\right)
\leq t^*
\right\}
$$

则：

$$

G_r(t^*) =S_r^{\left(k_r(t^*)\right)}
$$

这与：

$$

G_r(t^*) =\operatorname{Replay}\left(E_r^{\leq t^*}\right)
$$

完全等价。

因此：

```
requirement_state_graph.json
        ↓
select Requirement r
        ↓
locate target time t*
        ↓
find latest State Node before t*
        ↓
G_r(t*)
```

---

## 8.5 Requirement-level Gold State

Requirement-level Gold State 是某一个 Requirement-level Graph 在 target time $t^*$ 上取得的 State snapshot。

例如：

```json
{
  "requirement_id": "REQ_ETH_MINT",
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

如果 target time $t^*$ 位于后续 `IMPLEMENTATION_CLAIM` 之后，则同一个 Requirement 对应的 State Node 可能已经变为：

```json
{
  "requirement_id": "REQ_ETH_MINT",
  "state_id": "REQ_ETH_MINT_S003",

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
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that ETH minting has been fixed.",
    "source_event_id": "REQ_ETH_MINT_E005"
  },

  "supporting_event_ids": [
    "REQ_ETH_MINT_E001",
    "REQ_ETH_MINT_E004",
    "REQ_ETH_MINT_E005"
  ]
}
```

历史上的：

```
Execution = FAILED
```

并没有消失，而是保存在 `requirement_state_graph.json` 中此前的 State Node。

因此 Gold State 不需要额外重复保存：

```
previous_execution_status
previous_value
previous_scope
previous_lifecycle
```

如果后续 evaluation 需要历史状态，可以直接沿 State Graph 向前追踪。

核心原则为：

> **Graph stores history; Gold State stores the current snapshot.**
> 

---

## 8.6 Project-level Gold State

ReqMemBench 的 evaluation 是在 Project history 的某一个 target time $t^*$ 上进行的。

因此，需要将该时间点上所有**已经出现在可观察历史中的 Requirements** 的 Gold States 聚合为一个 **Project-level Gold State**。

定义：

$$

R_{\leq t^*}

$$

表示在 target time $t^*$ 之前已经至少出现过一个可观察 Event 的 Requirement 集合。

则 Project $P$ 在 target time $t^*$ 上的 Gold State 为：

$$
G_P(t^*)
=
\left\{
G_r(t^*)
\mid r \in R_r^{\leq t^*}
\right\}
$$

这里非常重要的一点是：

> **只有在 $t^*$ 之前已经出现在可观察 Project History 中的 Requirements 才能进入当前 Project Gold State。**
> 

如果某个 Requirement 的第一个可观察 Event 位于 $t^*$ 之后，那么该 Requirement 属于 future information，不能进入：

$$

G_P(t^*)

$$

否则会造成 benchmark leakage。

另一方面，如果某个 Requirement 已经在 $t^*$ 之前被 `REMOVE`，它仍然保留在 Project Gold State 中，例如：

```
REQ_BIG_BLOCK
lifecycle_status = REMOVED
```

原因是该 Requirement 已经属于当时可观察的历史，只是当前不再有效。

这些历史 Requirements 对后续 RQ3 判断：

```
ACTIVE
vs.
DEFERRED
vs.
REMOVED
```

非常重要。

因此：

> **Project Gold State contains all observed Requirements, not only currently ACTIVE Requirements.**
> 

---

### 8.6.1 Project-level Gold State Schema

一个 Project 可以对应多个不同的 evaluation target times：

$$

t_1^*, t_2^*, \ldots, t_m^*

$$

因此，`gold_states.json` 保存的是一个 Project 的多个 Project-level Gold State snapshots，而不是只有一个最终状态。

推荐结构：

```json
{
  "project_id": "42204309",

  "gold_states": [
    {
      "gold_state_id": "42204309_G001",

      "target_time": {
        "message_id": 250,
        "session_id": "S4",
        "milestone": "M3"
      },

      "requirement_states": [
        {
          "requirement_id": "REQ_SMALL_PRIZE",
          "state_id": "REQ_SMALL_PRIZE_S004",

          "attributes": {
            "winner_count": 1,
            "prize_amount_per_winner": "$500",
            "draw_condition": "every 100 sales"
          },

          "scope": {
            "persistence": "PROJECT_PERSISTENT",
            "components": ["SMART_CONTRACT", "BACKEND"],
            "contexts": ["PRIZE_SYSTEM"]
          },

          "lifecycle_status": "ACTIVE",

          "ambiguity": null,

          "execution": {
            "status": "VERIFIED_WORKING",
            "observed_behavior": "The prize mechanism was successfully verified in runtime testing.",
            "source_event_id": "REQ_SMALL_PRIZE_E008"
          },

          "supporting_event_ids": [
            "REQ_SMALL_PRIZE_E001",
            "REQ_SMALL_PRIZE_E003",
            "REQ_SMALL_PRIZE_E008"
          ]
        },

        {
          "requirement_id": "REQ_BIG_BLOCK",
          "state_id": "REQ_BIG_BLOCK_S003",

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
            "REQ_BIG_BLOCK_E003"
          ]
        }
      ]
    }
  ]
}
```

因此：

```
requirement_state_graph.json
```

保存的是：

> **整个 Project 的完整历史状态轨迹。**
> 

而：

```
gold_states.json
```

保存的是：

> **从该 Graph 在多个 target times 上取得的 Project snapshots。**
> 

例如：

```
requirement_state_graph.json
        │
        ├── t1* → G_P(t1*) → 42204309_G001
        ├── t2* → G_P(t2*) → 42204309_G002
        ├── t3* → G_P(t3*) → 42204309_G003
        └── ...
```

Project Gold State 本身不提前决定哪些 Requirements 与某一个具体 evaluation task 相关。

它只回答：

> **At target time $t^*$, what was the correct state of every Requirement already observed in the Project history?**
> 

后续 RQ1–RQ5 Instance Construction 再根据当前 task，从：

$$

G_P(t^*)

$$

中选择与当前 evaluation instance 相关的 Requirement States。

---

## 8.7 Gold State Retrieval

对于任意 target time $t^*$，Project Gold State 的自动获取过程如下：

```
① Select target time t*
        ↓
② Identify Requirements observed at or before t*
        ↓
③ Retrieve each Requirement's latest State Node
        ↓
④ Obtain Requirement Gold States G_r(t*)
        ↓
⑤ Aggregate Project Gold State G_P(t*)
        ↓
⑥ Save snapshot to gold_states.json
        ↓
⑦ Use Gold State for Benchmark Construction
```

---

### Step 1 — Select target time

首先确定 evaluation cutoff：

```
t*
```

在实际 Project 数据中，$t^*$ 应通过原始 project history 中的位置确定。

```json
{
  "message_id": 250,
  "session_id": "S4",
  "milestone": "M3"
}
```

其中：

- `message_id` 或 global message order 是主要时间定位依据；
- `session_id` 用于描述所在工作阶段；
- `milestone` 用于保留更高层的项目阶段信息。

---

### Step 2 — Exclude Future Events

对于每个 Requirement，只允许使用：

$$

E_r^{\leq t^*}

$$

任何发生在 $t^*$ 之后的 Event：

$$

E_r^{> t^*}

$$

都不能影响当前 Gold State。

例如：

```
S2
 │
 │ MODIFY E3
 ▼
S3
 │
 │
 ★ t*
 │
 │
 │ REMOVE E4
 ▼
S4
```

在 $t^*$ 上，当前最新 State 是：

```
S3
Lifecycle = ACTIVE
```

不能因为 State Graph 中已经保存未来的：

```
REMOVE E4
```

就提前得到：

```
Lifecycle = REMOVED
```

因此：

> State Graph 可以保存完整未来历史，但 Gold State Retrieval 必须严格遵守 target time $t^*$。
> 

---

### Step 3 — Retrieve Latest State Node

对于每一个 Requirement $r$，在 `requirement_state_graph.json` 中找到对应的 Requirement-level Graph。

然后寻找 $t^*$ 之前最后一个 Event：

$$
k_r(t^*)
=
\max\left\{
k \mid
\operatorname{time}\left(E_r^{(k)}\right)
\leq t^*
\right\}
$$

对应的 Gold State 为：

$$

G_r(t^*) =S_r^{\left(k_r(t^*)\right)}
$$

如果 Requirement $r$ 在 $t^*$ 之前没有任何可观察 Event，则：

$$

r \notin R_{\leq t^*}

$$

因此该 Requirement 不进入当前 Project Gold State。

---

### Step 4 — Aggregate Project Gold State

对所有：

$$

r \in R_{\leq t^*}

$$

重复 State Retrieval。

最终得到：

$$
G_P(t^*)
=
\left\{
G_r(t^*)
\mid r \in R_r^{\leq t^*}
\right\}
$$

该对象即为当前 target time $t^*$ 的 Project-level Gold State。

---

### Step 5 — Save Gold State

每一个选定的 target time $t^*$ 都生成一个新的 Gold State snapshot。

例如：

```
t1* → 42204309_G001
t2* → 42204309_G002
t3* → 42204309_G003
```

所有 snapshots 统一保存在：

```
gold_states.json
```

中，而不是分别创建大量独立 Gold State 文件。

因此，一个 Project 的 Stage 2 数据关系为：

```
requirement_state_graph.json
        │
        │ query at different t*
        │
        ├──────────────→ G_P(t1*)
        │
        ├──────────────→ G_P(t2*)
        │
        ├──────────────→ G_P(t3*)
        │
        └──────────────→ ...
                         │
                         ▼
                  gold_states.json
```

---
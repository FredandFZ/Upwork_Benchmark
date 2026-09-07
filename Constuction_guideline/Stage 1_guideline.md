# Stage 1_guideline

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
Event Verification
        ↓
Ambiguity Linking
        ↓
Value / Scope / Lifecycle / Ambiguity / Execution Evolution
```

这一阶段的目标是从完整项目对话中识别：

- 项目的时间与 Session 结构；
- 主要的 Requirement Families；
- 可以独立演化的 Requirements；
- 每个 Requirement 在历史中的关键 Events；
- 每个 `AMBIGUOUS` Event 何时被哪个后续 Event 明确解决；
- Requirement 的 Value、Scope、Lifecycle、Ambiguity 和 Execution 如何随时间变化。

```
Project Annotation
        ↓
Requirement State Graph
        ↓
Derived Current Gold State
        ↓
RQ1–RQ4 Evaluation Instances
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
  "annotation_version": "v0.6",

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
          "execution": null,
          "resolves_ambiguity_event_ids": null
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
          "execution": null,
          "resolves_ambiguity_event_ids": null
        }
      ]
    }
  ]
}
```

这一 Schema 只保存项目历史中需要直接标注的信息。后续的 Current Requirement State、Requirement State Graph 和 RQ1–RQ4 Evaluation Instances 均由这些标注自动推导。

每个最终 Event 都必须包含 `resolves_ambiguity_event_ids`。普通 Event 使用 `null`；只有当该 Event 明确解决了同一 Requirement 中更早的一个或多个 `AMBIGUOUS` Events 时，才写入对应 Event ID 数组。Stage 2 只根据这些显式链接关闭 ambiguity，不再根据 Event 类型或 ambiguity dimension 自动猜测。

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
AMBIGUOUS → open_ambiguities[ambiguity_event_id].status = OPEN
```

如果连受影响的是哪个 Requirement 都无法可靠判断，则进入 annotation review / human adjudication。

最终原则是：

> **Requirement Family provides optional semantic organization, while every actual state change belongs directly to a specific Requirement Atom.**
> 

# 5. Event

ReqMemBench 中，`Event` 表示一条历史消息对某个具体 Requirement 造成的**有效状态变化或重要状态证据**。Event 是 Requirement Lifecycle 的最基本组成单位，也是后续进行 Requirement replay、恢复当前 Gold State 以及生成 RQ1–RQ4 evaluation instances 的核心输入。

为了降低 LLM 标注复杂度，Event Annotation 采用固定结构。每个最终 Event 始终包含以下九个字段：

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
  
  "value_removals": null,

  "scope_updates": null,

  "ambiguity": null,

  "execution": null,

  "resolves_ambiguity_event_ids": null
}
```

下文为了突出某一规则，部分 Event 片段会省略未讨论的 `null` 字段；实际最终 JSON 仍必须包含上述全部 canonical fields。

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

| Category | `event_type` | `value_updates` | `scope_updates` | `ambiguity` | `execution` | `resolves_ambiguity_event_ids` | Lifecycle State | Ambiguity State | 含义 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Definition | `INTRODUCE` | ✅ 通常填写 | ✅ 可填写 | `null` | `null` | `null` 或显式 IDs | → `ACTIVE` | 仅关闭所引用的 OPEN ambiguities | Requirement 第一次被明确建立 |
| Definition | `MODIFY` | ✅ 可填写 | ✅ 可填写 | `null` | `null` | `null` 或显式 IDs | 通常保持不变 | 仅关闭所引用的 OPEN ambiguities | 已有 Requirement 的 Value、Scope 或两者被明确修改 |
| Lifecycle | `DEFER` | `null` | `null` | `null` | `null` | `null` 或显式 IDs | → `DEFERRED` | 仅关闭所引用的 OPEN ambiguities | Requirement 仍然存在，但当前阶段暂时不执行 |
| Lifecycle | `RESUME` | `null` | `null` | `null` | `null` | `null` 或显式 IDs | `DEFERRED → ACTIVE`，或保持 `ACTIVE` | 仅关闭所引用的 OPEN ambiguities | 恢复暂缓的 Requirement，或确认继续沿用原 Requirement |
| Lifecycle | `REMOVE` | `null` | `null` | `null` | `null` | `null` 或显式 IDs | → `REMOVED` | 仅关闭所引用的 OPEN ambiguities | Client 明确表示不再需要整个 Requirement |
| Uncertainty | `AMBIGUOUS` | `null` | `null` | ✅ 必须填写 | `null` | `null` | **不直接改变** | 新增一个 keyed OPEN ambiguity | 当前存在无法安全解决的 Value、Scope 或 Lifecycle uncertainty |
| Execution | `IMPLEMENTATION_CLAIM` | `null` | `null` | `null` | ✅ 必须填写 | `null` | 不改变 | 不改变 | Freelancer 声称已经实现或修复 Requirement，但尚未运行验证 |
| Execution | `RUNTIME_FAILURE` | `null` | `null` | `null` | ✅ 必须填写 | `null` | 不改变 | 不改变 | 实际运行或测试证明当前 implementation 没有满足 Requirement |
| Execution | `RUNTIME_VERIFICATION` | `null` | `null` | `null` | ✅ 必须填写 | `null` | 不改变 | 不改变 | 实际运行或测试确认 Requirement 已被正确实现 |

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

**标注原则**

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

`value_updates` 只记录当前消息明确建立或修改的值，但是不输出删除的值，不需要重新输出整个 Requirement State。

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

#### `value_removals`

`value_removals` 记录某个 `MODIFY` Event 中，Requirement 当前 State 里已经不再成立、需要被**删除的 attribute 名称**。

它解决的不是“把一个属性改成新值”，而是：

> 该属性描述的业务规则已经被取消、替代，或不再适用于当前 Requirement。
> 

字段格式：

```
{
  "value_removals": null
}
```

或：

```
{
  "value_removals": [
  "claim_interaction",
  "manual_claim_deadline"
]
}
```

例如，原 Requirement State 为：

```
prize_payout_mode = manual claim
claim_interaction = one-click claim on projectrebuild.xyz
manual_claim_deadline = 30 days after draw
```

Client 后续说：

> Prize payouts should now be transferred automatically to the winner wallet. No claim action is needed.
> 

则 Event 应为：

```
{
  "event_type": "MODIFY",

  "value_updates": {
    "prize_payout_mode": "automatic transfer to the winner wallet"
  },

  "value_removals": [
    "claim_interaction",
    "manual_claim_deadline"
  ],

  "scope_updates": null,
  "ambiguity": null,
  "execution": null
}
```

Replay：

```
ACTIVE
prize_payout_mode = manual claim
claim_interaction = one-click claim
manual_claim_deadline = 30 days

        ↓ MODIFY

ACTIVE
prize_payout_mode = automatic transfer to the winner wallet
```

最终 State：

```
prize_payout_mode = automatic transfer to the winner wallet
```

`claim_interaction` 和 `manual_claim_deadline` 已被从 State 中移除，不应继续保留为过期属性。

`value_removals` 与“属性值写成 `removed`”的区别是：

- `value_removals: ["big_block_eligibility_window"]`：表示该 attribute 已从当前 Requirement State 中删除，replay 后不再存在。
- `"big_block_eligibility_window": "removed"`：表示 attribute 仍存在，只是它的值为 `"removed"`；这通常适合保留“被移除”这一历史或状态信息的场景。

因此，只有当 attribute 本身已经不应存在于当前 State 时，才使用 `value_removals`。

其中 `null` 表示：

> 当前 Event 没有删除任何 attribute。
> 

而空数组 `[]` 也不应作为正常标注结果使用；若没有要删除的属性，应使用 `null`。

---

#### `MODIFY` 与 ambiguity resolution

`MODIFY` 还可能解决此前存在的 ambiguity，但“发生了 `MODIFY`”本身不等于“ambiguity 已解决”。只有当该 Event 的语义确实回答了某个更早 `AMBIGUOUS` Event 的具体问题，并通过 `resolves_ambiguity_event_ids` 显式引用该 Event 时，Stage 2 才关闭它。

例如此前：

```
REQ_PAYMENT_PROVIDER_E002 = AMBIGUOUS
payment_provider = Coinbase Commerce
open_ambiguities[REQ_PAYMENT_PROVIDER_E002].status = OPEN
open_ambiguities[REQ_PAYMENT_PROVIDER_E002].dimension = VALUE
```

Client 后续明确：

> Use Transak instead.
> 

则可以产生：

```
{
  "event_id": "REQ_PAYMENT_PROVIDER_E003",
  "event_type": "MODIFY",

  "value_updates": {
    "payment_provider": "Transak"
  },

  "scope_updates": null,
  "ambiguity": null,
  "execution": null,
  "resolves_ambiguity_event_ids": [
    "REQ_PAYMENT_PROVIDER_E002"
  ]
}
```

Replay 后：

```
ACTIVE
payment_provider = Coinbase Commerce
open_ambiguities = {
  REQ_PAYMENT_PROVIDER_E002: OPEN
}

        ↓ MODIFY

ACTIVE
payment_provider = Transak
open_ambiguities = {}
```

因为 Client 已经提供了足够的新信息，原来的 Value ambiguity 被解决。

相反，如果中间 `MODIFY` 改的是同一 Requirement 中的另一个属性，它必须保持：

```json
"resolves_ambiguity_event_ids": null
```

例如，`E002` 询问 prize delivery 是手动 claim 还是自动转账，`E003` 只修改 prize-draw 金额，而 `E004` 才明确自动转账，则：

```text
E002 AMBIGUOUS
  → OPEN

E003 MODIFY prize-draw amounts
  resolves_ambiguity_event_ids = null
  → E002 继续 OPEN

E004 MODIFY reward-delivery mode
  resolves_ambiguity_event_ids = ["REQ_PRIZE_CLAIM_FLOW_E002"]
  → 只在 E004 关闭 E002
```

禁止使用以下 heuristic：

```text
任意 VALUE MODIFY → 关闭所有 VALUE ambiguity
任意 SCOPE MODIFY → 关闭所有 SCOPE ambiguity
Requirement 中出现后续 MODIFY → 关闭最近 ambiguity
```

Ambiguity resolution 必须是 Event-ID-level 的显式关系，而不是仅依靠 dimension 或时间接近度推断。

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
  "execution": null,
  "resolves_ambiguity_event_ids": null
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

如果 `RESUME` 解决 ambiguity，还必须通过 `resolves_ambiguity_event_ids` 指向被解决的具体 `AMBIGUOUS` Event；没有显式链接时，`RESUME` 只执行 lifecycle transition，不会关闭任何 ambiguity。

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
  "execution": null,
  "resolves_ambiguity_event_ids": null
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
open_ambiguities = {}
```

随后 Freelancer 发现：

> Coinbase Commerce can't support direct card payment.
> 

这会产生 `AMBIGUOUS` Event，之后得到：

```
Lifecycle = ACTIVE
payment_provider = Coinbase Commerce

open_ambiguities[REQ_PAYMENT_PROVIDER_E002].status = OPEN
open_ambiguities[REQ_PAYMENT_PROVIDER_E002].dimension = VALUE
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
  "event_id": "REQ_PAYMENT_PROVIDER_E003",
  "event_type": "RESUME",
  "value_updates": null,
  "scope_updates": null,
  "ambiguity": null,
  "execution": null,
  "resolves_ambiguity_event_ids": [
    "REQ_PAYMENT_PROVIDER_E002"
  ]
}
```

Replay：

```
ACTIVE
payment_provider = Coinbase Commerce
open_ambiguities = {
  REQ_PAYMENT_PROVIDER_E002: OPEN
}

        ↓ RESUME

ACTIVE
payment_provider = Coinbase Commerce
open_ambiguities = {}
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

如果同一条消息既明确修改 Value/Scope，又通过该修改回答了 ambiguity，应只创建携带 resolution link 的 `MODIFY`，不应再为同一语义额外创建一个冗余 `RESUME`：

```text
正确：MODIFY + resolves_ambiguity_event_ids

错误：MODIFY + RESUME
      （两者来自同一消息并表达同一次 ambiguity resolution）
```

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

如果 `REMOVE` 同时明确解决了此前“保留、暂缓还是删除”的 lifecycle ambiguity，则在该 `REMOVE` 上写入对应的 `resolves_ambiguity_event_ids`。普通 `REMOVE` 使用 `null`；`REMOVE` 不会因为生命周期结束而自动清除未被引用的其他 ambiguity。

---

### 5.3.6 `AMBIGUOUS`

`AMBIGUOUS` 表示：

> **当前历史中出现了一个无法根据已有信息安全解决、并且可能影响 Agent 下一步行为的冲突或不确定性。**
> 

`AMBIGUOUS` 与其他 Lifecycle Event 最大的区别是：

> **它不直接改变 Requirement Lifecycle State。**
> 

`AMBIGUOUS` 可以来自 Client，也可以来自 Freelancer。判断标准不是 speaker，而是该消息是否对一个可识别 Requirement 产生了无法安全确定的 Value、Scope 或 Lifecycle uncertainty。Client 的犹豫、互相冲突的指令或未作决定的选择，同样可以产生 `AMBIGUOUS`。

例如 Requirement 当前是：

```
Lifecycle = ACTIVE
```

发生 `AMBIGUOUS` 后仍然可以保持：

```
Lifecycle = ACTIVE
```

变化的是独立的 Ambiguity State。每个 `AMBIGUOUS` Event 使用自己的 `event_id` 打开一条独立记录：

```
open_ambiguities[ambiguity_event_id].status = OPEN
```

因此标准 replay 为：

```
ACTIVE
open_ambiguities = {}

        ↓ AMBIGUOUS

ACTIVE
open_ambiguities = {
  REQ_EXAMPLE_E003: OPEN
}
```

当该 `OPEN` ambiguity 与当前 evaluation task 相关，并阻止 Agent 安全决定下一步时，后续 RQ4 自动派生：

```
Agent Action = CLARIFY
```

因此完整逻辑是：

```
AMBIGUOUS Event
        ↓
open_ambiguities[event_id].status = OPEN
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

`AMBIGUOUS` Event 自身的 `resolves_ambiguity_event_ids` 必须为 `null`。它负责打开新的 ambiguity，不负责关闭自己或其他 ambiguity。

Stage 2 replay 遇到 `AMBIGUOUS` Event 后，自动生成：

```json
{
  "ambiguity": {
    "REQ_EXAMPLE_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "...",
      "source_event_id": "REQ_EXAMPLE_E003"
    }
  }
}
```

其中：

- `status = OPEN`：当前 ambiguity 尚未解决；
- `dimension`：ambiguity 所影响的 Requirement State 维度；
- `description`：Stage 1 已标注的不确定性说明；
- `source_event_id`：产生该 ambiguity 的 Event，用于 provenance。

同一 Requirement 可以同时存在多个 OPEN ambiguities，因此 Stage 2 内部维护的是：

```text
open_ambiguities: dict[event_id, ambiguity_state]
```

而不是单一的 `state.ambiguity` 槽位。后续 resolver 只关闭 `resolves_ambiguity_event_ids` 中列出的条目；未被列出的其他 ambiguity 继续保持 OPEN。

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
open_ambiguities = {}
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

  "execution": null,
  "resolves_ambiguity_event_ids": null
}
```

Replay：

```
ACTIVE
payment_provider = Coinbase Commerce
open_ambiguities = {}

        ↓ AMBIGUOUS

ACTIVE
payment_provider = Coinbase Commerce
open_ambiguities[REQ_PAYMENT_PROVIDER_E002].status = OPEN
open_ambiguities[REQ_PAYMENT_PROVIDER_E002].dimension = VALUE
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
open_ambiguities[REQ_PAYMENT_PROVIDER_E002] = OPEN
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

  "execution": null,
  "resolves_ambiguity_event_ids": null
}
```

Replay：

```
ACTIVE
contexts = [LANDING_PAGE_ACCESS]
open_ambiguities = {}

        ↓ AMBIGUOUS

ACTIVE
contexts = [LANDING_PAGE_ACCESS]
open_ambiguities[REQ_MAURITIUS_GEOBLOCK_E002].status = OPEN
open_ambiguities[REQ_MAURITIUS_GEOBLOCK_E002].dimension = SCOPE
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

  "execution": null,
  "resolves_ambiguity_event_ids": null
}
```

假设此前 Lifecycle 为 `ACTIVE`，Replay：

```
ACTIVE
open_ambiguities = {}

        ↓ AMBIGUOUS

ACTIVE
open_ambiguities[REQ_REFERRAL_FEATURE_E002].status = OPEN
open_ambiguities[REQ_REFERRAL_FEATURE_E002].dimension = LIFECYCLE
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
keep it      → RESUME + resolves_ambiguity_event_ids
leave it     → DEFER + resolves_ambiguity_event_ids
remove it    → REMOVE + resolves_ambiguity_event_ids
change it    → MODIFY + resolves_ambiguity_event_ids
```

这里的 `resolves_ambiguity_event_ids` 必须指向产生该 lifecycle uncertainty 的具体 `AMBIGUOUS` Event。如果后续 Event 只处理同一 Requirement 的其他问题，则该字段仍为 `null`，原 ambiguity 继续 OPEN。

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

**`observed_behavior`**

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

**`observed_behavior` 必须具体，**应记录实际观察到的行为

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
- 构建 RQ4 Requirement-to-Code evaluation；
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

## 5.4 `resolves_ambiguity_event_ids`

`resolves_ambiguity_event_ids` 是最终 Stage 1 Event 的 canonical field，用于表达：

> **当前 Event 明确解决了同一 Requirement 中哪些更早的 `AMBIGUOUS` Events。**

没有解决 ambiguity 时：

```json
"resolves_ambiguity_event_ids": null
```

解决一个 ambiguity 时：

```json
"resolves_ambiguity_event_ids": [
  "REQ_ABOUT_PAGE_CONTENT_E002"
]
```

一个 Event 同时解决多个独立 ambiguities 时，可以列出多个 ID：

```json
"resolves_ambiguity_event_ids": [
  "REQ_EXAMPLE_E002",
  "REQ_EXAMPLE_E004"
]
```

允许携带 resolution links 的 resolver Event 类型只有：

```text
INTRODUCE
MODIFY
DEFER
RESUME
REMOVE
```

`AMBIGUOUS` 和 Execution Events 不能作为 resolver。每条链接必须满足：

1. 引用目标真实存在；
2. 引用目标与 resolver 属于同一个 Requirement；
3. 引用目标在 resolver 之前；
4. 引用目标的 `event_type` 是 `AMBIGUOUS`；
5. 数组非空且没有重复 ID；
6. 同一个 ambiguity 最多被一个后续 Event 解决；
7. resolver 的语义确实回答了该 ambiguity，而不只是时间上更晚或 dimension 相同。

该字段表达的是精确的 closure relation：

```text
AMBIGUOUS Event ID
        ↓ referenced by
resolver.resolves_ambiguity_event_ids
        ↓
close exactly this OPEN ambiguity
```

旧标注若缺少该字段，加载时可以规范化为 `null`。缺少链接意味着 ambiguity 保持 OPEN，绝不能继续使用旧的 dimension heuristic 猜测它已经解决。

---

# 6. AMBIGUITY_LINKING

## 6.1 Pipeline 位置与职责

Ambiguity resolution 不在 Event Extraction 时凭局部上下文直接猜测，而是在 Events 完成 verification 后由独立的 `AMBIGUITY_LINKING` 阶段处理：

```text
EVENT_VERIFICATION
        ↓
应用 KEEP / EDIT / DELETE
        ↓
按聊天顺序确定性排序
        ↓
预分配最终 Event IDs
        ↓
只选择仍含 AMBIGUOUS 的 Requirements
        ↓
AMBIGUITY_LINKING
        ↓
应用结构合法且 HIGH-confidence 的 resolution links
        ↓
Final Assembly
        ↓
Final Validation
```

ID 预分配与 Final Assembly 必须使用同一个排序函数，保证 linker 看到的 Event ID 与最终 JSON 完全一致。

`AMBIGUITY_LINKING` 是一个窄职责审查层。它只判断每个 ambiguity 在何时被解决，并且：

- 不增加、删除、编辑、合并、拆分或移动 Event；
- 不修改 Requirement ontology、title 或 family；
- 不重新判断或重新锚定 source evidence；
- 不审查没有 `AMBIGUOUS` Event 的 Requirements；
- 必须为目标 Requirement 中每个 `AMBIGUOUS` Event 输出一条决定。

## 6.2 Resolution test

Linker 首先识别 ambiguity 影响的精确状态路径，例如：

```text
attributes.process_reward_delivery_copy
scope.components
scope.contexts
scope.persistence
lifecycle_status
```

然后按时间顺序检查后续潜在 resolver。只有后续 Event 自身的语义直接、完整地确定了同一个 uncertain choice、value、scope boundary 或 lifecycle question，才算解决。

以下条件都不足以单独证明 resolution：

- Event 是一个 `MODIFY`；
- Event 修改了同一 Requirement 的其他 attribute；
- Event 与 ambiguity 同属 `VALUE`、`SCOPE` 或 `LIFECYCLE` dimension；
- Event 在时间上靠近 ambiguity；
- Event 是泛化确认或简单 acknowledgement；
- Event 只是 implementation claim、runtime failure 或 runtime verification；
- Event 重述问题，但没有选择答案。

对于看似可能解决但实际修改无关状态的中间 Event，记录为 `non_resolving_intermediate_event_ids`，并继续向后搜索。选择最早一个明确且完整的 resolver；若后续没有任何 Event 解决它，则输出 `UNRESOLVED`。

## 6.3 Linking 决定与项目级报告

每个 ambiguity 的完整决定保存为：

```json
{
  "ambiguity_event_id": "REQ_ABOUT_PAGE_CONTENT_E002",
  "affected_state_paths": [
    "attributes.process_reward_delivery_copy"
  ],
  "resolution_status": "RESOLVED",
  "resolver_event_id": "REQ_ABOUT_PAGE_CONTENT_E004",
  "non_resolving_intermediate_event_ids": [
    "REQ_ABOUT_PAGE_CONTENT_E003"
  ],
  "decision_note": "E003 changes prize-draw amounts; E004 resolves automatic versus claim-based reward delivery.",
  "confidence": "HIGH"
}
```

如果没有 resolver：

```json
{
  "ambiguity_event_id": "REQ_EXAMPLE_E002",
  "affected_state_paths": [
    "attributes.example_attribute"
  ],
  "resolution_status": "UNRESOLVED",
  "resolver_event_id": null,
  "non_resolving_intermediate_event_ids": [],
  "decision_note": "No later Event settles the uncertain value.",
  "confidence": "HIGH"
}
```

完整决定汇总到项目级 `ambiguity_linking.json`，逐 Requirement checkpoint 保存在 `ambiguity_linking/<requirement_id>.json`。最终 annotation 不复制 `affected_state_paths`、中间 Event、decision note 或 confidence，只在 resolver Event 上保留精简后的 `resolves_ambiguity_event_ids`。

## 6.4 自动应用与 human review

只有以下条件全部满足，Pipeline 才自动写入 resolution link：

- `resolution_status == "RESOLVED"`；
- `confidence == "HIGH"`；
- ambiguity 与 resolver Event 都存在；
- 两者属于同一个 Requirement；
- resolver 晚于 ambiguity；
- 目标类型确实为 `AMBIGUOUS`；
- resolver 类型属于允许集合；
- 同一个 ambiguity 没有被重复解决。

`MEDIUM`、`LOW`、缺失决定、重复决定或结构不合法的结果不会部分应用：ambiguity 保持 OPEN，并写入 `human_review.json`。一个 resolver 可以解决多个 ambiguities，但每个 ambiguity 仍需独立决定。

## 6.5 Final validation

Final validator 必须检查：

- 每个 Event 都包含 `resolves_ambiguity_event_ids`；
- 值为 `null` 或非空、无重复的字符串数组；
- 所有引用都存在且位于同一 Requirement；
- 引用目标是更早的 `AMBIGUOUS` Event；
- 同一个 ambiguity 最多被解决一次；
- resolver Event 类型合法；
- Event 删除或重编号后不存在悬空引用；
- 没有 resolver 的 ambiguity 可以一直保持 OPEN；
- 不使用 dimension-based fallback 自动关闭 ambiguity。


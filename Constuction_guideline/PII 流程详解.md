# PII 清洗流程详解（v7.0）

## 1. 文档目标与边界

本文说明 `Datasets/project` → `Datasets/PII_clean_project` 的去标识化流程设计：七个阶段
各自的职责、跨阶段数据结构、断点续跑的失效级联、失败处理与 Agent 修复闭环，以及最终产物
必须满足的硬不变量。

**不在本文范围**：Prompt 正文（见 `prompt/PII/`）、命令行用法（见
`Code/insturctions/README_PII_Clean.md`）。本文也不包含任何真实 PII 样例。

### 1.1 输入与输出

```text
Datasets/project/<project_id>/          Datasets/PII_clean_project/<project_id>/
├── chat_messages.json          ──►     ├── chat_messages.json     已清洗
├── job.txt                     ──►     ├── job.txt                原样复制
├── job_metadata.csv            ──►     ├── job_metadata.csv       原样复制
├── milestones.json             ──►     ├── milestones.json        原样复制
└── deliverables/...            ──►     └── deliverables/...       原样复制
```

程序只改写 `chat_messages.json`，且只改三个字段：

| 字段 | 处理 |
|---|---|
| `message` | 语义改写 + 合成替换 |
| `sender_id` | 运行期作为审计输入，**写出时整字段删除** |
| `created_ts` | **写出时整字段删除** |
| 其他字段（如 `message_user_type`） | 逐字节不变 |

> **明示：`chat_messages.json` 以外的文件并未脱敏。** 它们被原样复制。这是本流程的既定
> 范围，不是遗漏。若下游会消费 `job.txt`、`milestones.json` 或 `deliverables/`，这些文件
> 仍可能含真实 PII。

---

## 2. 最终数据集目标

1. 不含真实 PII。
2. 不含真实 API Key / Token / Password / Secret。
3. PII 替换为**自然的虚构内容**，而不是在最终产物里保留 `[EMAIL_001]` 这类占位符。
4. 凭据替换为**确定无效**的假凭据。
5. **公共第三方工具与技术名称默认保留**（GitHub、Stripe、AWS、Brevo、OAuth、ERC-721 …）。
6. 项目名、人物、邮箱、私有 URL、地址、业务数值、日期按语义做合成替换。
7. 长消息（≥5 词）必须显著改变句式与组织方式。
8. 短消息（3–4 词，以及任何携带 PII/secret/业务值的 1–2 词消息）也必须改动。
9. Requirement / Decision / Ambiguity / Execution 等核心语义保持不变。
10. 同一实体与同一 Requirement Value 在整个项目历史中保持一致。

第 3 条与第 5 条是与 v6.0 相反的方向：v6.0 在最终产物里保留占位符，并**强制替换**真实
公共服务名。v7.0 取消占位符、保留公共名，因为公共工具名本身是 Requirement 的组成部分。

---

## 3. 整体流程

```text
                     Datasets/project/<pid>/chat_messages.json
                                      |
        +-----------------------------+------------------------------+
        |  Phase 0  安全与 PII 发现                                   |
        |     0A  本地 Secret 屏蔽        （本地，无模型）              |
        |     0B  LLM PII 发现            （仅分类，不改写）            |
        +-----------------------------+------------------------------+
                                      |
        +-----------------------------+------------------------------+
        |  Phase 1  语义发现                                          |
        |     1A  逐条语义抽取            （业务值 → semantic slot）    |
        |     1B  项目级语义合并          （线性 fold，历史与数学约束）  |
        +-----------------------------+------------------------------+
                                      |
        +-----------------------------+------------------------------+
        |  Phase 2  项目级合成方案        （一份全项目一致的 plan）      |
        +-----------------------------+------------------------------+
                                      |
        +-----------------------------+------------------------------+
        |  Phase 3  改写                                              |
        |     3A  短消息改写              3B  长消息改写                |
        +-----------------------------+------------------------------+
                                      |
        +-----------------------------+------------------------------+
        |  Phase 4  独立语义校验          （PASS / 结构化 findings）     |
        +-----------------------------+------------------------------+
                                      |  FAIL
        +-----------------------------+------------------------------+
        |  Phase 5  定向修复              （≤2 次，仍失败则隔离）        |
        +-----------------------------+------------------------------+
                                      |
        +-----------------------------+------------------------------+
        |  Phase 6  渲染与安全审计        （本地）                      |
        |     6A  确定性假凭据渲染        6B  硬失败审计                |
        +-----------------------------+------------------------------+
                                      |
                        最终 chat_messages.json（或：不提交）
```

### 3.1 阶段职责与执行位置

| 阶段 | 回答的问题 | 执行者 |
|---|---|---|
| 0A | 哪些内容是**凭据**？ | 本地代码 |
| 0B | 哪些内容是 PII？ | LLM（仅分类） |
| 1A | 每条消息的业务值各代表什么参数？ | LLM |
| 1B | 整个项目的参数、历史与数学约束是什么？ | LLM（线性 fold） |
| 2 | 全项目统一换成哪些新身份与新数值？ | LLM（分块 + 本地组装） |
| 3 | 如何把对话重写成不同表达？ | LLM |
| 4 | 改写后语义有没有变？ | 独立 LLM |
| 5 | 只修复已发现的具体错误 | LLM |
| 6 | 生成假凭据，并确认真实信息全部消失 | 本地代码 |

设计原则：**本地正则负责候选提名、非强制提示与 fail-closed 验收；语义判断交给读过完整
消息的模型；凭据的生成与最终审计回到本地。**

### 3.2 模块与职责

| 文件 | 职责 |
|---|---|
| `Code/PII/_compat.py` | 唯一的双导入垫片，转发 `stage1` 的存储与 API 客户端 |
| `Code/PII/errors.py` | 异常层级；`PiiValidationError` 继承 `ValueError` 以获得重试与脱敏 |
| `Code/PII/config.py` | 阶段常量、`UPSTREAM` DAG、run_mode、分桶阈值、`PiiConfig` |
| `Code/PII/models.py` | 跨阶段 frozen dataclass 契约；纯数据 |
| `Code/PII/textutil.py` | 全部正则、文本谓词、分桶、结构改写判定、规范化哈希 |
| `Code/PII/prompts.py` | 加载 `prompt/PII/`，内联 shared fragment，逐阶段哈希 |
| `Code/PII/checkpoints.py` | `CheckpointStore`：信封、`input_hash` 链、恢复五层校验 |
| `Code/PII/ledger.py` | 未解决台账、诊断脱敏、运行状态机 |
| `Code/PII/llm.py` | 请求装配、强制脱敏器、**唯一**的 batch→逐条降级实现 |
| `Code/PII/secret_shield.py` | Phase 0A 屏蔽 + Phase 6A 确定性渲染 |
| `Code/PII/phase0b_entities.py` | Phase 0B 校验 + 本地确定性实体 ID 与 bundle 归并 |
| `Code/PII/phase1a_semantics.py` | Phase 1A 抽取与校验 |
| `Code/PII/phase1b_consolidate.py` | Phase 1B fold、历史链校验、`Decimal` 关系求值 |
| `Code/PII/phase2_plan.py` | Phase 2 分块、校验、本地组装、**`plan_slice` 闭包** |
| `Code/PII/phase3_rewrite.py` | Phase 3 分桶与**共用改写校验门** |
| `Code/PII/phase4_verify.py` | Phase 4 verdict 校验 + 本地守卫否决 |
| `Code/PII/phase5_repair.py` | Phase 5 定向修复 |
| `Code/PII/phase6_render.py` | Phase 6A 渲染 + 6B 审计（纯函数） |
| `Code/PII/discovery.py` | 项目发现、chat 读写、字段不变量 |
| `Code/PII/agent_handoff.py` | Agent 任务包与提交校验（双哈希守卫） |
| `Code/PII/pipeline.py` | 阶段编排、checkpoint 接线、阶段组屏障 |
| `Code/PII/finalize.py` | 离线 finalize：合并修复 → 渲染 → 审计 → 提交 |
| `Code/pii_clean.py` | CLI：主流水线 |
| `Code/pii_finalize.py` | CLI：离线 finalize |

`pipeline.py` 中不出现正则、Prompt 正文与响应解析；各 phase 模块之间互不导入，只通过
`models.py` 通信。

---

## 4. Phase 0 — 安全与 PII 发现

### 4.1 Phase 0A 本地 Secret 屏蔽

只处理**授予访问权限**的值：API Key、API Secret、Password、Access / Refresh / Bearer
Token、SMTP 凭据、Private Key、Seed Phrase、Webhook Secret。

用户名、登录名、账号标识**不在**此列 —— 它们是 PII 而非凭据，交给 0B 发现、Phase 2 合成
成自然身份（合成用户名比 `FAKE_ACCOUNT_…` 可读得多）。

检测信号（命中即屏蔽）：

| 信号 | 说明 | 是否需要上下文关键词 |
|---|---|---|
| PEM 私钥块 | `-----BEGIN ... PRIVATE KEY-----` | 否 |
| 凭据赋值 | `password:`、`api key =`、`token is` 后的取值 | 否 |
| `Authorization: Bearer` | 请求头形态 | 否 |
| JWT | 三段 base64 结构 | 否 |
| 结构化前缀 | 只可能出现在凭据前的前缀形态 | 否 |
| Seed phrase | 与助记词关键词同现的长小写词串 | 是 |
| 通用高熵 token | 长度 ≥20、≥3 字符类、含数字、熵 ≥3.2 | **是** |

命中后替换为 `<SECRET_CANDIDATE:S001>` 内部 token；真值只在内存中存在，**注册表只落盘
span 与指纹**（`value_sha256`、`length`、`charclass_signature`、命中的检测器），续跑时按
span 重新派生屏蔽。

> **通用高熵门为什么必须带关键词条件。** 在全部 55 个项目上实测：无条件的高熵门命中 70 处，
> 其中绝大多数是 URL 查询参数、CAD 文件名与硬件料号。被屏蔽的值不会被还原，因此这类误判会
> **直接破坏 Requirement**。加上「同消息内需存在凭据上下文词」后，全语料命中降至 9 处，
> 全部为真实凭据。精确率在此处比召回率重要，这也与规格本身的表述一致（关键字 **且** 形态
> **且** 熵 **且** 长度的合取）。
>
> 残留风险：0A 是流程中唯一「误判即破坏」的环节。`--dry-run` 会在不调用 API 的前提下报告
> 每个项目的候选数与类型，全量运行前应先看这份报告。

0A 的 fail-closed 核心校验：**对屏蔽后的文本重跑检测器，必须返回零候选**。检测器不允许留下
它自己能识别的 secret。此外校验 ID 唯一且连续、span 可逐字回验、屏蔽可复现、token 重数与
记录的出现次数一致。

### 4.2 Phase 0B LLM PII 发现

仅分类，不改写。22 种实体类型分为三类策略：

| 策略 | 类型 | 含义 |
|---|---|---|
| `SYNTHESIZE` | PERSON、EMAIL、PHONE、PERSONAL_USERNAME、SOCIAL_ACCOUNT、PROJECT_NAME、PRIVATE_ORGANIZATION、PRIVATE_DOMAIN、PRIVATE_REPOSITORY、PRIVATE_URL、MEETING_URL、LOCATION、ADDRESS、PERSONAL_CONTEXT、UNIQUE_BIOGRAPHICAL_DETAIL、ACCOUNT_IDENTIFIER、WALLET_ADDRESS | 替换为虚构值 |
| `PRESERVE` | PUBLIC_THIRD_PARTY、PUBLIC_TECHNOLOGY、NON_PII | 原样保留 |
| `PROTECTED` | SECRET、SECRET_CANDIDATE | 完全不经模型处理 |

**策略不是模型的选择**：由代码中的 `TYPE_POLICY` 固定，校验器强制一致。这样「公共第三方
默认保留」这条与 v6 相反的规则写在代码里，Prompt 回退也无法复活品牌替换。

**全局 ID 由本地确定性分配。** 模型只返回消息内 occurrence + `normalized_value` +
可选 `link_hint`；`entity_id` 与 identity bundle 由 `merge_entity_registry` 按
`(type, casefold(value))` 分组并按首次出现排序生成。v6 让模型分配全局占位符编号并与本地
计数器对比，导致批次必须严格顺序执行，且遇到第一个空洞就得停止 checkpoint。v7 中注册表是
per-message 结果的纯函数：中间有空洞不污染任何东西，跨运行哈希稳定。

**Identity bundle** 把必须一起合成的实体绑在一起：
①模型给出的 `link_hint` 传递闭包；②**本地 host 规则** —— 共享同一 host 的邮箱/链接/仓库
必须同组，子域归入父域。没有②时，邮箱与 URL 可能被分到不同 bundle，从而拿到不同的合成域名。

0B 覆盖率子句：safe text 中每个邮箱、链接、社交句柄、钱包地址、电话号码都必须被某个
occurrence 覆盖；每个内部 token 必须被标为 `SECRET_CANDIDATE`。**漏掉一个邮箱是校验失败，
不是判断分歧。**

---

## 5. Phase 1 — 语义发现

### 5.1 Phase 1A 逐条语义抽取

抽取 speech act、polarity、execution status、ambiguity、decisions，并把业务/技术值绑定到
**按含义命名的 semantic slot**。

v6 只能得到 `NUMBER / AMOUNT / DATE` 这类扁平类别，无法表达「两处 `5` 是同一个参数」或
「`$10,000` 是单人奖金而不是奖池总额」。按含义命名是 1B 能建立历史、Phase 2 能满足数学约束
的前提。

**硬约束：1A 不得输出任何 PII。** 任何返回字符串都不允许匹配邮箱/链接/句柄。这条约束正是
`UPSTREAM` 中「1A 不依赖 0B」这条边的许可条件 —— 收紧 PII 分类法并重跑 0B 时，1A/1B 的结果
全部保留（在最大项目上每次迭代 0B 就省下约 1075 次调用）。

不作为 slot 的内容：有序列表编号（`1.` `2.` 是版式）、技术标识内的数字（`ERC-721` 的 721）、
以及内部 token / 地址 / 链接 / 句柄内部的任何片段。

### 5.2 Phase 1B 项目级语义合并

**线性 fold**，不是 pairwise 树形合并：合并不满足结合律（历史链与规范命名都依赖顺序），
树形 fold 会让不同并行度产出不同 registry，破坏哈希稳定性。

每个 fold 的 scope 含 `prev_fold_output_sha256`，因此第 300 条消息的变化只作废覆盖 300..N
的 fold。累加器有硬尺寸上限，**超限抛错而不静默截断** —— 截断会丢掉 requirement 历史，而那
正是本阶段存在的理由。

校验：每个输入 slot 恰好被消费一次（靠 `merged_from` 证明）；累加器 slot 全部存活；历史链
严格按 ordinal 有序、`history[i].old == history[i-1].new`、首项为 `INTRODUCE`、
`current_value` 等于末项 `new_value`；每条关系用 `Decimal` 在其断言点**精确重算**。

关系求值有三态：`True` / `False` / `None`（不可判定）。不可判定与不成立刻意区分，避免把读不
出数值的关系当成违规。若对话本身自相矛盾（改了数量没改总额），历史照实记录，矛盾的关系进
`unsatisfiable_relations`，**不允许发明一致性**。

---

## 6. Phase 2 — 项目级合成方案

让「一份全项目一致的方案」与 1000+ 条消息兼容的办法：**分块使所有约束成为块内约束，所有
全局不变量在本地强制**。

### 6.1 实体块 = identity bundle 闭包

bundle 永不拆分，所以 bundle 内一致性是结构性的而非靠校验。跨块唯一性靠本地：每块收到
`RESERVED_VALUES`（此前已分配的全部，确定性顺序），校验器拒绝冲突并点名冲突项重试。

### 6.2 slot 块 = 数学关系闭包

由关系图的连通分量决定：相互有算术约束的 slot 在同一次调用中决策，于是
`a × b = c` 能被一致地改成新的 `a' × b' = c'`。孤立 slot 按字符预算自由分批。
校验器用 `Decimal` 在每个断言点重算，算错即整块拒绝 —— 这远比要求模型小心可靠。

### 6.3 本地组装与全局校验

`assemble_plan` 纯确定性且与输入顺序无关，因此 `plan.json` 的 output hash 在块未变时稳定，
这又是 Phase 3 slice 哈希可复用的前提。

`validate_plan` 强制的全局不变量：

1. 覆盖完整 —— 每个 `SYNTHESIZE` 实体都有 replacement，每个 slot 都有决策，secret 条目与
   0A 注册表一一对应。有缺口即拒绝（fail-closed），不放过。
2. `PRESERVE` 实体的 replacement 必须等于 original。
3. **非留存** —— replacement 不等于 original、不包含 original、不被 original 包含、且
   token 相似度低于阈值。
   > 「包含」这一项是必须的：某个名字 → 该名字加一个姓，token 相似度只有 0.67，却**完整
   > 保留了识别性信息**。仅靠相似度阈值会放过它。
4. 类型保持 —— 邮箱仍是合法地址形态、电话仍是电话形态、链接仍是链接、人名不含数字或 `@`。
5. **保留域强制** —— 每个合成域名以 `.example` 结尾（RFC 2606），每个合成邮箱/链接/仓库都在
   合成域名下。合成链接因此不可能指向真实资产。
6. bundle 内一致 —— 同一 bundle 只用一个合成域名；邮箱 local part 可从合成人名派生。
7. 唯一性 —— 同类型内 replacement 唯一，且不与任何其它实体的 original 冲突。
8. **不生成凭据** —— 对所有 plan 值重跑 0A 检测器，命中即硬拒。凭据由 6A 本地渲染，
   secret 条目的 `replacement` 恒为 `null`。
9. slot 新值与原值不同、数据类型不变、历史链形状与语义注册表完全一致、跨块关系仍成立。

### 6.4 `plan_slice`：per-message checkpoint 的可靠性根基

每条消息生成一份 slice，内容是它必须遵守的 plan 决策的**传递闭包**：

```text
该消息自己的实体
  ∪ 同 identity bundle 的全部实体      （改人名 → 作废只提到其邮箱的那条消息）
  ∪ 同数学 cluster 的全部 slot          （改数量 → 作废只提到总额的那条消息）
  ∪ 该消息出现的 secret token
  ∪ 该消息适用的保留词
```

有了这个闭包，`plan_slice_sha256` 相等才真正蕴含「该条缓存改写仍然正确」。

**没有闭包，per-message 哈希是不可靠的**：会保留引用了别处已变更值的改写，而矛盾只会在
最末尾的全项目审计中浮现，且无从追溯成因。因此配有一条双向 property test：改动 slice **外**
的任何 plan 条目，slice 哈希不变；改动 slice **内**任何条目，slice 哈希必变。

---

## 7. Phase 3 — 改写

### 7.1 分桶

```text
词数 0                            → EMPTY           原样保留，不调 LLM
词数 1–2 且 无 PII/secret/slot    → PRESERVE_SHORT  原样保留，不调 LLM
词数 1–2 且 含 PII/secret/slot    → SHORT (3A)      必须改写
词数 3–4                          → SHORT (3A)      必须改写
词数 ≥5                           → LONG  (3B)      必须结构改写
```

实测分布：`EMPTY 4.3%` / `1–2 词 12.3%` / `3–4 词 9.7%` / `≥5 词 73.7%`；1–2 词高度集中在
少量固定确认语。让模型改写上千次同一个单词既浪费又必然产生大批「无法改写」的校验失败。

> `PRESERVE_SHORT` 偏离「短消息也必须改动」这一条目标，是一项明确取舍。

**该取舍的唯一泄漏面必须显式关闭**：词法切分会把一个裸邮箱算成 2 个词。若无条件保留 1–2 词
消息，一条裸邮箱会被原样发布。因此 `PRESERVE_SHORT` 的成立前提是**三重本地检查全部为空**：
0B 该条无 `SYNTHESIZE` 实体、0A 该条无 secret token、1A 该条无 slot。任一非空即降级为
`SHORT`。分桶结果会落盘（`resolved_buckets.json`），否则离线 finalize 会读到 0A 的
**临时**分桶并套用错误的桶策略。

`EMPTY` 与 `PRESERVE_SHORT` 仍进 Phase 6B 覆盖检查：渲染结果必须与原文逐字节相同。

### 7.2 共用改写校验门

`rewrite_violations` 是**所有**候选文本经过的同一道门 —— Phase 3、Phase 5，以及 Agent 修复
经 finalize 时。Agent 没有绕过本地校验器的特权路径。

| 检查 | 内容 |
|---|---|
| 内部表示 | 无 `[X_001]` 形态占位符；无 `FAKE_*`（只有 6A 可引入） |
| secret token | 逐字保留，多重集完全相等 |
| 保留词 | `preserve_literals` 计数不变（大小写敏感，拼写也要保持） |
| 列表编号 | 有序列表编号序列不变 |
| 实体 | `SYNTHESIZE` 原值及别名全部消失；原值曾出现则对应 replacement 必须出现 |
| slot | 原字面值消失、新字面值出现 |
| PII 形态 | 任何邮箱/句柄/链接必须等于某个 planned replacement；源电话号码不得残留 |
| 分桶 | `EMPTY`/`PRESERVE_SHORT` 逐字节相同；`SHORT` 与原文不同、极性与疑问句式保持、不超过词数上限；`LONG` 必须通过结构改写判定 |

两处比较口径的区别很关键：

- **实体原值在原始文本上比较** —— 残留的地址或人名正是要抓的东西。
- **slot 字面值在「屏蔽掉完整 PII 形态之后」的文本上比较** —— 合成 URL 或邮箱里的数字属于
  那个值本身，不是留存的业务数字。

`SHORT` 的词数约束是**绝对上限带余量**，不是围绕原长的窄窗口。其目的是防止把简短确认语膨胀
成一段话；若改成「原长 ±2 词」，一条 2 词的凭据消息（被提升进 `SHORT`）就没有任何自然改写
空间，任务变成不可满足。

结构改写判定沿用 v6 的三条任一成立：句子数变化 / 唯一锚点词发生逆序 / token 序列相似度
≤0.55。仅替换同义词而保持词序会被拒绝。

---

## 8. Phase 4 / 5 — 校验与定向修复

### 8.1 Phase 4 独立校验

送「safe original + synthetic rewrite + plan slice」，返回 11 个维度的 `PASS/FAIL` 与结构化
`findings`。verifier 从 safe original 重新理解语义，而不是对照 1A 的笔记 —— 这也是
`UPSTREAM` 中「4 不依赖 1A」的原因。

`findings.evidence` 永远是**指针**（`DECISION_ID` / `SLOT_ID` / `ENTITY_ID` /
`RELATION_ID` / `SPAN`），绝不是源文本引用。这让 verdict 可安全落盘、可安全打日志、可安全
交给 Agent。

**`cross_check_verdict`：LLM 的 PASS 不能覆盖本地守卫。** 重跑 `rewrite_violations`，失败则
降级为 FAIL 并追加 `LOCAL_GUARD_CONTRADICTION`。本地确定性永远优先于模型判断，这是 Phase 4
最重要的 fail-closed 规则。同时记录 `verified_against`（safe/rewrite/slice 三个哈希），
使 6B 能断言「发布的文本就是被校验过的那份文本」。

### 8.2 Phase 5 定向修复

只处理 FAIL，带 verifier 的具体 finding code 修复，**最多 2 次尝试**（指 2 个不同的修复
Prompt；每次尝试另受该 run mode 的重试预算约束 —— 因此 CLI 为该 run mode 设置
`retries_overrides`，否则「2 次修复」会变成最多 8 次 API 调用）。

修复经过与 Phase 3 相同的门，外加一条：可机判的 finding（PII 不一致、slot 值错误、改写过弱、
本地守卫矛盾）必须转为通过。产出「不同但仍然错误」的文本不算修好。每次修复后重跑校验；
仍失败则进台账。

---

## 9. Phase 6 — 渲染与安全审计

### 9.1 6A 确定性假凭据渲染

`FAKE_<LABEL>_<sha256(project_id|secret_id|salt)[:12] 大写>`。

确定性带来两个性质：续跑、finalize 与重跑产出字节相同（这使「崩溃后重做提交」是安全的）；
形态明显无效，不可能被误当作可用凭据。两个不同 secret_id 渲染成同一字符串会被判为致命冲突。

Agent 与模型都**不允许**自己写 `FAKE_*`：它们保留内部 token，渲染发生在其后。

### 9.2 6B 硬失败审计

`audit_final_texts` 是 `(AuditInputs, cleaned_chat)` 的**纯函数**，可完全用 fixture 离线单测 ——
这也是这份清单能保持诚实的唯一办法。它**跑完所有检查再抛异常**，因此一次运行点名全部违规。
诊断只输出 ordinal、id、计数与 `sha256[:12]` 指纹。

| 组 | 检查 |
|---|---|
| 结构与 provenance | `INVALID_OUTPUT_SCHEMA`、`COVERAGE_INCOMPLETE`、`PROVENANCE_INVALID`、`REQUIRED_CHANGE_NOT_APPLIED`、`PRESERVED_ROW_DRIFTED` |
| 残留身份 | `ORIGINAL_PERSON_PRESENT`、`ORIGINAL_PROJECT_IDENTIFIER_PRESENT`、`ORIGINAL_ENTITY_PRESENT`、`ORIGINAL_EMAIL_PRESENT`、`ORIGINAL_URL_PRESENT`、`ORIGINAL_PHONE_PRESENT`、`ORIGINAL_SENDER_ID_PRESENT`、`MUST_REPLACE_TERM_PRESENT` |
| 凭据 | `ORIGINAL_SECRET_PRESENT`、`INTERNAL_PLACEHOLDER_PRESENT`、`SECRET_TOKEN_MULTIPLICITY`、`FAKE_CREDENTIAL_MALFORMED`、`UNEXPECTED_CREDENTIAL_LIKE_VALUE` |
| 方案一致性 | `PLAN_REPLACEMENT_COLLISION`、`INCONSISTENT_SYNTHETIC_ENTITY`、`INCONSISTENT_SLOT_VALUE`、`PRESERVED_VALUE_LOST`、`LIST_MARKER_DAMAGED` |
| 覆盖与校验 | `UNVERIFIED_TEXT`、`UNRESOLVED_MESSAGE_PRESENT` |

`ORIGINAL_SECRET_PRESENT` 的实现细节：注册表不存原值，审计时按记录的 span 从源文本**重新
派生**真值，只在内存中使用，诊断里仍只输出指纹。

> **移植反转，最易踩的回归点。** v6 对输出**禁止任何邮箱/URL**。v7 必须**允许**合成的
> `.example` 邮箱，因此该检查从「没有邮箱」翻转为「只允许保留域与被保留的公共 host」。

---

## 10. 跨阶段数据结构

```json
// SecretRegistry —— 只有 span 与指纹，绝不含原值
{"project_id": "...", "secrets": [{
  "secret_id": "S001", "internal_token": "<SECRET_CANDIDATE:S001>", "kind": "API_KEY",
  "occurrences": [{"ordinal": 0, "message_id": 0, "start": 0, "end": 0}],
  "length": 0, "value_sha256": "...", "charclass_signature": "aA9-",
  "detectors": ["STRUCTURAL_PREFIX"], "confidence": "HIGH"}]}

// SafeMessage —— 唯一允许送模型/落盘/给 Agent 看的文本形态
{"ordinal": 0, "message_id": 0, "speaker": "...", "safe_text": "...",
 "safe_text_sha256": "...", "source_text_sha256": "...", "word_count": 0,
 "bucket": "LONG", "secret_tokens": ["<SECRET_CANDIDATE:S001>"], "sender_id_present": true}

// PiiEntityRegistry —— entity_id 与 bundle_id 由本地确定性分配
{"entities": [{"entity_id": "E0001", "entity_type": "PERSON", "policy": "SYNTHESIZE",
  "canonical_value": "...", "normalized_key": "...", "bundle_id": "B0001",
  "confidence": "HIGH", "occurrences": [...]}],
 "bundles": [{"bundle_id": "B0001", "kind": "PERSON_IDENTITY", "entity_ids": ["E0001"]}]}

// SemanticRegistry —— 历史链 + 数学关系 + 合并证明
{"slots": [{"slot_id": "...", "kind": "BUSINESS", "value_type": "COUNT", "unit": null,
  "current_value": "...", "meaning": "...",
  "history": [{"ordinal": 0, "op": "INTRODUCE", "old_value": null, "new_value": "..."}],
  "source_literals": ["..."], "message_ordinals": [0]}],
 "relations": [{"relation_id": "R001", "kind": "PRODUCT", "expression": "A * B = C",
   "slot_ids": ["A", "B", "C"], "asserted_at_ordinals": [0]}],
 "decisions": [...], "merged_from": {"<旧名>": "<归并到的 slot_id>"},
 "unsatisfiable_relations": []}

// TransformationPlan —— secret 条目的 replacement 恒为 null
{"plan_version": 1,
 "entity_replacements": [{"entity_id": "E0001", "entity_type": "PERSON",
   "policy": "SYNTHESIZE", "original": "...", "replacement": "...",
   "bundle_id": "B0001", "aliases": [{"original": "...", "replacement": "..."}],
   "depends_on": ["E0002"]}],
 "slot_replacements": [{"slot_id": "...", "value_type": "COUNT",
   "history": [...], "literal_map": {"<原字面值>": "<新字面值>"}}],
 "secret_replacements": [{"secret_id": "S001", "internal_token": "...",
   "kind": "API_KEY", "replacement": null, "rendered_by": "PHASE_6A"}],
 "relation_checks": [...], "reserved_values": {...}, "amendments": []}

// MessagePlanSlice —— 传递闭包；Phase 3/4/5 的哈希来源
{"ordinal": 0, "message_id": 0, "bucket": "LONG", "safe_text_sha256": "...",
 "entity_replacements": [...], "slot_replacements": [...],
 "secret_tokens": [...], "preserve_literals": [...], "must_replace_terms": [],
 "semantic_expectations": {...}, "relation_constraints": ["A * B = C"], "plan_version": 1}

// RewriteRecord / VerdictRecord
{"ordinal": 0, "bucket": "LONG", "text": "...", "text_sha256": "...",
 "applied_entity_ids": [...], "applied_slot_ids": [...],
 "retained_secret_tokens": [...], "structural_change": true,
 "source": "LLM", "attempt": 1}
{"ordinal": 0, "status": "FAIL", "checks": {"intent": "PASS", "...": "..."},
 "findings": [{"code": "DECISION_LOST", "detail": "...",
   "evidence": {"kind": "DECISION_ID", "ref": "D014"}, "severity": "HIGH"}],
 "verified_against": {"plan_slice_sha256": "...", "rewrite_text_sha256": "...",
   "safe_text_sha256": "..."}}

// MessageState —— final_text 在拿到已校验文本前恒为 null
{"ordinal": 0, "message_id": 0, "bucket": "LONG", "requires_change": true,
 "status": "PENDING|DONE|QUARANTINED",
 "provenance": "LLM_REWRITE|LLM_REPAIR|AGENT_REPAIR|PRESERVED_VERIFIED|null",
 "text_sha256": null, "verified": false, "attempts": 0}
```

---

## 11. 断点续跑与级联失效

### 11.1 全局签名刻意很弱

`source_signature.json` 只含 `{source_sha256, engine_version, message_count, chat_path}`。
只有 `source_sha256` 不匹配才**拒绝续跑并退出** —— 消息 ordinal 由列表位置派生，原始 chat
变了则所有 per-message 产物都可能指向别的消息，这是唯一不可恢复的情形。

其余一切（model、effort、Prompt、批大小、fold 尺寸）都进逐阶段哈希，只作废它们真正影响的
部分。v6 把 5 个 Prompt 哈希和所有参数塞进**一个全局 signature**，于是改一个 Phase 5 的
Prompt 会连带作废 Phase 0B 的全部结果 —— 这正是其恢复逻辑长出六个兼容性分支的原因。

### 11.2 逐阶段 `input_sha256`

```text
input_hash(phase) = sha256_canonical({
    schema, engine, phase,
    prompt_sha256,     # 该阶段（含已内联 fragment）解析后全文的哈希
    model, reasoning_effort,
    params,            # 仅该阶段真正读取的参数（PiiConfig.params_for）
    upstream,          # {上游阶段: 其 output_sha256}
    scope,             # 分片身份 + 分片载荷哈希
})
```

`upstream` 映射到上游的 **`output_sha256` 而非 `input_sha256`**：重跑上游但产出字节相同时，
下游零成本。`params` 只投影该阶段读取的参数，避免无关旋钮造成失效。

### 11.3 UPSTREAM 是 DAG，不是链

```text
PHASE_0A_SECRET_SHIELD         : ()                 仅依赖源文件
PHASE_0B_PII_DISCOVERY         : (0A)
PHASE_1A_MESSAGE_SEMANTICS     : (0A)               注意：不依赖 0B
PHASE_1B_PROJECT_CONSOLIDATION : (1A)
PHASE_2_TRANSFORMATION_PLAN    : (0A, 0B, 1B)
PHASE_3_REWRITE                : (0A, 2)
PHASE_4_VERIFICATION           : (0A, 2, 3)         不依赖 1A：verifier 必须独立
PHASE_5_REPAIR                 : (0A, 2, 4)
PHASE_6_RENDER                 : (0A, 2, 3, 5)
```

（阶段常量的完整名称即上表左列；`python .\Code\pii_clean.py --list-phases` 可打印。）

`--force-phase` 取该 DAG 上的**后代闭包**，而非扁平前缀。效果：
`--force-phase PHASE_0B_PII_DISCOVERY` → `{0B, 2, 3, 4, 5, 6}`，**1A/1B 完整保留**。

### 11.4 分片 scope 与提交粒度

| 阶段 | 分片 | scope | 提交粒度 |
|---|---|---|---|
| 0A | 整项目 | 源哈希 | 整体 |
| 0B / 1A | 单条 | ordinal + safe 文本哈希 + 候选/邻居哈希 | **逐条** |
| 1B | fold *k* | k + 上一 fold 的 output hash + 本块记录哈希 | 逐 fold |
| 2 | bundle chunk / slot cluster | index + ids + 载荷哈希 + 已保留值哈希 | 逐块 |
| 3 | 单条 | ordinal + bucket + safe 文本哈希 + **plan_slice 哈希** | **逐条** |
| 4 | 单条 | 3 的 scope + rewrite 文本哈希 | **逐条** |
| 5 | 单条 + 尝试序号 | 4 的 scope + attempt + verdict 哈希 | 逐条逐尝试 |
| 6 | 整项目 | final_texts + secret 注册表 | 本地，不 checkpoint |

逐条独立文件（而非重写聚合文件）同时修掉一个 I/O 缺陷：v6 每个 batch 后重写整份 checkpoint，
一次运行 O(n²) 字节。聚合视图只在阶段完成时写一次，**per-message 信封才是权威**。

### 11.5 恢复时的五层校验

完整性（信封自哈希）→ schema/engine → 身份（phase + shard）→ 新鲜度（`input_sha256`）→
**用与线上响应完全相同的校验器重新验证 body**。

最后一层的意义：只改 Python 校验器（不动 Prompt）也能正确作废缓存 —— 存下的 body 直接通不过
新规则。`load()` 永不抛异常：缓存不可读就是「重算」，不是「中止」。

---

## 12. 失败处理与 Agent 修复流程

### 12.1 先关掉「悄悄用原文」这条结构性通路

v6 在改写前就用原文预填了每条消息的结果映射，唯一阻止原文流入输出的是一处中止。
**一旦为了「不能让程序停止」而放松那处中止，v6 的数据结构会立刻静默输出原文。**

v7 用显式的 per-message 状态取代它，三条规则让「跳过」在结构上就是安全的：

1. `final_text` 在拿到「已校验且已核验」的文本前恒为 `null`。唯一的原文赋值路径是
   `PRESERVED_VERIFIED`，而它要求 `requires_change == false`。
2. 对 `QUARANTINED` 消息读 `final_text` 直接抛异常；Phase 6 遍历**状态**而非文本字典，
   缺项无法默认。
3. 6B 的 `PROVENANCE_INVALID` 断言输出行的 provenance 只能取上述集合，
   `REQUIRED_CHANGE_NOT_APPLIED` 断言每个需改动行的渲染结果 ≠ 原文。

「悄悄用了原文」因此不是需要靠纪律维持的约定，而是被断言两次的不可达状态。

### 12.2 传输失败 ≠ 内容失败

**Agent 修不了 `ConnectError`**，把这类条目交给它只会诱导它为一条模型从未看过的消息编造
文本。（v6 的遗留产物里就有 155 条全是网络错误的「待修复」记录。）

| 失败类 | 处置 | 运行状态 | 下一步 |
|---|---|---|---|
| 传输耗尽 | 隔离该条、继续；**不生成 Agent 任务** | `BLOCKED_RETRYABLE` | 重跑同一条命令（checkpoint 让它很便宜） |
| 本地校验器拒绝 / verifier FAIL / 修复耗尽 | 隔离该条、继续、**生成 Agent 任务** | `AWAITING_AGENT_REPAIR` | Agent 修复 → finalize |
| 1B / 2 内容失败 | 项目级，无法靠手写文本修 | `REPLAN_REQUIRED` | `--force-phase PHASE_1B_PROJECT_CONSOLIDATION` |
| 0A / 结构不变量违反 | 枚举全部违规后中止该项目 | `FATAL` | 修代码或源数据 |
| Agent 提交被拒 | 不提交，写出逐条拒绝原因 | `AGENT_REPAIR_REJECTED` | Agent 依据 `repair_result.json` 重交 |

### 12.3 continue-past-failure 的精确语义

> **阶段内：绝不停止，隔离并继续，枚举全部。**
> **在聚合边界：若聚合体的任何输入缺失，就停止推进阶段。**

`ledger.record()` 永不抛异常；每个阶段跳过已隔离的消息但对其余消息跑到完。一条 Phase 3
失败不得妨碍 Phase 3 处理其余消息，也不得妨碍 Phase 4 核验那些成功的。

阶段组屏障：`{0B, 1A}` → `{1B, 2}` → `{3, 4, 5}` → `{6}`。

**为什么抽取级失败必须把运行封顶在抽取阶段**：Phase 2 的方案是「真实 X → 合成 X，全项目
一致」的唯一真相源。若某条消息在 1A 失败，它的实体从未进入清单，Phase 2 会产出缺该条目的
方案。接着只有两种坏结果，没有第三种 —— 要么 Phase 3 在改写**其它**提到同一实体的消息时
无映射可用（泄漏，或临时编造一个将来与方案矛盾的映射）；要么修复后重新生成方案，而那可能
改掉已改写消息已经承诺的映射，被迫整体重跑 Phase 3。**全局一致性无法从不完整的清单构建。**

这仍然满足「一次运行把所有有问题的 message 全部找出来」，只是粒度正确：0B 与 1A 在同一次
运行内**都跑到完**；`{3,4,5}` 同理跑到完 —— 而失败实际上主要聚集在后者。

`raise_if_unresolved()` 只在停下的那个分组末尾调用一次。**只要有未解决消息，绝不写最终
`chat_messages.json`。**

### 12.4 Agent 任务包

`outputs/pii_runs/<pid>/agent_tasks/index.json` + 每条一个 `task_NNNNN.json`。
任务包是**派生物，不是权威**：每次运行都从 phase checkpoint 重新生成，并绑定当前签名，
使陈旧的 Agent 成果被拒绝而不是被误用。

头部关键字段：`source_sha256`、`plan_sha256`、`blocked_phase`、
`protected_tokens`（**闭列表**，使「不得出现列表外 token」成为可判定断言）、
`preserve_terms_global`、`instructions_path` + `instructions_sha256`、按 failure_code 的计数。

每条任务：`task_id`（跨运行稳定 ⇒ 第二次运行复用 Agent 成果）、`ordinal`、`bucket`、
`failed_phase`、`failure_code`、`failure_class`、`agent_actionable`、`requires_replan`、
`context_available`、`attempt_history`（逐次 outcome + finding code + candidate 哈希 ——
**Agent 不该重试一个已经失败过的修法**）、`safe_original_text`、
`safe_source_sha256`、`source_text_sha256`（双哈希：后者兜住「屏蔽恰好归一化掉」的源改动）、
`last_candidate_text`、`rewrite_directive`、`must_apply_entities`（含 aliases）、
`must_apply_slots`（含目标值）、`relation_constraints`、`must_preserve_verbatim`、
`protected_tokens_present`（精确**多重集**）、`verifier_failures`、`local_validator_errors`
（规则码明文 + 冒犯片段只给指纹）、`context_window`（±2 邻居，只读）、`status`（**只由
finalize 写**）、`submission_slot`。

**两种 kind，对应两条消费路径** —— 这是与「finalize 全离线」调和的关键：

| kind | 何时产生 | Agent 交付 | 谁消费 |
|---|---|---|---|
| `TEXT` | 3/4/5 失败、`PLAN_GAP` | 该消息的最终合成文本 | **`pii_finalize.py`（离线）** |
| `EXTRACTION` | 0B/1A 内容失败 | 该消息缺失的实体/slot 标注 | **下一次 `pii_clean.py`**（方案必须带上该消息重建，本来就要调 API） |

抽取级失败罕见、常见失败是改写/校验，所以离线 finalize 覆盖了正常路径。

### 12.5 Agent 提交与 finalize

Agent 只写一个文件：`outputs/pii_runs/<pid>/agent_repairs/repairs.json`。
`--write-template` 可生成预填骨架。

**Agent 写的文本里仍保留内部 secret token，且绝不允许自己写 `FAKE_*`** —— 6A 确定性渲染是
唯一真相源，Agent 完全不需要推理凭据格式。

finalize 校验顺序（逐条短路但跨条继续，一次报全部问题）：

1. **形状** —— 闭 key 集合，拒绝未知 key。一个拼错的 key 会静默停用它所属的守卫，因此整个
   key 集合是封闭的。
2. **绑定** —— `schema_version` 已知；`queue_sha256` 与当前重算的任务包一致；`source_sha256` 一致。
3. **覆盖** —— `task_id` 存在、可由 Agent 处理、无重复；`requires_replan` 的任务不得带文本。
4. **双哈希守卫** —— 重读源行、重跑 0A、比对 `safe_source_sha256` 与 `source_text_sha256`；
   比对 `plan_slice_sha256`。
   > 为什么需要第二道：手写改写只对它所针对的**那份方案**有效。方案变了就必须响亮地拒绝，
   > 而不是套用。
5. **调用与 Phase 3 完全相同的校验器函数**（不是弱化副本）。
6. **protected token 多重集**相等，且无闭列表外的 token。
7. **无遗留占位符、无 `FAKE_*`**。
8. **方案一致性** —— 适用 slot 按方案值出现；其它实体的 original 表面形式不出现。
9. **`reason` 卫生** —— 拒绝含邮箱/链接或任何方案 original 表面形式的 reason。
   > 这条很要紧：`reason` 正是 Agent 会自然写成「把某某改成了某某」的字段，而那恰好是
   > 重识别密钥，出现在最容易被粘进终端或 commit message 的地方。**指令加强制，不是只有指令。**

全部通过后：合并 Phase 3/5 已通过文本 → 6A 渲染 → **6B 全项目审计**（不只是被修的行 —— 一条
修复可能破坏全局不变量，比如复用了分给另一个实体的 replacement）→ 原子提交
`repair_result.json` → 复制项目其他文件 + `chat_messages.json` → manifest → `run_metadata`
置 `PASSED` → 删除含 PII 的过程文件。

**提交前置条件是集合式的**：

```text
无 OPEN/REJECTED 的 agent_actionable 任务
  ∧ 每条提交本地校验 ACCEPTED
  ∧ 6B 零违规
```

因此部分修复无法提交：覆盖一部分任务的提交会校验那一部分（反馈有用且持久化），然后以
`AGENT_REPAIR_REJECTED` 拒绝并列出未覆盖的 `task_id`。

**幂等性**：Phase 0–5 checkpoint + `repair_result.json` 的逐任务判定 + 6A 的纯函数性质，
使第二次 finalize 零重复工作且产出字节相同。崩溃安全：所有写入原子，且「已完成」以 manifest
为准，所以「写了 chat 但没写 manifest」的崩溃会让项目保持未完成，下次确定性重做。
**绝不在 manifest 落盘前删除任何产物。**

### 12.6 离线 finalize 的责任边界

按既定决策，finalize **不调用任何 API**，因此 Agent 修复文本的**语义**正确性没有独立 LLM
复核。本地校验器（实体/slot 应用、保留词计数、protected token 逐字、结构改写、无内部 token
与遗留占位符）+ 6B 全项目审计是全部保障。语义层面的判断由编写修复的 Agent 与操作者承担。

### 12.7 运行状态机

```text
RUNNING ──► PASSED | BLOCKED_RETRYABLE | AWAITING_AGENT_REPAIR | REPLAN_REQUIRED | FATAL

{AWAITING_AGENT_REPAIR, AGENT_REPAIR_REJECTED} ──finalize──► {PASSED, AGENT_REPAIR_REJECTED}
{BLOCKED_RETRYABLE, REPLAN_REQUIRED}           ──clean────► RUNNING
```

`run_metadata.json` 同时写出 `next_command`，`--status` 直接打印每个项目该跑什么命令。

---

## 13. 核心不变量

1. 最终 `chat_messages.json` 中不含任何原始人名、邮箱、电话、私有域名、私有链接、仓库、
   账号标识或钱包地址。
2. 不含任何原始凭据；每个被屏蔽的凭据渲染为确定性的 `FAKE_*`，且两个 secret 不会渲染成同一值。
3. 不含 `<SECRET_CANDIDATE:...>` 内部 token，也不含 `[CATEGORY_001]` 形态的遗留占位符。
4. 出现的邮箱与链接只能位于保留域（`.example` 等）或被保留的公共 host。
5. 公共第三方与公共技术名称原样保留，计数不变。
6. 每个实体在整个项目中只有一种合成拼写；两个实体不共用同一 replacement。
7. 每个 slot 在每个出现点的值符合方案在该历史点的取值；方案满足 1B 记录的全部数学关系。
8. 有序列表编号序列不变。
9. 每个 `requires_change` 行的渲染结果 ≠ 原文；每个保留桶行与原文逐字节相同。
10. 每个变更行的 provenance ∈ {LLM_REWRITE, LLM_REPAIR, AGENT_REPAIR, PRESERVED_VERIFIED}，
    且携带针对**该确切文本**的校验结果。
11. 行数不变；除 `message`、`sender_id`、`created_ts` 外所有字段逐字节相同；
    `sender_id` 与 `created_ts` 已删除。
12. **只要存在未解决消息，就不存在最终输出。**

1–11 由 Phase 6B 逐项断言；12 由状态机与 6B 的 `UNRESOLVED_MESSAGE_PRESENT` 共同保证。

---

## 14. 数据敏感性

### 14.1 产物分级

**含真实 PII —— 绝不提交、成功后自动删除**

| 产物 | 说明 |
|---|---|
| `phase2_transformation_plan/plan.json` 与 `slices/` | **原值 ↔ 合成值的完整重识别密钥，全系统最敏感的产物** |
| `agent_tasks/`、`agent_repairs/` | 含 secret 已屏蔽但人名/邮箱仍在的原文 |
| `phase0b/1a/3/5` 的逐条信封、`phase0a/safe_messages.json` | 同上 |
| `outputs/pii_logs/failed_responses/` | 失败响应（PII run mode 强制脱敏，但仍按敏感对待） |

**只含指纹 —— 可保留、可提交**：`run_metadata.json`、`unresolved/{ledger.jsonl, summary.json}`、
`phase6_render/audit_report.json`、`_manifests/<pid>.json`、`outputs/pii_logs/api_calls.jsonl`。

`--keep-run-artifacts` 可保留全部产物，但应仅在受信任环境用于排查。

### 14.2 日志纪律

**永不写入日志 / stdout / stderr**：原文、safe 原文、candidate 文本、原值与 replacement 的
配对、secret 值。只允许：`message_id`、`ordinal`、`task_id`、`failure_code`、
`sha256[:12]` 指纹、计数。

台账持有一张注册表（secret 真值、sender_id、实体表面形式），对每条诊断字符串做**单次
正则替换**，因此即使某个校验器消息意外引用了敏感值也不会外泄。
`failed_response_redactor` 在 v7 对所有 PII run mode **强制非可选**（v6 把它做成可选参数、
靠记得传）。

### 14.3 git 卫生

仓库根 `.gitignore` 覆盖 `outputs/pii_runs/`、`outputs/pii_logs/`、
`Datasets/**/_checkpoints/`、`Datasets/**/_logs/` 等。

排查本次重构时发现仓库此前已把含真实 PII 的中间产物提交进 git（v6 的改写后未脱敏
checkpoint、失败响应、以及一份人工改写文件）。这些路径已取消跟踪（本地文件保留）。
⚠️ **历史 commit 里的副本仍然存在**，`.gitignore` 不会移除它们；若需清理历史，那是独立的
`filter-repo` 操作，不在本次范围内。

### 14.4 关于 Agent 会读到 PII 的前提

Agent（本机 Claude Code）按设计会读到真实人名、邮箱与业务数值 —— 这不可避免，语义修复需要
原意。安全边界画在别处：

1. PII 不离开本机与该会话；
2. **任何真实凭据都不在文件里**（0A 在任何数据离开本地进程前已替换成 token），这是唯一
   Agent 确实不该看到的类别，而它结构性地看不到；
3. 产物不入 git，且项目成功后自动删除；
4. 指令要求 Agent 不把原值回显到 `reason`/日志/commit，**并且 finalize 强制执行**。

---

## 15. 实现与运行文档

- 实现：`Code/PII/`（23 个模块）、`Code/pii_clean.py`、`Code/pii_finalize.py`
- Prompt：`prompt/PII/`（3 个 shared fragment + 8 个阶段 Prompt + 1 个 Agent 说明）
- 测试：`Code/tests/test_pii_audit.py`、`test_pii_plan.py`、`test_pii_pipeline.py`
- 运行命令与 Agent 修复操作步骤：[`README_PII_Clean.md`](../Code/insturctions/README_PII_Clean.md)

### 15.1 与 v6.0 的主要差异

| 维度 | v6.0 | v7.0 |
|---|---|---|
| 最终产物 | 保留 `[EMAIL_001]` 占位符 | 自然虚构内容 |
| 公共第三方名 | 强制替换 | **默认保留**（代码强制） |
| 业务数值 | 逐位置 `NUMBER/AMOUNT/DATE` | 按含义命名的 semantic slot + 历史 + 数学约束 |
| 凭据 | 与其它 PII 同路处理 | 本地屏蔽 → 确定性假凭据渲染 |
| 短消息 | 原样保留 | 3–4 词及含内容的 1–2 词必须改写 |
| 校验 | 本地校验器 | 本地校验器 + 独立 LLM verifier（本地守卫可否决其 PASS） |
| 续跑失效 | 单一全局 signature | 逐阶段 `input_sha256` + DAG 后代闭包 |
| 占位符编号 | Phase 3 边走边分配（顺序敏感） | Phase 2 一次性本地确定性分配 |
| 失败处理 | 台账 + 中止；数据结构预填原文 | 隔离并继续 + 结构上不可能回落原文 + Agent 修复闭环 |
| 过程文件 | 数据集目录下 | `outputs/pii_runs/`，成功后自动删除含 PII 的部分 |

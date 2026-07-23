# Benchmark Survey

# 1. Agent

根据 Upwork《Client Matching Big Bet Q2/Q3 ’26》的规划，第二阶段的核心目标是设计这样一个智能体：

> **从“用户输入 Query → 系统返回搜索结果”的被动匹配系统，转向“理解客户是谁、理解客户当前想做什么、预测下一步需要什么、主动调用匹配能力完成招聘任务”的智能体。**
> 

Upwork 对第二阶段的定义是 **“Intelligence for What’s Next”**。文档明确指出，被动式 Ranking 无法适应 Agentic World；未来 Upwork 需要建立三类基础能力：**Intent、Readiness 和 Representation**。也就是说，系统不仅需要理解“用户现在输入了什么”，还需要理解“这个客户是谁”“候选人现在是否适合被联系”“客户下一步可能需要什么”。

因此，本文将第二阶段 Agent 定义为：

# Intent-Aware Recruiting Agent

## 意图感知型招聘智能体

这个任务不是简单地“找 Freelancer”，而是：

> **持续理解客户的招聘目标与项目状态，维护客户和人才的动态表示，决定当前最合理的招聘动作，调用 Upwork 的搜索与匹配工具，并通过多轮交互帮助客户完成下一步招聘决策。**
> 

其完整核心流程应当是：

```
用户目标 / 当前对话
        ↓
理解招聘意图
        ↓
读取客户历史和当前状态
        ↓
判断信息是否充分
        ↓
决定下一步行动
        ↓
调用 Search / Match / Readiness 等工具
        ↓
比较、筛选和解释候选人
        ↓
向用户提出建议或继续询问
        ↓
根据新信息更新状态
        ↓
进入下一轮招聘决策
```

从系统能力角度，第二阶段 Agent 至少需要具备六项核心能力：

1. **Conversational Intent Understanding**
2. **Persistent Client Representation**
3. **Freelancer Readiness Awareness**
4. **Sequence-aware Next-step Prediction**
5. **Tool Planning and API Orchestration**
6. **Multi-turn State Tracking**

# 2. Benchmark

结合Agent的设计，我们的Benchmark在整体设计上应该需要完整评估下面这个流程：

```
理解客户
    ↓
发现信息缺口
    ↓
决定问还是搜
    ↓
利用历史状态
    ↓
调用正确工具
    ↓
考虑人才实时状态
    ↓
推荐正确的人
    ↓
最终招聘是否产生高质量工作结果
```

Upwork 的 Agent需要建设 intent、readiness、representation 三类能力。 第二阶段还明确要求 sequence-aware recommendation、conversational query understanding、MCP retrieval，以及可被 Agent 调用的 Match/Search APIs。

所以 benchmark 的评价对象必须从：

```
Query → Ranking
```

升级成：

```
Client Goal
→ Understanding
→ State
→ Planning
→ Tool Use
→ Matching
→ Hiring Outcome
```

## 2.1 目前已有的数据集

## HAPIv2：结果非常丰富，但缺少招聘过程

- `jobs` 中有 145 个真实 Web / Mobile / Software Development 任务；
- 每个任务都有具体 `acceptance_criteria`；
- 平均每个任务大约 6 个验收标准；
- 主评估链中有 104 个任务；
- `agent_traces` 和 `evals_turn0` 对应 104 个任务 × 3 个 Agent；
- 后续还有 `evals_turn1`、`evals_turn2`；
- 失败以后可以修改、再次提交；
- `submission_feedback` 可以对应到具体 Criterion；
- 最自然的评价单位是：

```
Task × Agent × Turn × Criterion
```

它天然拥有：

```
真实任务
+
明确验收标准
+
真实产物
+
逐项评价
+
失败诊断
+
修改重试
+
最终成功/失败
```

但它没有：

```
Client是谁
客户之前招聘过谁
为什么要招聘
候选人池是什么
Agent为什么选择这个人
Agent调用了什么搜索工具
有没有问澄清问题
招聘过程是什么
```

所以 HAPIv2 不能独立评价 Recruiting Agent。

---

## Upwork_GPT：过程丰富，但最终结果不足

它包含：

```
conversation / session
tool_name
structured inputs
query
additional_context
location
hourly_rate
search
view
hire
```

同时里面包含：

```
Search
Search → View
Search → View → Hire
```

这样的用户行为流程。

它很适合回答：

> Agent 是否正确理解 Query？
> 

> Agent 是否调用了正确 Tool？
> 

> Tool 参数是否合理？
> 

> 行为顺序是否合理？
> 

但是当前主要问题是：

> 大量记录仍然停留在 Search。
> 

完整：

```
Goal
→ Search
→ View
→ Invite
→ Hire
→ Work Outcome
```

链路比较少。

因此它很难告诉我们：

> Agent 推荐的人最终真的好吗？
> 

---

## UFS / UMA 数据：非常适合评价 Clarification

它已经定义了一种：

```
Step-by-step Refinement
```

比如：

```
Turn 1:
Location

Turn 2:
Experience / Badge

Turn 3:
JSS
```

而且内部强调：

```
一次只处理一个 refinement dimension
```

这正好可以用于评价第二阶段 Agent 的：

```
Clarification Policy
State Tracking
Constraint Accumulation
Context Consistency
```

但它的问题是：

> 目前训练数据主要是 synthetic。
> 

因此不能把它直接当“真实用户行为 Ground Truth”。

## 2.2 Benchmark 的核心研究问题

我们不能把研究问题定义成：

> How accurately can an agent recommend freelancers?
> 

因为这个问题太像传统推荐系统，更好的核心问题是：

> **Can an agent understand a client's evolving hiring goal, choose the right next action, use matching tools effectively, and produce a high-quality hire?**
> 

中文：

> **一个 Agent 能否理解客户不断变化的招聘目标，选择正确的下一步行动，合理调用匹配工具，并最终产生高质量招聘结果？**
> 

这个问题包含四层：

```
Layer 1
理解得对不对？

Layer 2
行动得对不对？

Layer 3
推荐得对不对？

Layer 4
最终招聘结果好不好？
```

这四层恰好是当前大多数 benchmark 没有同时评价的，这也是和传统的推荐系统的不同之处。

## 2.3 Benchmark 的基本单位

# Episode × Agent × Turn × Decision Criterion

一个 Episode 是一次完整招聘任务。

例如：

```
Episode #183

Client:
AI startup

Existing team:
Designer
Frontend Developer

Current project:
AI SaaS prototype

Hidden goal:
Production deployment

Initial user message:
"We are building an AI product
and need someone to help."

Candidate pool:
20 freelancers

Available tools:
Search
View
Client History
Readiness
Reputation
Match

Maximum turns:
8
```

然后记录：

```
Turn 1
Agent interprets intent

Turn 2
Agent asks clarification

Turn 3
User provides new information

Turn 4
Agent retrieves history

Turn 5
Agent searches

Turn 6
Agent checks readiness

Turn 7
Agent compares candidates

Turn 8
Agent recommends
```

最后再连接：

```
Chosen Candidate
        ↓
Actual Work
        ↓
HAPI Acceptance Criteria
        ↓
Downstream Quality
```

## 2.4 Benchmark 架构设计

将Benchmark设计为四个相互连接、但可以独立运行的 Track。

### Track A：Intent & Interaction

## 评价 Agent 是否真正理解客户

主要使用：

```
Upwork_GPT
+
UFS / UMA
+
新增标注
```

### 评价指标：

```
Intent Understanding
Constraint Extraction
Missing Information Detection
State Tracking
Clarification Quality
```

任务包括：

### A1. Explicit Intent

用户明确说：

> I need a senior React developer in Australia.
> 

Agent 应该正确提取：

```
role = React Developer
seniority = Senior
location = Australia
```

---

### A2. Ambiguous Intent

用户：

> I need help launching my AI product.
> 

Agent 不应该马上 Search。

正确行为应该是：

```
ASK_CLARIFICATION
```

---

### A3. Long-form Intent

例如：

> We have already built a prototype using PyTorch. We now want to serve it to customers through our web application and expect a few thousand requests per day.
> 

Agent 要推断：

```
Current state:
Prototype exists

Target:
Production deployment

Likely role:
MLOps / ML Infrastructure

Missing:
Cloud provider
Deployment stack
```

---

### A4. Changing Intent

```
Turn 1:
Need Python engineer

Turn 3:
Actually we already have backend support

Turn 5:
The main issue is deployment
```

评价 Agent 是否：

```
更新状态
```

而不是继续按照最早的 Python Engineer 搜索。

---

### Track B：Planning & Tool Use

在PPT中Stage 2 的 Roadmap 明确要求把 Search/Match 做成 Agent-consumable primitives，而不是让所有产品重新实现搜索逻辑。

Agent 的 Action可以定义成：

```
ASK
RETRIEVE_HISTORY
SEARCH
VIEW
CHECK_READINESS
CHECK_REPUTATION
MATCH
COMPARE
REFINE
RECOMMEND
STOP
```

---

## 典型测试

用户：

> Find someone similar to the developer I hired last year.
> 

错误：

```
SEARCH("developer")
```

正确：

```
RETRIEVE_HISTORY
        ↓
IDENTIFY_PREVIOUS_HIRE
        ↓
SEARCH_SIMILAR
        ↓
CHECK_READINESS
        ↓
RECOMMEND
```

评价：

```
Tool Selection
Tool Ordering
Argument Accuracy
Redundant Calls
Error Recovery
```

---

### Track C：Matching & Readiness

这是连接推荐系统和 Agent 的部分。

Roadmap 明确要求 Freelancer Readiness Model 根据 bids、messages、alert interactions 等行为估计近实时 readiness；同时 Client–Talent Intent Embedding 应利用历史行为和 talent alignment 形成跨 Session 的客户表示。

因此 Candidate 的评价不能只有：

```
Skill Match
```

而应该有：

```
Candidate Utility

=
Task Fit
×
Client Fit
×
Readiness
×
Trust
```

例如：

| Candidate | Task Fit | Readiness | 最终结果 |
| --- | --- | --- | --- |
| A | 0.97 | 0.15 | 不应第一推荐 |
| B | 0.91 | 0.88 | 最合理 |
| C | 0.82 | 0.95 | 可作为备选 |

传统 Ranking：

```
A > B > C
```

Agentic Matching：

```
B > C > A
```

### 指标

可以保留传统推荐指标：

```
NDCG@K
Recall@K
Hit Rate
```

但必须加入：

```
Readiness-aware Utility
Constraint Satisfaction
Personalization
```

---

### Track D：Closed-loop Hiring Outcome

### 核心问题

> Agent 推荐的人最终真的把任务做好了吗？
> 

这是Benchmark 最大的研究创新。

传统 Recommendation Benchmark 到 推荐就停止，

传统招聘数据通常到 Hire阶段就停止，

但是我们可以做到：

```
Recommend
    ↓
Hire
    ↓
Work
    ↓
Acceptance Criteria
    ↓
Real Task Outcome
```

我们的Agent会真实的评估：

> **推荐结果产生的真实下游价值。**
> 

例如：

```
Criterion 1：通过
Criterion 2：通过
Criterion 3：失败
Criterion 4：部分通过
Criterion 5：通过
```

计算：

```
Final Work Quality = 0.76
```

### 指标

```
Acceptance Criteria Satisfaction
Overall Task Quality
Final Success
Decision Regret
```

## 2.5 四个 Track 如何连在一起

完整流程应该是：

```
┌─────────────────────┐
│ Track A             │
│ Intent & Interaction│
│                     │
│ 客户到底要什么？     │
└──────────┬──────────┘
           ↓

┌─────────────────────┐
│ Track B             │
│ Planning & Tool Use │
│                     │
│ 下一步该做什么？     │
└──────────┬──────────┘
           ↓

┌─────────────────────┐
│ Track C             │
│ Matching & Readiness│
│                     │
│ 应该推荐谁？         │
└──────────┬──────────┘
           ↓

┌─────────────────────┐
│ Track D             │
│ Hiring Outcome      │
│                     │
│ 这个人最终做得好吗？ │
└─────────────────────┘
```

所以完整 Benchmark 问的是：

> **Agent 能不能理解客户 → 做出正确决策 → 选出正确人才 → 最终产生好的真实任务结果。**
> 

---

# 三、三个现有数据集具体放在哪里

| 数据 | Track A | Track B | Track C | Track D |
| --- | --- | --- | --- | --- |
| Upwork_GPT | ✓ | ✓ | 部分 |  |
| UFS / UMA | ✓ | 部分 |  |  |
| HAPIv2 |  |  | 部分 | ✓ |
| 新 Bridge Dataset |  | ✓ | ✓ | ✓ |

```
Upwork_GPT
    ↓
真实客户需求和 Tool 场景
    ↓
Track A + Track B

UFS / UMA
    ↓
多轮需求变化
    ↓
Track A

Candidate Dataset
    ↓
Candidate Profile + Readiness
    ↓
Track C

HAPIv2
    ↓
真实任务执行结果
    ↓
Track D
```

# 3. 目前缺少的数据

缺少一个

### Bridge Dataset

负责把四个 Track 连起来。

每一个完整 Episode 需要：

```
Client Request
+
Client History
+
Conversation State
+
Available Tools
+
Candidate Pool
+
Candidate Readiness
+
Candidate Actual Outcome
```

完整结构：

```
Client
  ↓
Track A
理解需求
  ↓
Track B
选择行动
  ↓
Track C
选择 Candidate
  ↓
Track D
查看真实 Outcome
```

# 4. 版本线

### V1：4个单独 Track Benchmark

| Track | 建议规模 |
| --- | --- |
| A Intent & Interaction | 300–500 |
| B Planning & Tool Use | 300–500 |
| C Matching & Readiness | 200–300 |
| D Closed-loop Outcome | 100–300 |

这样可以诊断：

```
Agent 到底是哪里不好？
```

例如：

```
Agent A

Track A：90
Track B：55
Track C：80
Track D：76
```

说明：

> 理解很好，匹配也不错，但 Planning / Tool Use 很差。
> 

## V2: Integrated Benchmark

再设计大约：

```
200–300 个完整 Episode
```

完整运行：

```
Track A
   ↓
Track B
   ↓
Track C
   ↓
Track D
```

即：

```
真实需求
→ 多轮理解
→ 自主 Tool Use
→ Candidate Selection
→ Real Work Outcome
```

# 六、最终 Leaderboard

| Agent | Track A Understanding | Track B Decision | Track C Matching | Track D Outcome |
| --- | --- | --- | --- | --- |
| Agent A | 86 | 72 | 80 | 75 |
| Agent B | 78 | 91 | 85 | 84 |
| Agent C | 90 | 65 | 76 | 70 |
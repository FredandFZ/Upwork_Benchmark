# ReqMemBench RQ1–RQ4 Evaluation Design（精简版）

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
| RQ2 | Agent 能否恢复 target 前当前有效的 Requirement State？ | State Score、Full-State Exact |
| RQ3 | Agent 能否正确选择 ACT 或 CLARIFY？ | Decision Accuracy |
| RQ4 | Agent 修改后的代码能否通过最终自动验证？ | Delivery Pass |

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
RQ2 和 RQ3 在 C1/C2/C3 下评价。RQ4 只在对应 condition 的最终 Gold decision 为
`ACT` 时评价代码交付。

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
- `selection_basis` 和 `source_artifacts`；
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
  "selected_history_message_ids": [8, 21, 156],
  "requirements": [
    {
      "requirement_ref": "agent-local-1",
      "requirement_summary": "Small Block prize rule",
      "evidence_message_ids": [8, 21, 156],
      "current_state": {
        "attributes": {},
        "scope": {},
        "lifecycle_status": "ACTIVE",
        "ambiguity": null,
        "execution": null
      }
    }
  ],
  "decision": "ACT",
  "clarification": null
}
```

如果 Agent 选择 `CLARIFY`：

```json
{
  "decision": "CLARIFY",
  "clarification": {
    "requirement_ref": "agent-local-1",
    "dimension": "VALUE",
    "question": "Which prize amount should be used?"
  }
}
```

Agent 不需要猜内部 `REQ_*` ID。Evaluator 根据 evidence message overlap 和
requirement summary，把 Agent 的 `requirement_ref` 与 Gold Requirement 对齐；无法可靠对齐的
结果交给人工复核。

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

对项目 `42204309`，可以先使用 `42204309_T010` 做 smoke test。全部 25 个 targets
按统一协议运行一次需要最多 `25 × 3 = 75` 个 Agent runs。

---

## 3. RQ1 — Relevant Requirement Selection

### 3.1 输入与 Agent 输出

RQ1 只使用 C2 Full History。Agent 需要输出：

- 相关历史 Requirement 的简短描述；
- 每个 Requirement 对应的 historical message IDs；
- 汇总后的 `selected_history_message_ids`。

当前 target 首次提出的新 Requirement 不属于 historical Requirement，不能虚构历史证据。

### 3.2 Gold

RQ1 Gold 包含：

- `relevant_requirement_ids`；
- 每个 Requirement 的核心 evidence message IDs；
- unrelated history messages。

正式评分前必须完成人工 relevance review。当前 provisional Gold 不能直接作为正式论文分数。

### 3.3 评分

Requirement-level：

- 正确匹配到相关 Gold Requirement：TP；
- Agent 额外提出无关 Requirement：FP；
- Agent 遗漏 Gold Requirement：FN。

计算 Requirement Precision、Recall 和 F1。

Evidence-level：

- 选择 Gold core message：TP；
- 遗漏 Gold core message：FN；
- 选择 unrelated message：FP。

计算 Evidence Precision、Recall 和 F1。
仅用于理解指代或上下文、但不直接承载 Requirement fact 的必要 contextual message，既不计
TP，也不计 FP。

RQ1 的主要报告结果为：

```text
Requirement F1
Evidence F1
Exact Requirement Set Accuracy
```

---

## 4. RQ2 — Current Requirement State Reconstruction

### 4.1 输入与 Agent 输出

RQ2 在 C1/C2/C3 下运行。Agent 对每个相关 historical Requirement 输出 target 到来前的
current state：

- `attributes`；
- `scope`；
- `lifecycle_status`；
- `ambiguity`；
- `execution`。

这里评价的是 Pre-task State，不是完成当前 task 之后的 Post-task State。

### 4.2 Gold

RQ2 Gold 来自 `construction_gold.states`。正式评分前先完成人工 relevance review，并确认
每个可评分字段具有可靠 Gold。

同一个 target 在 C1/C2/C3 下使用同一份真实 State Gold。C1 只是隐藏历史，不改变项目事实。

### 4.3 字段比较

| State field | 比较方式 |
|---|---|
| attributes | key/value fact Precision、Recall、F1 |
| scope | persistence exact；components/contexts 使用 set F1 |
| lifecycle_status | exact match |
| ambiguity | OPEN/null 和 dimension exact match |
| execution | status exact match |

如果 Agent 遗漏整个 Gold Requirement，该 Requirement 的适用字段都记为 0。无法建立可靠
Gold 或不适用的字段不进入分母。

### 4.4 评分

先计算每个 Requirement 的适用字段平均分，再在 target 内平均：

\[
StateScore
=
\operatorname{mean}(attributes, scope, lifecycle, ambiguity, execution).
\]

同时报告：

- `State Score`：允许部分字段正确；
- `Full-State Exact`：全部相关 Requirements 和全部适用字段都正确才为 1；
- C1、C2、C3 各自的结果。

重点比较：

```text
C2 − C1：完整历史是否帮助恢复状态
C3 − C2：去掉无关历史后是否改善
```

---

## 5. RQ3 — Memory-or-Clarify Decision

### 5.1 输入与 Agent 输出

RQ3 在 C1/C2/C3 下运行。Agent 必须输出以下二选一结果：

```text
ACT
CLARIFY
```

选择 `CLARIFY` 时，还要输出具体问题及其对应的 Requirement 和 state dimension。

### 5.2 Gold

RQ3 使用 condition-specific Gold：

```json
{
  "C1": "CLARIFY",
  "C2": "ACT",
  "C3": "ACT"
}
```

因为 C1 缺少历史，所以它可能需要 clarification；C2/C3 拥有足够历史时则可以直接行动。
C2 和 C3 包含相同的有效 evidence，因此其最终 Gold decision 应一致。

RQ3 Gold 必须经过人工审核。不能仅因为存在任意 OPEN ambiguity 就自动判为 CLARIFY；该
ambiguity 必须真正影响当前实现。

### 5.3 评分

主要结果为：

- Decision Accuracy；
- ACT Recall；
- CLARIFY Recall。

同时区分两类错误：

| Gold | Agent | 错误 |
|---|---|---|
| CLARIFY | ACT | Unsupported Autonomy：证据不足却自行实现 |
| ACT | CLARIFY | Unnecessary Clarification：已有足够证据却重复询问 |

对于 Gold CLARIFY，还可以报告 clarification 是否指向正确 Requirement 和 dimension。

---

## 6. RQ4 — Requirement-to-Code Execution

### 6.1 核心定义

RQ4 不再使用复杂的 action/gate 综合评分。第一版只回答：

> Agent 修改后的代码能否通过我们为当前 target 编写的自动交付验证？

RQ4 只评价最终 Gold decision 为 `ACT`、代码环境可运行、能够编写确定性测试的实例。
Gold 为 `CLARIFY` 的实例只在 RQ3 中评价，不进入 RQ4 分母。

### 6.2 我们编写 hidden validator

Benchmark 作者根据当前 target 和 Gold Requirement，为每个 RQ4 target 编写一个专属的
hidden validator。例如：

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

要真正使用 Claude Code、Codex 或其他 Coding Agent 跑测试，只需要实现四个组件：

1. `public_materializer`：生成 C1/C2/C3 的安全输入目录；
2. `agent_runner`：在独立 workspace 中调用 Agent，并保存 JSON、patch 和日志；
3. `rq1_rq2_rq3_scorer`：读取结构化回答并与审核后的 Gold 比较；
4. `rq4_validator_runner`：执行 target-specific hidden validator，根据 exit code 生成
   `rq4_pass`。

当前 RQ instances 仍包含 provisional Gold，且 RQ4 的 `acceptance_criteria`、
`validator_ids` 为空、`execution_ready=false`。因此现阶段可以测试 materialization 和 Agent
运行流程，但在 Gold review 和 hidden validators 完成前不能发布正式分数。

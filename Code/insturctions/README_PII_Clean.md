# PII Clean 运行命令

本文只讲**怎么跑**。流程设计见
[`Constuction_guideline/PII 流程详解.md`](../../Constuction_guideline/PII%20流程详解.md)。

实现入口：

- 流水线：`Code/PII/`
- 命令行：`Code/pii_clean.py`（主流程）、`Code/pii_finalize.py`（离线 finalize）
- Prompt：`prompt/PII/`
- 测试：`Code/tests/test_pii_audit.py`、`test_pii_plan.py`、`test_pii_pipeline.py`

## 环境变量

```powershell
$env:UPWORK_API_KEY = "..."
$env:UPWORK_BUDGET_ID = "..."
```

`pii_finalize.py` 不读凭据，完全离线运行。

---

## 1. 本地预检查（不调 API）

```powershell
python .\Code\pii_clean.py --dry-run
python .\Code\pii_clean.py --dry-run --project-id 42204309
```

输出每个项目的消息数、Secret 候选数与类型、以及词数分桶分布。**全量运行前先看这份报告**，
确认 Secret 候选里没有被误判的料号、文件名或 URL 参数。

查看阶段名（`--force-phase` / `--stop-after-phase` 要用）：

```powershell
python .\Code\pii_clean.py --list-phases
```

---

## 2. 运行

处理全部项目：

```powershell
python .\Code\pii_clean.py --insecure
```

只处理一个项目：

```powershell
python .\Code\pii_clean.py --project-id 42204309 --insecure
```

重复 `--project-id` 可指定多个。

明确指定输入输出：

```powershell
python .\Code\pii_clean.py `
  --source-root .\Datasets\project `
  --output-root .\Datasets\PII_clean_project `
  --work-root .\outputs\pii_runs `
  --insecure
```

补充必须原样保留的术语，或必须被替换的私有名称：

```powershell
python .\Code\pii_clean.py `
  --project-id 42204309 `
  --preserve-term "Small Block" `
  --preserve-term "Big Block" `
  --extra-private-term "Project Rebuild" `
  --insecure
```

分阶段推进（用于先看中间产物，不提交任何输出）：

```powershell
python .\Code\pii_clean.py --project-id 42204309 --stop-after-phase PHASE_2_TRANSFORMATION_PLAN --insecure
```

---

## 3. 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--model` | `stage1` 的 `ANNOTATION_MODEL` | 模型 |
| `--reasoning-effort` | `stage1` 的 `REASONING_EFFORT` | 全局推理强度 |
| `--phase-effort PHASE=LEVEL` | 见下 | 单阶段覆盖，可重复 |
| `--max-batch-messages` | 40 | 每请求最多消息数 |
| `--max-batch-chars` | 30000 | 每请求最多字符数（与上者同时生效） |
| `--neighbor-window` | 2 | Phase 1A 的邻居上下文条数 |
| `--semantic-fold-chars` | 60000 | Phase 1B 每个 fold 的字符上限 |
| `--max-accumulator-chars` | 250000 | Phase 1B 累加器硬上限（超限报错，不截断） |
| `--plan-chunk-bundles` | 25 | Phase 2 每块的 identity bundle 数 |
| `--max-repair-attempts` | 2 | Phase 5 定向修复次数 |
| `--project-concurrency` | 2 | 并行项目数 |
| `--max-concurrent-requests` | 4 | 并行请求数 |
| `--retries` | 3 | 单请求重试次数 |
| `--timeout` | 900 | 单请求超时（秒） |
| `--insecure` | 关 | 关闭 TLS 校验，仅受信任环境 |
| `--keep-run-artifacts` | 关 | 成功后保留含 PII 的过程文件（默认自动删除） |

默认已按阶段设置推理强度（1B / 2 / 4 用 `max`，3 / 5 用 `high`，其余用全局值）。要调整：

```powershell
python .\Code\pii_clean.py --phase-effort PHASE_3_REWRITE=max --phase-effort PHASE_0B_PII_DISCOVERY=high --insecure
```

---

## 4. 断点续跑

`--resume` 默认开启。已完成的项目会被跳过；未完成的项目从每个阶段已验证的分片继续。

| 需求 | 命令 |
|---|---|
| 中断后继续 | 重跑同一条命令即可 |
| 重跑已完成的项目 | 加 `--overwrite` |
| 完全从头 | 加 `--no-resume`（清空该项目全部阶段产物） |
| 只重算某阶段及其下游 | `--force-phase <PHASE>` |
| 只跑到某阶段 | `--stop-after-phase <PHASE>` |

```powershell
# 改了 Prompt 后只重算受影响的阶段
python .\Code\pii_clean.py --project-id 42204309 --force-phase PHASE_0B_PII_DISCOVERY --insecure

# 方案需要重新生成（状态为 REPLAN_REQUIRED 时）
python .\Code\pii_clean.py --project-id 42204309 --force-phase PHASE_1B_PROJECT_CONSOLIDATION --insecure
```

`--force-phase` 会连带重算该阶段在依赖图上的**全部下游**，上游与旁支保留。
改 Prompt 无需加 `--force-phase`：Prompt 哈希已进入该阶段的输入哈希，会自动失效。

**唯一会拒绝续跑的情况**：`Datasets/project/<pid>/chat_messages.json` 本身变了。此时消息序号
不再可信，命令会报错并提示用 `--no-resume` 或换一个 `--work-root`。

---

## 5. 出现问题 message 时的 Agent 修复流程

多次修复失败的 message **不会**被悄悄替换成原文，也不会让程序停止：它被隔离、记录，运行
继续，因此**一次运行就能把该项目所有有问题的 message 找全**。只要还有未解决的 message，
就不会产出最终 `chat_messages.json`。

### 步骤 1：看状态

```powershell
python .\Code\pii_clean.py --project-id 42204309 --status
```

关注 `status` 字段：

| status | 含义 | 动作 |
|---|---|---|
| `PASSED` | 已完成 | 无需处理 |
| `BLOCKED_RETRYABLE` | 只有网络错误 | **重跑第 2 节的命令即可**，不需要 Agent |
| `AWAITING_AGENT_REPAIR` | 有内容问题 | 进入步骤 2 |
| `AGENT_REPAIR_REJECTED` | 上次提交被拒 | 看 `repair_result.json` 后重交 |
| `REPLAN_REQUIRED` | 方案级问题 | `--force-phase PHASE_1B_PROJECT_CONSOLIDATION`（见第 4 节） |
| `FATAL` | 结构性问题 | 看审计报告，需改代码或源数据 |

命令同时打印每个项目的 `next_command`。

### 步骤 2：生成提交骨架（可选，但推荐）

```powershell
python .\Code\pii_finalize.py --project-id 42204309 --write-template
```

在 `outputs\pii_runs\42204309\agent_repairs\repairs.template.json` 生成预填骨架，
`task_id` 与两个哈希都已填好。

### 步骤 3：让 Agent 修复

在 Claude Code 里粘贴这段：

```text
请阅读 prompt/PII/agent_repair_instructions.md，然后修复项目 42204309 的问题 message。

任务队列： outputs/pii_runs/42204309/agent_tasks/index.json
提交文件： outputs/pii_runs/42204309/agent_repairs/repairs.json
骨架：     outputs/pii_runs/42204309/agent_repairs/repairs.template.json

只修改提交文件。不要运行流水线，不要改校验器或审计代码。
```

任务包里也带了 `instructions_path`，说明文档的副本同时写在
`outputs\pii_runs\42204309\agent_tasks\repair_instructions.md`。

### 步骤 4：校验（不写任何输出）

```powershell
python .\Code\pii_finalize.py --project-id 42204309 --validate-only
```

被拒时会逐条打印原因，详情写入
`outputs\pii_runs\42204309\agent_repairs\repair_result.json`。把结果交回 Agent 再改一轮。

### 步骤 5：提交

```powershell
python .\Code\pii_finalize.py --project-id 42204309
```

全部校验与审计通过后，写出最终 `Datasets\PII_clean_project\42204309\chat_messages.json`
与 manifest，并删除含 PII 的过程文件。

**只要还有未覆盖的任务、被拒的提交，或任何审计违规，就不会提交任何输出。**

### 批量 finalize

```powershell
# 所有有运行目录的项目
python .\Code\pii_finalize.py --validate-only
python .\Code\pii_finalize.py

# 只看状态
python .\Code\pii_finalize.py --status
```

### 关于 `EXTRACTION` 类任务

任务的 `kind` 为 `EXTRACTION` 时（`blocked_phase` 是 `EXTRACTION`），Agent 交付的是缺失的
标注而非最终文本。这类提交由**下一次 `pii_clean.py`** 消费，不是 `pii_finalize.py`：

```powershell
python .\Code\pii_clean.py --project-id 42204309 --insecure
```

---

## 6. 输出与过程目录

```text
Datasets\PII_clean_project\            已发布产物
├── <project_id>\
│   ├── chat_messages.json             自然合成内容，无 sender_id / created_ts
│   └── ...                            其他文件原样复制（未脱敏）
└── _manifests\<project_id>.json

outputs\pii_runs\<project_id>\         过程文件（含 PII，成功后自动删除）
├── run_metadata.json                  状态 + next_command（指纹级，保留）
├── source_signature.json
├── resolved_buckets.json
├── phase0a_secret_shield\ ... phase6_render\
├── unresolved\{ledger.jsonl, summary.json}   （指纹级，保留）
├── agent_tasks\{index.json, task_NNNNN.json, repair_instructions.md}
└── agent_repairs\{repairs.json, repairs.template.json, repair_result.json}

outputs\pii_logs\{api_calls.jsonl, failed_responses\, batch_failures.json}
```

`outputs\pii_runs\` 与 `outputs\pii_logs\` 已在 `.gitignore` 中，**不要提交**。
`run_metadata.json`、`unresolved\summary.json` 与 `phase6_render\audit_report.json`
只含指纹与计数，成功后保留作为审计线索。

---

## 7. 测试

```powershell
python -m unittest discover -s Code/tests -p "test_pii_*.py" -v

# 单个模块
python -m unittest Code.tests.test_pii_audit -v      # Phase 6 渲染与审计
python -m unittest Code.tests.test_pii_plan -v       # Phase 2 方案与 slice 闭包
python -m unittest Code.tests.test_pii_pipeline -v   # 端到端、续跑、失败与 Agent 闭环

# 全仓库
python -m unittest discover -s Code/tests
```

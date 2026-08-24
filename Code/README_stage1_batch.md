# ReqMemBench Stage 1 batch annotation

The default workflow uses `prompt/stage1_prompt_v2.md`, `gpt-5.6-sol`, and `high` reasoning.
`EVENT_VERIFICATION` additionally uses `prompt/stage1_event_verification_addendum.md` for stricter source alignment and execution-event pruning.
`CROSS_REQUIREMENT_IMPACT_AUDIT` uses `prompt/stage1_cross_requirement_impact_audit.md` to judge candidates across all Requirement families.
Credentials are read only from `UPWORK_API_KEY` and `UPWORK_BUDGET_ID`.

The current output schema is annotation `v0.6`. Every Event contains `value_removals`; a MODIFY may delete obsolete top-level attributes before applying `value_updates`. After the global consistency audit, the pipeline replays provisional states at each material MODIFY/REMOVE, retrieves cross-Requirement candidates from title/current attributes/scope/history/family/shared entities, and asks the impact audit for `ADD_EVENT`, `EDIT_EVENT`, `NO_IMPACT`, or `HUMAN_REVIEW`. Only HIGH-confidence ADD/EDIT decisions are applied. The minimum-lifecycle filter now runs after this audit so a short Requirement is not discarded before it can receive a necessary propagated Event.

New checkpoints and reports:

```text
impact_audited_state.json
impact_audit/<phase>/round_NN/*.json
cross_requirement_impact_audit.json
```

Relevant controls:

```text
--force-stage cross_requirement_impact_audit
--max-impact-audit-rounds 2
--max-impact-candidates-per-event 12
```

Incrementally upgrade one existing v0.5/v0.6 annotation instead of rerunning the
full Stage 1 pipeline:

```powershell
& 'D:\Python_env\Miniconda\python.exe' Code\stage1_batch_annotate.py `
  --dataset-root 'Pilot Benchmark' `
  --project-id 42204309 `
  --upgrade-existing-annotation 'outputs\stage1_annotations\42204309_stage1_annotation.json' `
  --output-dir 'outputs\stage1_annotations_v06' `
  --run-root 'outputs\stage1_upgrade_runs' `
  --stats-file 'outputs\stage1_annotations_v06\statistics.csv' `
  --insecure
```

This mode freezes and reuses the existing Requirement inventory and Events. It
skips `EVIDENCE_SCAN`, `REQUIREMENT_DISCOVERY`, `EVENT_EXTRACTION`, and the old
general `CONSISTENCY_AUDIT`. It runs only the migration-specific
`VALUE_REMOVAL_AUDIT`, `CROSS_REQUIREMENT_IMPACT_AUDIT`, verification for
Requirements actually changed by those audits, deterministic v0.6 assembly,
and validation. The separate output directory above preserves the original
annotation for comparison. Checkpoints are resumable by default.

Run one project in resumable multi-pass mode:

```powershell
python Code/stage1_batch_annotate.py --project-id 42204309 --insecure
```

`--resume` is enabled by default. Do not add `--no-resume` unless every semantic checkpoint should be regenerated.

Rerun only one Requirement's verifier after changing the verification addendum:

```powershell
python Code/stage1_batch_annotate.py --project-id 42204309 --force-stage event_verification --force-requirement REQ_AAVE_PRIZE_POOL_YIELD --insecure
```

This reuses Evidence Scan, Requirement Discovery, Event Extraction, and Consistency Audit checkpoints. It reruns only the selected Requirement's Event Verification and final assembly.

## 整体 Pipeline 架构

### 设计目标

默认的 `multipass` Pipeline 将“发现证据、建立 Requirement ontology、提取 lifecycle、全局纠错、逐项验证和最终组装”拆开执行。这样做的核心原因是：

- Requirement 边界是项目级问题，不能只看单条消息；
- Event 必须逐 Requirement 对齐证据，不能在一次超大生成中混合路由；
- 全局 Audit 需要看到所有 Requirement 和 Events 才能发现 overlap、漏标和错路由；
- Verification 需要回到单个 Requirement 和原始消息，独立判断每个 provisional Event；
- 最终 JSON 的排序、ID、短 lifecycle 过滤和 Schema 校验应由确定性代码完成，而不是交给模型自由生成。

Stage 1 只生成 Sessions、Requirement Families、Requirements 和 Requirement Events。它不构建 Stage 2 的 Current State、State Graph、evaluation instances 或 benchmark answers。

### 一张图看完整数据流

```text
Datasets/<project_id>/
        |
        v
[0. Project discovery + deterministic preprocessing]
        |
        +--> normalized_project.json
        +--> pipeline_config.json
        |
        v
[1. EVIDENCE_SCAN]  每个消息分块一次 LLM 调用
        |
        +--> evidence_chunks/chunk_*.json
        +--> evidence_scan.json
        |
        v
[2. REQUIREMENT_DISCOVERY]  全项目一次 LLM 调用
        |
        +--> Sessions
        +--> Requirement Families
        +--> frozen Requirement inventory
        +--> unresolved_candidates
        +--> requirement_discovery.json
        |
        v
[3. EVENT_EXTRACTION]  每个 Requirement 一次 LLM 调用
        |
        +--> events/<requirement_id>.json
        +--> event_extraction_findings.json
        |
        v
[Lifecycle filter #1: event_count < 3]
        |
        +--> discarded_requirements.json
        |
        v
[4. CONSISTENCY_AUDIT]  每轮一次全项目 LLM 调用
        |
        +--> consistency_audit_round_N.json
        +--> deterministic patch application
        +--> boundary changed? re-extract affected Requirements
        +--> audited_state.json
        +--> Audit human-review items
        |
        v
[Lifecycle filter #2: event_count < 3]
        |
        v
[5. EVENT_VERIFICATION]  每个保留 Requirement 一次 LLM 调用
        |
        +--> verification/<requirement_id>.json
        +--> apply KEEP / EDIT / DELETE
        +--> verified_events.json
        +--> missing_event_candidates -> human_review.json
        |
        v
[Lifecycle filter #3: event_count < 3]
        |
        v
[6. Deterministic final assembly + validation]
        |
        +--> human_review.json
        +--> final/<project_id>_stage1_annotation.json
        +--> outputs/stage1_annotations/<project_id>_stage1_annotation.json
        +--> run_metadata.json
        +--> stage1_requirement_event_statistics.csv
```

图中的 1–5 是五种模型 `RUN_MODE`，不是总共只调用五次 API。Extraction、Verification 和 Evidence Scan 都可能产生很多次请求。

### 阶段 0：项目发现、预处理和运行签名

这一阶段不调用 LLM。

程序从 `--dataset-root`（默认 `Datasets/`）发现项目，找到聊天记录和项目元数据，然后执行确定性预处理：

- 规范化 project ID、标题和输入路径；
- 规范化消息 ID；
- 识别 client / freelancer speaker；
- 保留消息原文、时间和原始顺序；
- 读取可用 milestone 信息；
- 对缺失 ID 和排序做确定性处理；
- 写出 `normalized_project.json`。

随后代码建立 `pipeline_config.json` 恢复签名。签名包含模型、Prompt 哈希、规范化输入哈希、分块大小、上下文模式、上下文上限和 Audit 配置等，用于判断已有 checkpoint 是否仍可安全复用。

关键点：

- `normalized_project.json` 是后续证据完整性的基准；
- Event 的 message ID、speaker 和 text 最终必须与这里一致；
- 修改原始聊天、主 Prompt 或关键语义配置可能使旧 checkpoint 失效；
- reasoning effort 属于兼容的运行参数，可以在复用语义 checkpoint 时调整。

### 阶段 1：`EVIDENCE_SCAN`

#### 目标

快速浏览完整聊天记录，找出可能涉及 Requirement 生命周期、范围、执行状态或歧义的消息，减少后续阶段需要读取的上下文。

#### 调用粒度

聊天按以下参数分块：

```text
--evidence-chunk-size 150
--evidence-chunk-overlap 10
```

每个 chunk 单独调用一次模型。overlap 用于避免跨 chunk 的短上下文被截断。

#### 输入

- project metadata；
- 当前 chunk 的原始消息。

#### 输出

每个 chunk 输出候选证据，包括 message ID、evidence tags、topic hints、context message IDs 和 confidence。代码验证所有 message ID 必须真实存在，然后写入：

```text
evidence_chunks/chunk_0001.json
evidence_chunks/chunk_0002.json
...
```

所有 chunk 结果再确定性合并为 `evidence_scan.json`。

#### 它不做什么

Evidence Scan 不创建正式 Requirement，也不创建 Event。候选少不等于最终 Event 少；候选只是后续检索索引。

### 阶段 2：`REQUIREMENT_DISCOVERY`

#### 目标

建立项目级 ontology：

- Sessions；
- 可选 Requirement Families；
- 独立、可演化的 Requirement atoms；
- anchor message IDs；
- scope hypothesis；
- boundary note；
- unresolved candidates。

#### 调用粒度

通常每个项目一次全局调用。

#### 输入

- project metadata；
- 合并后的 Evidence Index；
- Evidence Scan 选中的消息及配置的相邻上下文。

Discovery 不一定收到完整聊天全文；它主要收到候选证据和 `--context-window` 扩展出的附近消息。

#### 输出和校验

输出保存在 `requirement_discovery.json`。代码至少校验：

- Session、Family、Requirement ID 非空且唯一；
- Requirement 引用的 Family 存在；
- anchor message ID 在原始项目中存在；
- confidence 和字段结构合法。

此阶段冻结初始 Requirement inventory。Event Extraction 只能为该 inventory 中的 Requirement 提取 Events；新 Requirement 候选必须交给 Audit 处理。

### 阶段 3：`EVENT_EXTRACTION`

#### 目标

为一个目标 Requirement 提取完整的 chronological lifecycle/execution Events。

#### 调用粒度

一个 Requirement 一次调用。若 Discovery 发现 `R` 个 Requirements，第一次 Extraction 通常需要 `R` 次成功调用。

程序使用 `asyncio.gather` 并发调度多个 Requirement，但真正同时进行的 HTTP 请求受 `--max-concurrent-requests` 限制。

#### 输入

每次调用只针对一个 `TARGET_REQUIREMENT`，同时提供：

- 目标 Requirement；
- 目标及必要 Family siblings 的 focused inventory；
- 与目标相关的 Evidence candidates；
- anchor、topic hints 和附近消息构成的 local context；
- 当前项目元数据。

默认 `--event-context-mode filtered`，每个 Requirement 最多发送 `--max-requirement-context-messages 160` 条重点消息。`full_history` 会发送更完整的历史，但 token 成本显著更高。

#### 输出

```text
events/<requirement_id>.json
```

每个文件包括：

- `events`：目标 Requirement 的 provisional Events；
- `routing_warnings`：证据更适合已有其他 Requirement；
- `missing_requirement_candidates`：证据独立有意义，但 frozen inventory 没有适合的 Requirement。

代码会：

- 检查输出的 Requirement ID 与目标一致；
- 将模型轻微改写的 source text 恢复为 `normalized_project.json` 中的精确原文；
- 验证 speaker、message ID、时间顺序和 Event payload；
- 汇总 warnings/candidates 到 `event_extraction_findings.json`。

### Lifecycle filter：为什么执行三次

当前 benchmark 只保留至少 `--min-requirement-events 3` 个有效 Events 的 Requirement。这个过滤器在三个位置执行：

| 时点 | 原因 |
|---|---|
| Extraction 后 | 尽早阻止 0–2 Event Requirement 进入高成本全局 Audit 和 Verification。 |
| Audit 后 | Audit 的删除、移动、拆分或重提取可能改变 lifecycle 长度。 |
| Verification 后 | Verifier 的 DELETE 可能使原本合格的 Requirement 降到 3 以下。 |

被淘汰的 Requirement 和当时的 Events 会写入 `discarded_requirements.json`，不会静默丢失。

过滤器还会清理无意义的一成员 Family：

- 一个 Family 少于两个保留 Requirements 时，该 Family 被移除；
- 原成员的 `family_id` 被设为 `null`；
- Requirement 本身只要满足最短 lifecycle，仍可作为 standalone Requirement 保留。

模型不能为了达到 3 Events 而合并 Requirement、发明 Event、重复 Event 或保留弱证据。

### 阶段 4：`CONSISTENCY_AUDIT`

#### 目标

Event Extraction 是逐 Requirement 的局部任务，无法可靠发现所有全局问题。Audit 负责检查：

- duplicate / overlapping Requirements；
- broad Requirement 是否需要拆分；
- attribute over-splitting；
- missing Requirement；
- Event 错路由；
- Event 类型错误；
- client/freelancer authority；
- execution-event inflation；
- source evidence misalignment；
- Family 和 Session 问题。

#### 调用粒度

每个 Audit round 是一次全项目调用。默认：

```text
--max-audit-rounds 1
```

如果某轮没有改变 Requirement 边界，Pipeline 会提前停止；如果有边界变化，则重新提取受影响 Requirements。配置为多轮时，下一轮会审查更新后的 inventory/Events。

#### 输入

- 当前完整 retained inventory；
- 当前所有 retained Events；
- Event Extraction 汇总的 routing warnings；
- missing Requirement candidates。

Audit 通常是单次输入上下文最大的调用，也是主要 token 消耗点之一。

#### 输出：patches

Audit 不直接重写最终 JSON，而是输出 patch list：

```text
ADD_REQUIREMENT
MERGE_REQUIREMENTS
SPLIT_REQUIREMENT
DELETE_REQUIREMENT
CHANGE_FAMILY
ADD_EVENT
DELETE_EVENT
EDIT_EVENT
MOVE_EVENT
CHANGE_SESSION
HUMAN_REVIEW
```

代码按顺序应用 patches：

- HIGH-confidence、非 `HUMAN_REVIEW` 且结构有效的 patch 自动应用；
- MEDIUM/LOW-confidence patch 不自动应用，进入 `human_review.json`；
- `HUMAN_REVIEW` 始终进入人工复核；
- 应用失败的 patch 带 `application_error` 进入人工复核；
- Requirement ID 必须保持非空且唯一。

#### 边界变化后的重提取

`ADD_REQUIREMENT`、`MERGE_REQUIREMENTS`、`SPLIT_REQUIREMENT` 或 `DELETE_REQUIREMENT` 会让 ontology boundary 发生变化。代码在完成当前轮 patch application 后，对受影响、仍存在的 Requirements 重新执行 Event Extraction。

如果最后允许的一轮仍改变边界，代码增加：

```json
{
  "source": "CONSISTENCY_AUDIT",
  "reason": "Requirement boundaries still changed in the final configured audit round.",
  "affected_requirement_ids": []
}
```

这是一条稳定性警告，不表示所有 affected Requirements 都错误。

Audit 应用后的完整 checkpoint 写入 `audited_state.json`。该文件包含 inventory、Events、Audit human-review items、patch 数量和输入哈希。

### 阶段 5：`EVENT_VERIFICATION`

#### 目标

对 Audit 后的每个 provisional Event 再做一次目标级证据验证，重点检查：

- source 是否真的支持一个 Event；
- source 是否支持这个具体 Requirement；
- event type 是否正确；
- implementation claim / runtime failure / runtime verification 是否混淆；
- partial success 是否被错误扩大为全目标 verification；
- execution Event 是否重复或没有 lifecycle novelty；
- value/scope 是否超出证据。

#### 调用粒度

每个 Audit 后保留的 Requirement 一次调用。若过滤后有 `V` 个 Requirements，Verification 通常需要 `V` 次成功调用。

#### 输入

- 单个 target Requirement；
- focused target inventory；
- 该 Requirement 的 provisional Events；
- Events 附近的 raw local context；
- 与该 Requirement 相关的 Audit human-review items；
- 主 Prompt；
- 仅此阶段使用的 `stage1_event_verification_addendum.md`。

#### 输出和确定性应用

Verifier 对已有 Event 返回：

```text
KEEP
EDIT
DELETE
```

代码确定性应用 EDIT/DELETE，然后生成 `verified_events.json`。

Verifier 还可以输出 `missing_event_candidates`，但 Pipeline 不会自动 ADD。这些候选被包装为：

```json
{
  "source": "EVENT_VERIFICATION",
  "requirement_id": "REQ_EXAMPLE",
  "missing_event_candidate": {}
}
```

并写入 `human_review.json`。这是为了避免 verifier 在最终阶段绕过 Extraction/Audit 直接发明或错路由 Event。

### 阶段 6：最终组装和严格校验

这一阶段不调用 LLM。

代码使用最终 inventory 和 verified Events：

1. 删除少于两个成员的 Family，并把对应 Requirement 变为 standalone；
2. 按原始消息顺序稳定排序 Events；
3. 为每个 Requirement 生成连续 Event ID：

```text
<requirement_id>_E001
<requirement_id>_E002
...
```

4. 删除 intermediate-only 的 `supporting_message_ids`；
5. 只保留 canonical Stage 1 Event 字段；
6. 组装 Sessions、Families、Requirements 和 Events；
7. 执行最终验证。

最终验证包括：

- benchmark/version/project ID；
- Session、Family、Requirement ID 唯一且非空；
- Family 引用存在；
- Event ID 连续且全局唯一；
- Event chronological order；
- source message ID 存在；
- speaker 和原始 text 精确一致；
- canonical Event fields 和 payload 结构合法。

只有通过最终验证后，文件才会写入：

```text
outputs/stage1_runs/<project_id>/final/<project_id>_stage1_annotation.json
outputs/stage1_annotations/<project_id>_stage1_annotation.json
```

随后更新项目 `run_metadata.json` 和全局统计 CSV。

### `human_review.json` 在 Pipeline 中的位置

`human_review.json` 是多个阶段问题的汇总，而不是单独的一次模型调用。它在 Verification 后、final assembly 前写出，内容来自：

```text
Audit HUMAN_REVIEW
Audit MEDIUM/LOW patches
Audit application_error
final Audit round boundary warning
Verification missing_event_candidates
Discovery unresolved_candidates
Discovery LOW-confidence Requirements
```

这些记录不会自动进入最终 annotation。详细 Schema 和处理流程见本文后面的“`human_review.json` 详解”。

### Checkpoint 与 `--resume`

默认启用 `--resume`。每个模型阶段都有独立 checkpoint；程序复用 checkpoint 前会重新解析并验证其 JSON。

| Stage | 主要 checkpoint | 额外失效条件 |
|---|---|---|
| Evidence Scan | `evidence_chunks/chunk_*.json` | chunk/schema/输入签名变化或强制 Evidence。 |
| Discovery | `requirement_discovery.json` | schema、anchor IDs、上游强制。 |
| Extraction | `events/<requirement_id>.json` | Event schema/证据完整性失败，或目标 Requirement 被强制/边界变化。 |
| Audit | `consistency_audit_round_N.json` + `.meta.json`；汇总为 `audited_state.json` | inventory、Events、extraction findings 哈希变化，ID 不合法或 Audit 被强制。 |
| Verification | `verification/<requirement_id>.json` + `.meta.json` | target inventory、provisional Events、相关 Audit review 或 verification addendum 哈希变化。 |

如果 checkpoint JSON 损坏、Schema 不合法或 source text 不匹配，程序会显示：

```text
[checkpoint invalid] ...; rerunning
```

然后只重新请求该 checkpoint。

`--no-resume` 会忽略所有模型 checkpoint，通常意味着完整重跑和最高 token 成本。

### `--force-stage` 的级联关系

强制一个上游阶段会自动使其所有下游阶段失效：

```text
evidence_scan
    -> requirement_discovery
        -> event_extraction
            -> consistency_audit
                -> event_verification
                    -> assembly
```

| 命令 | 实际影响 |
|---|---|
| `--force-stage evidence_scan` | 从 Evidence 开始全部重跑。 |
| `--force-stage requirement_discovery` | 复用 normalized/Evidence；重跑 Discovery 及全部下游。 |
| `--force-stage event_extraction` | 复用 Discovery；重跑 Extraction 及全部下游。 |
| `--force-stage consistency_audit` | 复用已有 Extraction；重跑 Audit、Verification 和 assembly。 |
| `--force-stage event_verification` | 复用 Audit；重跑 Verification 和 assembly。 |
| `--force-stage assembly` | 不调用 LLM，只重新组装 final。 |

`--force-requirement REQ_X` 用于缩小按 Requirement 执行的阶段。最精确、成本最低的组合是：

```powershell
--force-stage event_verification --force-requirement REQ_X
```

它只重跑目标 verifier。若从 Extraction 强制目标 Requirement，后续全局 Audit 仍需重新运行，因为该 Requirement 的 Events 已变化。

### API 调用数量与主要 token 消耗

一次 multipass 项目的成功调用数可近似表示为：

```text
Evidence chunks
+ 1 Requirement Discovery
+ discovered Requirements 的首次 Event Extraction
+ Audit rounds
+ Audit 边界变化引发的受影响 Requirement 重提取
+ Audit 后保留 Requirements 的 Event Verification
```

可写成：

```text
successful_calls ≈ C + 1 + R + A + R_changed + V
```

其中：

- `C`：Evidence chunks 数；
- `R`：Discovery 得到的 Requirements 数；
- `A`：实际执行的 Audit rounds；
- `R_changed`：Audit 边界变化后重新提取的 Requirement 次数；
- `V`：Audit 后、最短 lifecycle 过滤后保留的 Requirements 数。

重试会增加 `total_attempts`，但不增加成功调用公式中的 stage count。

通常最大的 token 消耗来自：

1. 每个 Requirement 重复携带局部上下文的 Event Extraction；
2. 携带全 inventory 和全部 Events 的 Consistency Audit；
3. 每个 Requirement 独立进行的 Event Verification；
4. Audit 拆分/新增 Requirement 后触发的重提取和 verifier refresh。

因此以下配置最直接影响成本：

```text
--event-context-mode filtered
--max-requirement-context-messages 160
--min-requirement-events 3
--max-audit-rounds 1
--max-concurrent-requests 4
```

并发只降低墙钟时间，不减少 token。

### 重试、失败记录和项目级隔离

API client 的默认行为：

- 第一次 LLM 调用前使用 `UPWORK_API_KEY` 获取 JWT；
- 使用 `Authorization: Bearer <JWT>` 和 `UPWORK_BUDGET_ID` 调用网关；
- 复用 JWT；遇到 401 时强制刷新；
- 408/409/429/500/502/503/504、HTTP 错误、JSON 解析错误和 validator 错误可重试；
- `--retries 3` 表示最多 4 次 attempt；
- 重试等待采用有上限的指数退避；
- `--timeout 900` 表示单请求最长 15 分钟。

每次 attempt 都写入：

```text
outputs/stage1_logs/api_calls.jsonl
```

失败响应写入：

```text
outputs/stage1_logs/failed_responses/
```

如果一个项目最终失败：

- `run_metadata.json.status` 变为 `FAILED`；
- `error` 保存终止原因；
- 项目加入 `stage1_batch_failures.json`；
- 已成功 checkpoint 保留，可在修复后续跑；
- 批量任务中的其他项目不必因此失败；
- 全局统计只读取成功写入 `stage1_annotations/` 的最终标注。

### Multi-pass 与 Single-pass 的区别

`--annotation-mode single-pass` 是兼容/对照模式，不是默认推荐流程。

| 能力 | Multi-pass | Single-pass |
|---|---|---|
| Evidence Scan | 有 | 无 |
| Requirement Discovery | 独立阶段 | 与 Event 一次生成 |
| 每 Requirement Extraction | 有 | 无 |
| Consistency Audit | 有 | 无 |
| Event Verification | 有 | 无 |
| 三次最短 lifecycle 过滤 | 有 | 无 |
| `human_review.json` 汇总 | 有 | 无完整 multi-pass review |
| Checkpoint 粒度 | 细，可局部续跑 | 粗 |
| API 调用 | 多 | 通常 1 |
| 推荐用途 | 正式 Stage 1 标注 | 成本/质量 baseline 或兼容测试 |

## Token controls

### Final zero-Requirement project filter

After the last lifecycle-length filter and final assembly, the pipeline checks the
final `requirements` array. If it is empty, the project is excluded from the
published Stage 1 dataset:

- no `<project_id>_stage1_annotation.json` is retained in `outputs/stage1_annotations/`;
- no run-local final copy is retained in `outputs/stage1_runs/<project_id>/final/`;
- the project is not counted by `stage1_requirement_event_statistics.csv`;
- `run_metadata.json.status` is set to `EXCLUDED_NO_REQUIREMENTS`, so the default
  `--resume` workflow does not spend API tokens annotating the same empty project again.

The remaining run checkpoints and `run_metadata.json` are diagnostic/resume state,
not published annotations. At the start of a non-dry run, the same rule also removes
legacy final annotation files whose `requirements` array is already empty.

- `--event-context-mode filtered` is the default. It uses anchors and evidence topic hints instead of sending almost the complete transcript for every Requirement.
- `--max-requirement-context-messages 160` caps the focused raw-message context while preserving anchors and chronological coverage.
- `--min-requirement-events 3` removes short lifecycles before Audit, Verification, and final assembly.
- Consistency Audit receives the retained inventory and Events plus aggregated routing warnings and missing-Requirement candidates from Event Extraction.
- Target-specific Audit `HUMAN_REVIEW` items are passed into Event Verification and included in its checkpoint hash.
- Verification checkpoints also depend on the target inventory and verification-addendum hash, so a verifier-only policy change does not require regenerating upstream stages.
- Reasoning effort can be changed with `--reasoning-effort low|medium|high|xhigh`. It does not invalidate compatible semantic checkpoints.

Discarded short lifecycles are retained for analysis at:

```text
outputs/stage1_runs/<project_id>/discarded_requirements.json
```

## Important options

```text
--model gpt-5.6-sol
--reasoning-effort high
--verification-addendum-file prompt/stage1_event_verification_addendum.md
--max-concurrent-requests 4
--project-concurrency 1
--evidence-chunk-size 150
--evidence-chunk-overlap 10
--context-window 2
--event-context-mode filtered|full_history
--max-requirement-context-messages 160
--min-requirement-events 3
--max-audit-rounds 1
--retries 3
--timeout 900
```

## Outputs

```text
outputs/
|-- stage1_annotations/<project_id>_stage1_annotation.json
|-- stage1_runs/<project_id>/
|   |-- evidence_chunks/
|   |-- events/
|   |-- final/
|   |-- verification/
|   |-- audited_state.json
|   |-- consistency_audit_round_1.json
|   |-- consistency_audit_round_1.meta.json
|   |-- consistency_audit_round_2.json
|   |-- consistency_audit_round_2.meta.json
|   |-- discarded_requirements.json
|   |-- event_extraction_findings.json
|   |-- evidence_scan.json
|   |-- human_review.json
|   |-- normalized_project.json
|   |-- pipeline_config.json
|   |-- requirement_discovery.json
|   |-- run_metadata.json
|   `-- verified_events.json
|-- stage1_logs/api_calls.jsonl
`-- stage1_requirement_event_statistics.csv
```

## 单项目运行目录说明

`outputs/stage1_runs/<project_id>/` 是一个项目的完整可续跑工作目录。它既包含最终结果，也包含每个阶段的模型原始输出、代码应用补丁后的状态和恢复任务所需的检查点。正常分析时使用 `final/` 或 `outputs/stage1_annotations/` 中的最终标注；排查问题和人工复核时再查看其他文件。

### 文件夹

| 路径 | 作用 | 是否属于最终结果 |
|---|---|---|
| `evidence_chunks/` | Evidence Scan 分块结果。长聊天记录会被拆成多个 chunk，每个文件保存该分块识别出的候选证据。 | 否，属于上游检查点。 |
| `events/` | Event Extraction 的逐 Requirement 原始结果，通常一个 Requirement 一个 JSON。包含暂定 Events、`routing_warnings` 和 `missing_requirement_candidates`。这里可能仍包含之后因少于 3 个 Events 而被淘汰的 Requirement。 | 否，属于审计前的中间结果。 |
| `verification/` | Event Verification 的逐 Requirement 判定结果。每个普通 JSON 保存 `KEEP`、`EDIT`、`DELETE` verdict；对应的 `.meta.json` 保存输入哈希、verification addendum 哈希等检查点信息。 | 否，应用 verdict 后的汇总结果见 `verified_events.json`。 |
| `final/` | 通过 Audit、Verification、最短生命周期过滤和最终 Schema 校验后生成的标准 Stage 1 JSON。成功完成后，同一文件还会复制到 `outputs/stage1_annotations/`。 | 是。 |

### 根目录 JSON 文件

| 文件 | 作用 | 使用建议 |
|---|---|---|
| `normalized_project.json` | 由代码对原始项目数据进行确定性预处理后的结果，包括规范化消息 ID、speaker、时间、消息顺序、项目元数据和可用 milestone 信息。后续所有 evidence 校验都以它为原始证据基准。 | 排查消息文本、speaker、时间顺序或 source-message mismatch 时查看。 |
| `pipeline_config.json` | 本次运行的恢复签名，包括模型、reasoning effort、Prompt 哈希、输入数据哈希、上下文配置、最短 Event 数量和 Audit 轮数等。 | `--resume` 用它判断旧检查点能否安全复用；reasoning effort 等运行参数允许兼容变更，不建议手工修改该文件。 |
| `evidence_scan.json` | 合并全部 `evidence_chunks/` 后的候选证据索引。它定位可能涉及 Requirement lifecycle/execution 的消息，但这些候选还不是正式 Events。 | 检查某条消息为什么没有进入后续阶段时查看。 |
| `requirement_discovery.json` | Requirement Discovery 的原始输出，包括 Sessions、Requirement Families、初始 Requirement inventory 和 `unresolved_candidates`。 | 检查 Requirement 是否在最初发现阶段漏标、重复或拆分不当时查看。 |
| `event_extraction_findings.json` | 汇总所有逐 Requirement Extraction 产生的 `routing_warnings` 和 `missing_requirement_candidates`，提供给 Consistency Audit。 | 检查错路由或 Extraction 阶段发现的新 Requirement 候选。 |
| `consistency_audit_round_N.json` | 第 N 轮 Consistency Audit 的模型原始输出，主要内容是结构化 patches，例如 `ADD_REQUIREMENT`、`SPLIT_REQUIREMENT`、`MOVE_EVENT`、`DELETE_EVENT` 和 `HUMAN_REVIEW`。它不等于已经应用后的状态。 | 检查模型在每轮 Audit 建议了哪些修改。 |
| `consistency_audit_round_N.meta.json` | 对应 Audit 轮次的检查点元数据，主要记录输入内容的 SHA-256。输入发生变化时，代码据此判断该轮是否必须重新请求模型。 | 仅用于恢复和失效判断，不包含标注语义。 |
| `audited_state.json` | 代码依次应用高置信度 Audit patches 后的 inventory、Events、待人工复核项和 patch 数量，是进入 Event Verification 前的主要检查点。 | 检查 Audit 建议是否真正应用、Requirement 是否重复，以及 Event 在 Verification 前的状态。 |
| `discarded_requirements.json` | 因有效 Event 数量少于 `--min-requirement-events` 而被排除的 Requirement。保存淘汰阶段、Event 数量、原因和当时的 Events。 | 这些不是解析错误；它们只是未达到后续实例构建的最短 lifecycle 要求。 |
| `verified_events.json` | 对每个保留 Requirement 应用 Event Verification 的 `EDIT` 和 `DELETE` 后得到的 Events 映射。 | 对比 `events/` 可判断 verifier 实际删除或修改了什么。 |
| `human_review.json` | 汇总流水线无法或不应自动决定的问题。详见下一节。 | 完成 Gold 验收前应检查。 |
| `run_metadata.json` | 当前运行状态和统计信息，包括项目 ID、模型、reasoning effort、Prompt 路径/版本/哈希、开始/完成/失败时间、错误、API 调用次数、token 使用量和最终 calibration 指标。调用与 token 数据按当前项目日志汇总，续跑时可能包含累计值。 | 判断任务是否真正完成、使用了哪个 Prompt，以及最近一次失败的原因。 |

## `human_review.json` 详解

`human_review.json` 是一份**待人工复核队列**，不是最终 Stage 1 标注，也不表示其中的修改已经执行。它的外层格式为：

```json
{
  "items": []
}
```

一个项目可以成功生成最终标注，同时仍然存在 human-review items。这表示自动流水线已经完成，但 Gold 验收者还应检查这些不确定项。反过来，编辑或删除 `human_review.json` 中的记录不会自动修改 `audited_state.json`、`verified_events.json` 或最终标注。

### 内容来源

`items` 可能来自以下阶段：

| 来源 | 进入人工复核的原因 |
|---|---|
| `CONSISTENCY_AUDIT` 的 `HUMAN_REVIEW` | 模型发现潜在问题，但证据不足以安全执行 `ADD/EDIT/DELETE/MOVE/SPLIT/MERGE`。 |
| 非 HIGH 置信度 Audit patch | 代码只自动应用 `confidence == "HIGH"` 的非 `HUMAN_REVIEW` patch；MEDIUM/LOW patch 留给人工判断。 |
| Audit patch 应用失败 | patch 的 target、event locator 或 replacement 无法应用。记录中会新增 `application_error`，原始标注不会因这条 patch 被修改。 |
| Audit 最后一轮仍改变 Requirement 边界 | 达到 `--max-audit-rounds` 后 ontology 仍未稳定，记录会带有 `affected_requirement_ids`。 |
| `REQUIREMENT_DISCOVERY` | `unresolved_candidates` 或 LOW-confidence Requirement 无法自动定案。 |
| `EVENT_VERIFICATION` | verifier 在局部证据中发现可能缺失的 Event，记录为 `missing_event_candidate`，但不会直接新增 Event。 |

### 先区分 `operation` 与 `source`

`human_review.json` 中的条目并不只有一种 Schema。判断条目含义时，先看它是以 `operation` 开头，还是以 `source` 开头。

| 识别字段 | 含义 | 谁生成 |
|---|---|---|
| `operation` | 一条具有“修改动作”形状的 Consistency Audit patch，例如删除、移动、拆分或纯人工复核。 | Consistency Audit 模型生成，代码决定是否自动应用。 |
| `source` | 一条由流水线包装的来源记录，表示哪个阶段发现了问题。它通常没有 `targets` / `replacement`，也不是可直接执行的 patch。 | Pipeline 代码根据 Discovery、Audit 或 Verification 输出生成。 |

这里的 `source` 不是聊天消息的 speaker，也不是 Event 的 `source_message`。它只是 human-review item 的来源阶段。

### 类型一：Audit action / `operation` 记录

#### 纯 `HUMAN_REVIEW`

```json
{
  "operation": "HUMAN_REVIEW",
  "targets": {},
  "replacement": null,
  "evidence_message_ids": [170],
  "decision_note": "The evidence does not reliably identify the target Requirement.",
  "confidence": "LOW"
}
```

这表示 Audit 发现了问题，但无法安全决定改哪个对象或怎样改。`targets: {}` 和 `replacement: null` 不是字段缺失，而是明确表示“没有足够证据形成可执行 patch”。

#### 未自动执行或执行失败的动作

```json
{
  "operation": "DELETE_EVENT",
  "targets": {
    "requirement_id": "REQ_EXAMPLE",
    "event_locator": {
      "message_id": 585,
      "event_type": "RUNTIME_FAILURE",
      "occurrence": 1
    }
  },
  "replacement": null,
  "evidence_message_ids": [585],
  "decision_note": "The Event duplicates a narrower Requirement.",
  "confidence": "HIGH",
  "application_error": "Event locator not found: ..."
}
```

`operation` 虽然是 `DELETE_EVENT`，但只要存在 `application_error`，就说明删除没有发生。另一个不会自动执行的情况是 `confidence` 为 `MEDIUM` 或 `LOW`：代码只自动应用 HIGH-confidence、且不是 `HUMAN_REVIEW` 的有效 patch。

| 字段 | 含义 |
|---|---|
| `operation` | 建议动作。可能是 `ADD_REQUIREMENT`、`MERGE_REQUIREMENTS`、`SPLIT_REQUIREMENT`、`DELETE_REQUIREMENT`、`CHANGE_FAMILY`、`ADD_EVENT`、`DELETE_EVENT`、`EDIT_EVENT`、`MOVE_EVENT`、`CHANGE_SESSION` 或 `HUMAN_REVIEW`。 |
| `targets` | 要修改的现有对象。Event 操作一般包含 `requirement_id` 和 `event_locator`；移动操作包含来源/目标 Requirement；拆分、合并和删除 Requirement 使用对应 Requirement ID。 |
| `event_locator.message_id` | Event 的 source message ID。 |
| `event_locator.event_type` | 当前 Event 类型；必须与被定位 Event 完全一致。 |
| `event_locator.occurrence` | 同一 Requirement 中相同 `message_id + event_type` 的第几次出现，从 1 开始。 |
| `replacement` | ADD/EDIT/MERGE/SPLIT 要写入的新结构。DELETE 和纯 HUMAN_REVIEW 通常为 `null`。 |
| `evidence_message_ids` | 复核该建议时应打开的原始消息。它们提供判断线索，但不代表每个 ID 都能独立支持 Event。 |
| `decision_note` | 为什么提出该动作或为什么需要人工判断。它是简要说明，不是隐藏推理，也不能替代原始证据。 |
| `confidence` | 模型对建议的置信度。只有 HIGH 且可成功应用的非 HUMAN_REVIEW patch 才自动修改状态。 |
| `application_error` | 可选。表示自动应用失败，例如 target 已被前一个 patch 改变、Event locator 已失效、Requirement ID 冲突或 replacement 不合法。 |

### 类型二：`source: "CONSISTENCY_AUDIT"`

```json
{
  "source": "CONSISTENCY_AUDIT",
  "reason": "Requirement boundaries still changed in the final configured audit round.",
  "affected_requirement_ids": [
    "REQ_CONTRACT_EVENT_WEBHOOK",
    "REQ_NFT_METADATA_ACCURACY",
    "REQ_NFT_REFERRAL_IDENTITY"
  ]
}
```

这是代码生成的稳定性警告，不是模型 patch。

| 字段 | 含义 |
|---|---|
| `source` | 问题来自 Consistency Audit 阶段。 |
| `reason` | 达到 `--max-audit-rounds` 时，最后一轮仍成功应用了 Requirement 边界变化，因此没有下一轮检查修改后的 ontology 是否稳定。 |
| `affected_requirement_ids` | 最后一轮中被新增、拆分、合并、重建 Events 或以其他方式影响的 Requirement 集合。它是重点检查范围，不表示列表中每个 Requirement 都错误。 |

默认只运行一轮 Audit 时，只要该轮进行了 Requirement 拆分、新增或合并，这种记录就比较常见。它不会自动修改任何内容，也不能转化为某一个固定的 replacement。

### 类型三：`source: "REQUIREMENT_DISCOVERY"`

#### 未决候选 `unresolved_candidate`

```json
{
  "source": "REQUIREMENT_DISCOVERY",
  "unresolved_candidate": {
    "message_ids": [105, 106, 107],
    "description": "A hosting-service choice was requested, but no client decision is visible.",
    "confidence": "LOW"
  }
}
```

| 字段 | 含义 |
|---|---|
| `source` | 问题最早由 Requirement Discovery 发现。 |
| `unresolved_candidate.message_ids` | 与候选 Requirement 或边界问题相关的消息。 |
| `unresolved_candidate.description` | 为什么无法安全创建 Requirement，例如只有 freelancer 提案、没有 client 接受，或行为边界无法确定。 |
| `unresolved_candidate.confidence` | 对“这是一个值得复核的候选”的置信度，不是对 Requirement 已成立的置信度。 |

#### LOW-confidence Requirement

```json
{
  "source": "REQUIREMENT_DISCOVERY",
  "requirement_id": "REQ_LOW_CONFIDENCE_EXAMPLE",
  "reason": "Low-confidence Requirement inventory item"
}
```

这表示 Requirement 已进入 inventory，但 Discovery 将它标为 LOW confidence。人工必须确认它是否是真实、独立且有客户端授权的 Requirement。

### 类型四：`source: "EVENT_VERIFICATION"`

```json
{
  "source": "EVENT_VERIFICATION",
  "requirement_id": "REQ_ETH_MINT_FLOW",
  "missing_event_candidate": {
    "source_message": {
      "message_id": 326,
      "speaker": "client",
      "text": "..."
    },
    "supporting_message_ids": [],
    "event_type": "INTRODUCE",
    "value_updates": {
      "payment_currency": "ETH"
    },
    "scope_updates": null,
    "ambiguity": null,
    "execution": null
  }
}
```

| 字段 | 含义 |
|---|---|
| `source` | Event Verification 在核对目标 Requirement 时发现可能漏掉了 Event。 |
| `requirement_id` | verifier 认为该候选应属于哪个 Requirement。 |
| `missing_event_candidate` | 一个完整但尚未应用的候选 Event。它只是建议，pipeline 不会直接把它加入 `verified_events.json`。 |
| `source_message` | 建议作为 Event 主证据的原始消息。仍需人工检查其文本是否真正蕴含目标 Requirement 和 event type。 |
| `supporting_message_ids` | 仅用于解析指代/接受关系的局部上下文，不能替代主 `source_message` 承担全部语义。 |

missing candidate 可能是真漏标，也可能是重复或错路由。例如同一 message 已经在目标 Requirement 中以另一个正确 event type 存在，或已经由更合适的 Requirement 拥有，此时不应再次添加。

### 重复提醒不等于多个独立问题

同一语义问题可能被多个阶段独立发现，因此 `human_review.json` 中可能出现内容相近的两条记录。例如：

- Discovery 将 Super Admin Dashboard 写为 `unresolved_candidate`；
- Audit 再次对同一组消息输出 `operation: HUMAN_REVIEW`。

这两条应合并为一个人工决策，不应按两个问题分别修改。判断是否重复时比较：

1. `evidence_message_ids` / `message_ids` 是否相同或高度重合；
2. `requirement_id` / `affected_requirement_ids` 是否指向同一语义对象；
3. `decision_note` / `description` 是否在描述同一不确定性。

## Human review 的详细处理流程

### 第 1 步：保存当前可比较版本

在修改 Prompt、代码或强制重跑前，先把当前 `outputs/stage1_runs/<project_id>/` 和最终 JSON 归档。强制重跑会更新 checkpoint；没有旧版本就很难确认问题是否真正改善。

至少保留：

```text
run_metadata.json
human_review.json
requirement_discovery.json
audited_state.json
verified_events.json
final/<project_id>_stage1_annotation.json
```

### 第 2 步：确认条目是否已经实际影响结果

按以下顺序检查：

1. 在 `normalized_project.json` 中打开所有 evidence message，核对 speaker、完整原文和相邻上下文。
2. 在 `requirement_discovery.json` 中确认 Requirement 最初是否存在、定义和边界是什么。
3. 在 `events/<requirement_id>.json` 中确认 Extraction 是否生成过目标 Event。
4. 在 `consistency_audit_round_N.json` 中找到原始 patch。
5. 在 `audited_state.json` 中确认 patch 是否真正应用。
6. 在 `verification/<requirement_id>.json` 中查看 verifier verdict。
7. 在 `verified_events.json` 与 `final/` 中确认最终是否仍存在该问题。

不要仅凭 `decision_note` 决定修改；原始消息和最终状态才是判断依据。

### 第 3 步：给人工复核项分类

| 人工结论 | 含义 | 后续动作 |
|---|---|---|
| `KEEP_AS_IS` | 当前标注正确，review item 是误报、重复提醒或证据不足。 | 不改标注；可在外部审核记录中写明理由。 |
| `FIX_REQUIRED` | 当前 inventory/Event/final JSON 确实有错误。 | 找到最早产生错误的阶段，从该阶段重跑。 |
| `UNRESOLVED` | 原始证据本身不足，无法得到唯一 Gold 结论。 | 保留为已知不确定性，不强行新增、删除或路由。 |

当前 pipeline 不读取 `KEEP_AS_IS` 等人工决策字段。若需要保存 reviewer decision，应放在单独的人工审核记录中；不要向 `human_review.json` 任意增加字段并期待 pipeline 自动执行。

### 第 4 步：根据来源选择正确的修改入口

#### A. Discovery 漏掉、误建或错误拆分 Requirement

适用条目：

- `source: REQUIREMENT_DISCOVERY`；
- Requirement 从一开始就不存在、定义错误或边界错误；
- 后续所有 Events 都被错误 inventory 影响。

处理方式：

1. 修改 Requirement Discovery 相关 Prompt 规则，或确认现有 Prompt 下只是需要重新生成。
2. 从 Requirement Discovery 开始强制重跑：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --force-stage requirement_discovery --insecure
```

它会复用 Evidence Scan，但重新生成 Discovery、Event Extraction、Audit、Verification 和 final。

如果修改了主 Prompt 文件，Prompt 哈希会变化，旧 semantic checkpoints 不再兼容。此时应归档旧结果后执行干净重跑：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --no-resume --insecure
```

#### B. Requirement 正确，但 Event Extraction 漏标、错类型或错路由

适用条目：

- `source: EVENT_VERIFICATION` 的 missing candidate 经人工确认是真漏标；
- Audit 指出某 Event 应移动到另一个 Requirement；
- `events/<requirement_id>.json` 已经错，但 Discovery inventory 正确。

先确认候选 Event：

1. 主 `source_message` 是否独立支持该 Requirement；
2. event type 是否正确；
3. 是否已经存在于同一 Requirement；
4. 是否已经由另一个更窄的 Requirement 拥有；
5. 添加后是否只是为了达到 3-Event 门槛。

确认需要修正后，对目标 Requirement 从 Extraction 开始重跑：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --force-stage event_extraction --force-requirement REQ_TARGET --insecure
```

该命令复用 Evidence Scan 和 Requirement Discovery；目标 Requirement 会重新 Extraction，之后 Audit 和 Verification 会重新执行。

注意：只强制 `event_verification` 不能补上 Extraction 漏掉的 Event，因为 verifier 的 `missing_event_candidate` 不会自动应用。

#### C. Audit patch 是正确的，但存在 `application_error`

先判断失败原因：

| `application_error` 类型 | 常见原因 | 处理 |
|---|---|---|
| `Event locator not found` | 前面的 SPLIT/MERGE/DELETE 已改变 Event 列表，或 event type/occurrence 已变化。 | 在 `audited_state.json` 和当前 Events 中重新确认对象；修复 patch 顺序/代码后重跑 Audit。 |
| Requirement ID already exists | ADD/SPLIT/MERGE 复用了已有 ID。 | 应复用并更新 canonical Requirement，不能创建重复 ID。 |
| target is invalid | Requirement 已被前一个 patch 删除、合并或更名。 | 判断 patch 是否已过时；若仍需要，改为当前有效 target。 |
| replacement is invalid | replacement 缺字段、类型错误或不符合 patch contract。 | 修复 Prompt/schema 或代码校验。 |

修改 Audit Prompt 或 patch-application 代码后，从 Audit 开始：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --force-stage consistency_audit --insecure
```

它复用 Evidence Scan、Discovery 和已有 Extraction，重新执行 Audit 以及后续 Verification/final。

#### D. `source: CONSISTENCY_AUDIT` 边界未稳定

这条记录没有可直接执行的 `operation`。处理顺序是：

1. 只检查 `affected_requirement_ids`，不要把整个项目全部人工重标。
2. 对比 `requirement_discovery.json` 与 `audited_state.json`，确认新增/拆分/合并后的定义是否更原子。
3. 检查受影响 Requirement 的 Events 是否已经重新提取。
4. 检查是否仍有 overlap、同一 message 跨 broad/narrow Requirement 重复，或新 Requirement 少于 3 个有效 Events。
5. 如果结构已合理，将它视为“最后一轮发生变化”的信息提示，不需要为了消除 warning 强行修改。
6. 如果结构仍不稳定，可对该项目使用两轮 Audit 做完整重跑。

`--max-audit-rounds` 属于 checkpoint 配置。把已有项目从 1 改为 2 时不能安全混用旧 semantic checkpoints，应先归档，再执行干净重跑：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --max-audit-rounds 2 --no-resume --insecure
```

#### E. 只有 verifier verdict 需要重做

适用于 Event 已经存在于 `events/` / `audited_state.json`，但 verifier 错误 KEEP、EDIT 或 DELETE。

修改 verification addendum 后，可以只重跑一个 Requirement：

```powershell
python Code\stage1_batch_annotate.py --project-id <project_id> --prompt-file prompt\stage1_prompt_v2.md --force-stage event_verification --force-requirement REQ_TARGET --insecure
```

这会复用 Evidence Scan、Discovery、Extraction 和 Audit，只重新验证目标 Requirement 并重新组装 final。

### 第 5 步：重跑后的验收清单

修改和重跑完成后，至少检查：

1. `run_metadata.json.status == "DONE"`，且使用了预期 Prompt/version/hash。
2. 新的 `human_review.json` 中，原问题是否消失；若仍存在，`decision_note` 或 `application_error` 是否发生变化。
3. `audited_state.json` 中 Requirement ID 非空且唯一。
4. `verified_events.json` 中目标 Event 是否存在于正确 Requirement，event type 和 source message 是否正确。
5. `final/<project_id>_stage1_annotation.json` 与 `outputs/stage1_annotations/<project_id>_stage1_annotation.json` 是否一致。
6. Event 的 `source_message.text` 是否与 `normalized_project.json` 完全一致。
7. 修正后的 Requirement 是否因少于 3 个 Events 被写入 `discarded_requirements.json`。
8. 没有为了保留 Requirement 而制造、重复或错误路由 Event。

### 当前人工修改机制的限制

当前代码没有读取 `human_review_decisions.json` 或人工 override patch 的步骤。因此：

- 修改 `human_review.json` 本身不会改变结果；
- 直接修改 `final/` 会在下次组装时被覆盖，也无法保证统计文件和顶层输出同步；
- 真正可复现的修改必须发生在 Prompt、对应上游 checkpoint 的生成逻辑或 patch-application 代码中，然后重跑相应阶段；
- 如果后续需要大量人工 Gold 修正，建议新增一个经过 Schema 校验的 `human_review_overrides.json` 应用层，在 final assembly 前确定性应用人工批准的 ADD/EDIT/DELETE/MOVE 操作。

### 推荐复核优先级

1. 带 `application_error` 的 HIGH-confidence patch；
2. evidence/source-message 错位；
3. 最后一轮边界未稳定且 affected Requirement 仍有 overlap；
4. verifier 的真实 missing Event；
5. Discovery unresolved/LOW-confidence Requirement；
6. 重复提醒、误报或原始证据本身无法定案的条目。

Run local tests (no external API calls):

```powershell
python -m unittest discover -s Code/tests -v
```

# ReqMemBench Stage 2.2：LLM 选择目标时间与 Gold State

> 状态：新版 Pipeline 已实现。旧的 position / priority / random sampler 已从
> `Code/stage2/gold_state.py` 移除。离线测试和 `42204309 --prepare-only` 已验证；真实
> LLM API 调用仍需配置凭据后显式运行。

新版 Stage 2.2 先从已标注的 Client task 中选择有 Requirement Memory benchmark
价值的目标时间 \(t^*\)，再从 Requirement State Graph 确定性生成 Task 前后的 Gold
State。目标时间选择与 Gold State 回放的设计逻辑见
[`DESIGN_stage2_target_time_selection.md`](../../Constuction_guideline/DESIGN_stage2_target_time_selection.md)；
Python 接口、CLI、配置、恢复、故障处理、校验与测试说明统一维护在本文。

## 新版数据流

```text
outputs/stage1_runs/<project_id>/normalized_project.json
        +
outputs/stage1_annotations/<project_id>_stage1_annotation.json
        +
outputs/stage2/<project_id>/requirement_state_graph.json
        |
        v
规则生成 candidate_tasks.json
        |
        v
candidate_contexts.json
        |
        v
candidate_packets.jsonl
        |
        v  每个 Candidate 一次 LLM 评估
candidate_llm_evaluations.jsonl
        |
        v
recommended_candidates.json
        |
        +--> 默认模式：coverage + deduplication --> 人工 ACCEPT / REJECT / ADD_BACK
        |
        +--> --auto-accept-ai：0-10 分数线筛选，跳过人工复核
        |
        v
selected_candidates_auto.json
        |
        v
selected_target_times.json
        |
        v  确定性 State Graph replay
outputs/stage2/<project_id>/gold_states.json
outputs/stage2/<project_id>/target_time_selection/gold_state_validation.json
```

## 输出目录布局

仅看 Stage 2.2 的产物时，项目根目录放置 Requirement Graph 与最终 Gold State；所有目标
时间选择过程文件放在独立子目录中。后续 Stage 2.3 还会在同一项目根目录加入
`RQ1/`–`RQ4/` 和 `rq_instance_manifest.json`：

```text
outputs/stage2/<project_id>/
├── requirement_state_graph.json
├── gold_states.json
└── target_time_selection/
    ├── candidate_tasks.json
    ├── candidate_contexts.json
    ├── candidate_packets.jsonl
    ├── candidate_llm_evaluations.jsonl
    ├── threshold_selection_statistics.json
    ├── threshold_selection_statistics.md
    ├── recommended_candidates.json
    ├── selected_candidates_auto.json
    ├── target_time_human_review.template.json
    ├── target_time_human_review.json       # 仅人工复核模式
    ├── selected_target_times.json
    ├── gold_state_validation.json
    └── target_selection_run.json
```

Stage 1 annotation 提供 Requirement 和完整 Event payload；`normalized_project.json`
提供脱敏后的完整消息目录及稳定对话顺序；State Graph 提供 Candidate 前的 Requirement
State 和最终 Gold replay。三份输入的 project / Event provenance 必须一致。

Stage 2.2 不直接重读 `Datasets/` 中的原始聊天，不让 LLM 重新标注 Requirement、修改
State Graph 或生成 Gold State。

## Candidate 规则

一个 Candidate 对应一条 Client message。同一 `source_message_id` 触发的所有
Requirement Events 必须合并成一个 Candidate。

主要候选包括：

- `MODIFY`；
- `REMOVE`；
- `DEFER` / `RESUME`；
- `AMBIGUOUS`；
- 通过非空 `resolves_ambiguity_event_ids` 表达的 ambiguity resolution；
- 与其他候选 Event 同消息、影响多个 Requirements，或发生在已有项目状态之后的
  `INTRODUCE`。

仅含 `IMPLEMENTATION_CLAIM`、`RUNTIME_FAILURE`、`RUNTIME_VERIFICATION` 的消息默认
不进入候选。

当前 Stage 1 schema 没有独立 `CLARIFY` / `RESOLVE` Event type。新版 selection
只派生 clarification / resolution coverage tag，不改写原始 Event。

## 历史长度定义

一个 turn 是 `normalized_project.messages` 中的一条有效消息。消息顺序使用规范化数组
顺序，并用 `original_index` 校验，不按 message ID 数值排序。

```text
conversation_turn_index = Candidate 的一基顺序位置
history_turn_count       = Candidate 前的有效消息数量
history_turn_count       = conversation_turn_index - 1
```

两个字段从 Candidate 一直保留到 `selected_target_times.json` 和 `gold_states.json`。
它们只用于后续历史长度分层和数据分析，不参与 LLM 评分、coverage gain、去重优先级或
Candidate 排序。

## Candidate Packet

LLM 每次只接收一个 Candidate Packet：

```text
Current Candidate Task
+ Triggered Events
+ affected Requirements 的 Pre-task States
+ affected Requirements 的历史 Event sequence
+ 这些历史 Event 对应的原始 evidence messages
+ history metadata
```

Packet 不包含完整 conversation 或完整 State Graph。Pre-task State 和历史 evidence
必须严格早于 Candidate；当前 Task 单独提供，未来信息不得泄漏。

## LLM 的唯一职责

LLM 只判断 Candidate 是否具有 benchmark value，维度包括：

- historical dependency；
- requirement evolution；
- reconstruction risk；
- ambiguity / decision value；
- multi-requirement value；
- 忽略历史是否会导致不同且错误的结果。

模型输出必须是通过严格 schema 校验的 JSON，包括 `valid_task`、五个
`LOW/MEDIUM/HIGH` 维度、`history_sensitive`、`recommended`、
`primary_rq_targets` 和 `reason`。`recommended: true` 必须同时满足
`valid_task: true` 与 `history_sensitive: true`。

程序还会从五个维度确定性计算 `ai_selection_score`：`LOW=0`、`MEDIUM=1`、
`HIGH=2`，总分范围为 0–10。这个分数不是模型自由填写的额外字段，因此同一份合法
evaluation 总能得到相同分数。

`primary_rq_targets` 以 `Constuction_guideline/ReqMemBench_RP_V2.md` 为权威，只允许：

- `RQ1` Relevant Requirement Selection：选择与当前 Task 有关的历史 Requirement 和
  evidence，并排除无关历史；
- `RQ2` Current Requirement State Reconstruction：恢复当前有效的 scope、persistence、
  lifecycle、update、override、removal、temporal validity 和 conflict resolution；
- `RQ3` Memory-or-Clarify Decision：判断历史证据是否足以执行，还是必须向 Client 澄清；
- `RQ4` Requirement-to-Code Execution：把恢复后的 Requirement State 忠实落实为可验证代码。

`allowed_rq_targets` 固定为 `RQ1`–`RQ4`。模型返回 allowlist 之外的值，或在
`recommended=true` 时返回空 RQ 列表，都会被严格拒绝。

RQ 定义属于 prompt semantics。修改 RQ prompt 后需要重新评估：

```powershell
& 'D:\Python_env\Miniconda\python.exe' Code\stage2_generate_gold_state.py `
  --project-id 42204309 `
  --force-evaluation `
  --insecure
```

prompt fingerprint 改变后，普通 evaluation 命令也会自动重评失效项；显式
`--force-evaluation` 可以强制重新生成。`--threshold-report-only` 会拒绝不匹配的
fingerprint，不会混用不同 RQ prompt 生成的统计表。

无效响应按配置重试。重试后仍失败会停止该项目的 selection，不回退到旧随机抽样，
也不会把 API 失败误记为不推荐。

## Coverage、去重与人工复核

Automatic selection 先保留有效且推荐的 Candidate，再覆盖实际存在的 Event / ambiguity
pattern、single / multi-Requirement task 和 RQ opportunities。

去重只自动合并 affected Requirements、Event / resolution tags、Pre-task lifecycle / open
ambiguity pattern 完全相同的 Candidate。若设置 target 上限，使用可复算的 greedy
set-cover；所有 tie-break 和 coverage gain 写入产物。历史长度和时间位置不参与选择。

人工 Reviewer 使用 Candidate Packet 和 LLM reason 给出：

```text
ACCEPT
REJECT
ADD_BACK
```

人工文件名为 `target_time_human_review.json`，避免与 Stage 1 已有的
`human_review.json` 混淆。`ADD_BACK` 只能引用已经构建 packet 且完成有效 LLM evaluation
的 Candidate。最终只有 `ACCEPT` 和合法 `ADD_BACK` 进入
`selected_target_times.json`。

显式使用 `--auto-accept-ai` 时，流程改为信任 AI：Candidate 必须同时满足
`valid_task=true`、`history_sensitive=true`、`recommended=true`，且总分不低于
`--score-threshold`。所有满足条件的时间点都会进入最终结果，不执行 coverage 去重、
greedy set-cover 或 `max_selected_targets` 上限，也不生成或读取 ACCEPT 文件。

## Gold State 生成

Gold builder 不再自行发现或抽样 Task，只消费最终 selected targets。

对每个 target：

- `Pre-task Gold` 是该消息发生前的完整项目 Requirement snapshot；
- `Post-task Gold` 是该消息中全部 Events 应用后的完整 snapshot；
- 当前消息的全部 Graph Events 必须属于同一个 Task；
- `affected_requirement_ids` 只来自当前 Task Events；
- `preserved_requirement_ids` 是 Pre-task Requirements 减去 affected Requirements；
- 当前 Task 新 INTRODUCE 的 Requirement 不在 Pre、在 Post；
- REMOVE 后的 Requirement 仍保留在 Post，并显示 `REMOVED`；
- 同一 Requirement 在同一消息有多个 Event 时，Post 使用最后一个 Event 的 State。

Gold 继续通过 State chain、Event grouping、完整 Pre/Post snapshot、affected / preserved、
INTRODUCE / REMOVE、same-message final State 和 future leakage 校验。

## Python 接口与文件责任

`gold_state.py` 以纯数据变换和校验为主，网络调用通过注入的 client 完成。文件责任如下：

| 文件 | 责任 |
|---|---|
| `Code/stage2/gold_state.py` | index、Candidate / Context / Packet 变换、LLM response 校验、coverage / dedup、review finalize、Gold replay 与校验；不读取环境变量或创建 HTTP client |
| `Code/stage2_generate_gold_state.py` | CLI、默认路径、JSON / JSONL 原子读写、API client 生命周期、resume 编排和阶段状态报告 |
| `prompt/t_selection_prompt.md` | LLM 角色、评估维度、历史长度禁用规则和唯一允许的 JSON response schema |
| `Code/config/stage2_gold_state.json` | Candidate、RQ allowlist、LLM runtime 与 selection cap 配置 |
| `Code/tests/test_stage2_gold_state.py` | 纯函数、fake client、选择与 Gold regression 测试 |

公开的核心 Python 接口为：

```python
def validate_selection_inputs(annotation, normalized_project, state_graph) -> None: ...
def generate_candidate_tasks(annotation, normalized_project, state_graph, config) -> dict: ...
def build_candidate_contexts(candidates, annotation, normalized_project, state_graph) -> dict: ...
def build_candidate_packets(candidates, contexts) -> list[dict]: ...
def validate_llm_evaluation(evaluation, packet, config) -> None: ...
async def evaluate_candidate_packets(packets, *, api, prompt, config) -> list[dict]: ...
def select_recommended_candidates(...) -> dict: ...
def calculate_ai_selection_score(...) -> int: ...
def build_threshold_selection_statistics(...) -> dict: ...
def render_threshold_selection_markdown(...) -> str: ...
def select_ai_candidates_by_score(...) -> dict: ...
def apply_coverage_and_deduplication(...) -> dict: ...
def finalize_ai_selected_targets(...) -> dict: ...
def finalize_selected_targets(...) -> dict: ...
def build_gold_states(selected_targets, normalized_project, state_graph) -> dict: ...
```

内部的 `_MessageIndex`、`_AnnotationIndex` 和 `_GraphIndex` 分别负责消息、标注及图索引；
`TargetSelectionConfig` 集中管理选择配置；`LLMClientProtocol` 允许测试注入 fake client，
避免凭据、网络或真实输出目录成为单元测试依赖。

## API 与运行参数

当前实现复用现有 `stage1.api_client.Stage1ApiClient` 的认证、并发、重试、JSON 解析、
调用日志和失败响应机制，通过 Stage 2 adapter 使用
`TARGET_TIME_EVALUATION` run mode；不复制 HTTP/JWT 实现。

凭据仍只从环境变量读取：

```powershell
$env:UPWORK_API_KEY="..."
$env:UPWORK_BUDGET_ID="..."
```

`Code/stage2_generate_gold_state.py` 是统一入口，负责 annotation、messages、prompt、
LLM resume、AI 自动接受、human review 和 finalize 编排。`Code/config/stage2_gold_state.json` 已删除
旧的 `event_priority`、`position_ratio` 和 `random_seed`，改为候选规则、RQ allowlist、
LLM 参数与 `max_selected_targets`。

当前配置 schema 如下；旧字段会触发迁移错误，不会被静默忽略：

```json
{
  "candidate_event_types": ["MODIFY", "REMOVE", "DEFER", "RESUME", "AMBIGUOUS"],
  "include_introduce_candidates": true,
  "include_execution_only_tasks": false,
  "allowed_rq_targets": ["RQ1", "RQ2", "RQ3", "RQ4"],
  "max_selected_targets": null,
  "model": "gpt-5.6-sol",
  "reasoning_effort": "high",
  "max_concurrent_requests": 4,
  "retries": 3,
  "timeout_seconds": 900
}
```

### 完整命令速查

以下命令均在仓库根目录 `D:\Python_workplace\Upwork\Upwork_Benchmark` 下执行。PowerShell
可以先设置两个本地变量：

```powershell
$py = 'D:\Python_env\Miniconda\python.exe'
$projectId = '42204309'
```

| 功能 | 是否调用 LLM | 是否生成最终 Gold |
|---|---|---|
| 只准备 Candidate Packets | 否 | 否 |
| 只完成 evaluation 并生成 threshold 表 | 是；已有相同 fingerprint 时复用 | 否 |
| 用已有 evaluation 重建 threshold 表 | 否 | 否 |
| 按 threshold 自动接受 AI 选择 | 首次需要；以后可复用 | 是 |
| 人工 ACCEPT / REJECT 后 finalize | evaluation 缺失或失效时才调用 | 是 |
| 强制重新 evaluation | 是 | 否，除非同时使用自动接受模式 |

只准备 Candidate，不调用 LLM：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --prepare-only
```

只进行 evaluation，不输入 threshold、不生成最终 Gold；同时自动生成 threshold 5–10
统计表：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId
```

已有 evaluation 后，仅本地重建并打印 threshold 表，不调用 LLM：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --threshold-report-only
```

选定 threshold 后，跳过人工审核并直接生成最终 Gold：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --auto-accept-ai `
  --score-threshold 7
```

人工审核模式先复制模板：

```powershell
Copy-Item `
  "outputs\stage2\$projectId\target_time_selection\target_time_human_review.template.json" `
  "outputs\stage2\$projectId\target_time_selection\target_time_human_review.json"
```

填写全部 `ACCEPT` / `REJECT` / `ADD_BACK` 和 reason 后 finalize：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --finalize `
  --human-review-file "outputs\stage2\$projectId\target_time_selection\target_time_human_review.json"
```

强制重新调用 LLM 评估所有 Candidate：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --force-evaluation
```

`--force-evaluation` 保留旧 JSONL，成功后再压缩为最新结果；`--no-resume` 会先清空当前
evaluation JSONL，再从头评估。通常优先使用 `--force-evaluation`。例如：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --no-resume
```

常用附加参数可以组合到需要调用 LLM 的命令中：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --model gpt-5.6-sol `
  --reasoning-effort high `
  --max-concurrent-requests 4 `
  --retries 3 `
  --timeout 900
```

其他可选参数包括 `--output-dir`、`--annotation`、`--messages`、`--state-graph`、
`--config`、`--prompt`、`--max-selected-targets` 和
`--include-execution-only-tasks`。`--insecure` 会关闭 TLS 证书校验，只应在明确需要的
受控环境中使用。

### 1. 只准备 Candidate Packets

此模式不需要 API 凭据：

```powershell
python Code/stage2_generate_gold_state.py `
  --project-id 42204309 `
  --prepare-only
```

它会写出 `candidate_tasks.json`、`candidate_contexts.json`、
`candidate_packets.jsonl` 和 `target_selection_run.json`。

### 2. 调用 LLM 并生成自动选择

设置凭据后运行：

```powershell
$env:UPWORK_API_KEY="..."
$env:UPWORK_BUDGET_ID="..."

python Code/stage2_generate_gold_state.py `
  --project-id 42204309
```

每个 Candidate 使用 `prompt/t_selection_prompt.md` 单独评估。有效 evaluation 根据
packet、prompt、model 和 reasoning effort fingerprint 断点复用；`--no-resume` 或
`--force-evaluation` 可禁用复用。完成后写出：

```text
candidate_llm_evaluations.jsonl
threshold_selection_statistics.json
threshold_selection_statistics.md
recommended_candidates.json
selected_candidates_auto.json
target_time_human_review.template.json
```

此时不会写正式 targets 或 Gold。

### 3. 人工复核并 Finalize

复制 review template，逐项填写 `ACCEPT` / `REJECT` 和 reason；需要恢复其他已评估
Candidate 时添加 `ADD_BACK`：

```powershell
Copy-Item `
  outputs/stage2/42204309/target_time_selection/target_time_human_review.template.json `
  outputs/stage2/42204309/target_time_selection/target_time_human_review.json
```

编辑完成后运行：

```powershell
python Code/stage2_generate_gold_state.py `
  --project-id 42204309 `
  --finalize `
  --human-review-file outputs/stage2/42204309/target_time_selection/target_time_human_review.json
```

Pipeline 校验 review、生成 `selected_target_times.json`，再确定性写出
`gold_states.json` 和 `gold_state_validation.json`。如果输入、LLM response、人工决定、
State snapshot 或 provenance 任一不合法，finalize 会失败关闭。
当所有 evaluation fingerprint 均可从已有 JSONL 复用时，finalize 不需要重新访问网络；
若有任何 Candidate 需要重新评估，则仍必须提供 API 凭据。

### 4. 直接接受 AI 选择并生成 Gold

如果不需要人工 `ACCEPT / REJECT`，使用以下单条命令：

```powershell
python Code/stage2_generate_gold_state.py `
  --project-id 42204309 `
  --auto-accept-ai `
  --score-threshold 7
```

分数线必须是 0–10 的整数，默认值是 7。`0` 表示接受所有满足三个 AI 布尔条件的
推荐项；`10` 只接受五个维度全部为 `HIGH` 的推荐项。该模式在同一次运行中直接写出：

```text
outputs/stage2/42204309/target_time_selection/selected_candidates_auto.json
outputs/stage2/42204309/target_time_selection/selected_target_times.json
outputs/stage2/42204309/gold_states.json
outputs/stage2/42204309/target_time_selection/gold_state_validation.json
outputs/stage2/42204309/target_time_selection/target_selection_run.json
```

`selected_target_times.json` 会为每项记录 `selection_source: LLM_AUTO_ACCEPT`、
`ai_selection_score`、`ai_score_threshold` 和 `human_review: SKIPPED`。自动模式保留已有
evaluation 的 fingerprint resume 行为；如需强制重新调用 API，可同时使用
`--force-evaluation`。

### 5. 查看 threshold 5–10 的选择数量

每次完成 Candidate LLM evaluation 后，Pipeline 会自动生成：

```text
outputs/stage2/<project_id>/target_time_selection/threshold_selection_statistics.json
outputs/stage2/<project_id>/target_time_selection/threshold_selection_statistics.md
```

Markdown 表格结构如下：

| Score threshold (`>=`) | 0–50 turns | 50–100 turns | 100+ turns | Total |
|---:|---:|---:|---:|---:|
| 5 | ... | ... | ... | ... |
| 6 | ... | ... | ... | ... |
| 7 | ... | ... | ... | ... |
| 8 | ... | ... | ... | ... |
| 9 | ... | ... | ... | ... |
| 10 | ... | ... | ... | ... |

三个 history bucket 使用无重叠的半开区间：`[0,50)`、`[50,100)`、`[100,+∞)`。
每一行统计所有同时满足 `valid_task=true`、`history_sensitive=true`、
`recommended=true` 且分数不低于该 threshold 的时间点，因此可直接用于选择
`--score-threshold`。

如果 evaluation 已经存在，只想重新生成并在终端查看表格，执行：

```powershell
python Code/stage2_generate_gold_state.py `
  --project-id 42204309 `
  --threshold-report-only
```

该命令只读取 `candidate_llm_evaluations.jsonl` 并执行本地计数，不读取 API 凭据、
不调用 LLM，也不改写 Gold State。通常在很短时间内完成。

## Resume、fingerprint 与失败处理

每条 LLM evaluation 保存 `candidate_id`、`packet_sha256`、`prompt_sha256`、`model`、
`reasoning_effort`、`response`、`usage` 和 `request_id`。默认只复用 fingerprint、model
参数均一致且已经通过 schema 校验的结果；Packet、prompt、model 或 reasoning effort
任一变化都会触发重新评估。

失败与恢复遵循以下规则：

- 单个请求按 API client 的 retry policy 重试；
- 中断后保留已验证的 JSONL 行，下一次运行可 resume；
- 任一 Candidate 最终没有有效 evaluation 时，停止 automatic selection；
- 人工复核不完整时可以生成 review packet，但不能生成 final targets 或 Gold；
- 输入 provenance、future leakage 或 Gold validation 失败时，不写成功状态的最终文件；
- `--force-evaluation` 保留旧 JSONL，成功后压缩为最新结果；`--no-resume` 从头评估。

常见报错应这样处理：

| 报错类型 | 处理方式 |
|---|---|
| 缺少 `UPWORK_API_KEY` / `UPWORK_BUDGET_ID` | 只做离线准备时使用 `--prepare-only`；需要评估时设置凭据 |
| evaluation fingerprint 不匹配 | 重新运行普通评估，或用 `--force-evaluation` 明确全量重评 |
| human review 不完整/存在未知 Candidate | 补齐模板中的全部决定，并只引用已生成且已评估的 Candidate |
| provenance、State 或 future leakage 校验失败 | 回到 Stage 1 annotation / State Graph 修复输入；不要绕过校验生成 Gold |
| TLS 证书问题 | 优先修复证书环境；`--insecure` 仅用于明确受控的临时环境 |

## 校验清单

输入与 Candidate：

- annotation、normalized project、State Graph 的 project ID 一致；
- message ID 和 `original_index` 唯一，顺序合法；
- Stage 1 Event 引用真实消息，且与 Graph provenance 一致；
- Candidate 是 Client message，包含同消息的完整 Event 集合；
- Event / Requirement ID 不重复；
- `history_turn_count == conversation_turn_index - 1`。

Context 与 Packet：

- Pre-state supporting Events 和 Requirement history 都严格早于 target；
- historical evidence 不晚于 target且不重复；
- 当前 task 只在 `candidate_task` 出现一次；
- Packet 大小和 reason 长度符合配置限制。

LLM 与选择：

- 每个 Candidate 恰好有一条有效 evaluation；
- 枚举、布尔、RQ1–RQ4 allowlist 和回显 ID 严格合法；
- 推荐条件、AI 总分、threshold 集合、coverage、dedup 和 tie-break 均可复算；
- 排序不读取 `history_turn_count` 或 conversation position；
- 人工决定完整、唯一且只引用已知 Candidate。

Gold：

- State chain、完整快照、Event 分组、affected / preserved、INTRODUCE / REMOVE、
  same-message final State 和 future leakage 校验通过；
- 每个 Task Gold 引用一个最终 selected target；
- message / Event / Requirement / history metadata 与选择产物一致；
- 不为被拒绝、未复核且未通过显式 AI 自动接受的 Candidate 生成 Gold。

## 测试要求

测试不得依赖真实 LLM API，单元和离线集成测试使用 fake client。覆盖范围包括：

1. Candidate generation：单/多 Requirement、同消息多 Event、纯 INTRODUCE、纯 execution、
   非 Client message、opaque message ID；
2. History metadata：首条消息、消息空洞、非数字 ID、`original_index` 不连续但顺序合法；
3. Context boundary：INTRODUCE 无 Pre-state、同消息多 Event、resolution link、未来泄漏；
4. LLM validator：缺字段、额外字段、错误 enum、ID 不匹配、推荐逻辑矛盾；
5. Resume：fingerprint 命中，以及 prompt / packet / model 改变后的失效；
6. Coverage / dedup：相同 fingerprint、ambiguity pattern、上限不足和稳定 tie-break；
7. Human review 与 AI auto-accept：决定合法性、0–10 分数、阈值边界和跳过 review；
8. Threshold report：5–10 各行、49/50/99/100 turn 边界、总数和 Markdown 渲染；
9. Gold regression 与 CLI integration：State replay、provenance、fake API 全流程产物。

测试套件本身不要求凭据或网络。当前 14 个 Stage 2 Gold/selection 测试与全仓库 93 个
测试均已通过；`42204309 --prepare-only` 生成了 72 个 Candidate Packets。真实 API
结果不在单元测试中伪造为生产输出。

运行本模块测试：

```powershell
python -m unittest Code.tests.test_stage2_gold_state -v
```

## 实施顺序与完成标准

维护或重构本阶段时，按依赖关系依次处理：message / annotation / graph index，Candidate /
Context / Packet，prompt 与严格 response validator，API client 与 resume，coverage / dedup /
human review，selected targets，最后是确定性 Gold replay 与 CLI/测试迁移。

完成标准：

- 旧 position / priority / random sampler 不参与选择；
- 每个最终 target 可追踪到 Candidate packet、合法 evaluation，以及人工复核或显式 AI 自动接受记录；
- `history_turn_count` 无损保留到 Gold，但不作为 target value 信号；
- Gold State 仅由已验证 State Graph 确定性回放；
- 单元测试、离线端到端测试和 artifact validation 全部通过；
- 真实 LLM selection 仍是需要显式凭据的生产步骤。

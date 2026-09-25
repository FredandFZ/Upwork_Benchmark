# ReqMemBench RQ1--RQ3：Codex 全流程自动运行 Prompt

你是本次 ReqMemBench RQ1--RQ3 实验的执行 Agent。你没有任何可依赖的历史对话；本文件是完整执行协议。用户会另外告诉你且只需要告诉你三个参数：

- `MODEL`：Codex CLI 接受的模型 ID；
- `EFFORT`：模型思考强度；
- `TARGET_COUNT`：要测试的唯一 target 数量。

从用户最新消息中提取这三个参数。只有参数缺失或存在实质歧义时才提一个简短问题；参数齐全后不要再次确认，立即执行。不要擅自替换模型或思考强度。

## 1. 目标与数量定义

完成一次新的 Codex RQ1--RQ3 实验：正式输入物化、样本冻结、Agent 运行、Judge、确定性评分和汇总。

`TARGET_COUNT=N` 永远表示 N 个唯一 target，不是 package 数或 score record 数。每个 target 分别运行 C1 和 C2，因此 `expected_agent_runs = 2 × N`，`repetitions = 1`。一次 target-condition run 只调用一个 Codex 进程并输出统一 response，再投影到适用的 RQ1--RQ3；严禁按 RQ 分别调用 Agent。

## 2. 不可改变的边界

- 不修改 RQ1--RQ3 定义、Gold、response schema、Judge prompt/标签、scorer、聚合公式或正式 package。
- 不修改 `prompt/rq_agent_run_prompt.md`、`prompt/rq_agent_instructions.md`、`schema/rq_agent_response.schema.json`。
- benchmark Agent 不得看到 repository、Code Environment、private manifest、Gold、其他 run、Judge 输出或本 prompt。
- 不手工修补 Agent response，不用第二个模型改写无效 response，不依据分数选择性重跑。
- 每个 target-condition 使用新进程、新临时 workspace、无持久 session；不得 resume。
- 不输出、记录或写入 credential 值，只检查所需环境变量是否存在。
- 只在本实验专属输出目录创建配置和结果；不覆盖既有实验，不删除或重置用户文件。
- 所有仓库路径均相对于仓库根目录。先确认当前目录包含 `Code/`、`prompt/`、`schema/`、`outputs_new/stage2/`。

## 3. 必须先读

依次读取：

1. `Code/insturctions/README_rq_agent_pipeline.md`
2. `Code/config/rq123_codex_experiment.example.json`
3. `Code/config/rq123_codex_5target_pilot.json`
4. `Code/run_rq123_agents.py`
5. `Code/run_rq123_judges.py`
6. `Code/aggregate_rq123_results.py`

RQ 定义和评分以仓库实现为准；provider、用户参数、样本数和隔离要求以本 prompt 为准。不要清理工作树中与本任务无关的修改。

## 4. 环境预检

自动识别可用的 Python 命令（如 `python`、`python3` 或 Windows Python launcher），后续始终使用同一解释器。执行：

```text
<python> --version
codex --version
codex login status
```

Windows 若实际 executable 是 `codex.cmd`，配置使用 `codex.cmd`；其他系统使用 `codex`。`codex login status` 非零时停止，不启动 benchmark run，并提示用户先登录。

记录 `codex --version` 完整输出为 `agent.runtime_version`。配置的 `environment_allowlist` 至少包含：

```json
["CODEX_HOME", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"]
```

保留模板中的 `exec`、`--ephemeral`、`--ignore-user-config`、`--ignore-rules`、`--sandbox read-only`、`--output-last-message agent_response.json`、`--json` 和 stdin `-`。不得增加 `exec resume` 或 `--last`。不得传 `--output-schema`；动态 attribute keys 由 Runner 在冻结前按公共 schema 本地校验。

## 5. 实验身份与配置

将 `MODEL` 原样写入 `agent.model` 和 `agent.model_version`，将 `EFFORT` 原样写入 `agent.reasoning_effort`，`repetitions` 固定为 1。将模型名清理为只含字母、数字、点、下划线和连字符的 slug：

```text
experiment_id = rq123-codex-<model-slug>-<effort>-<N>targets-r1
experiment_root = outputs_new/rq_experiments/<experiment_id>
config = outputs_new/rq_experiments/<experiment_id>/experiment.json
package_root = outputs_new/rq_experiments/<experiment_id>/rq_agent_inputs
run_root = outputs_new/rq_experiments/<experiment_id>/rq_runs
log_root = outputs_new/rq_experiments/<experiment_id>/rq_judge_logs
summary = outputs_new/rq_experiments/<experiment_id>/rq_results/summary.json
selection = outputs_new/rq_experiments/<experiment_id>/selected_cases.json
```

从 `Code/config/rq123_codex_experiment.example.json` 创建 `config`，填满所有 placeholder。Agent 使用本次参数与实际 runtime version。Judge 固定为：

```json
{
  "provider": "upwork_stage1",
  "api_interface_version": "stage1-chat-completions-v1",
  "model": "gpt-5.6-sol",
  "model_version": "gpt-5.6-sol",
  "reasoning_effort": "high",
  "max_concurrent_requests": 4,
  "retries": 3,
  "timeout_seconds": 900
}
```

配置不得含 credential 或 placeholder。若 `experiment_root` 已存在且 config 完全一致，则恢复运行；若不一致，创建带 UTC 时间后缀的新 ID。绝不覆盖或混合不兼容实验。

## 6. Package 与确定性样本

先验证再物化：

```text
<python> Code/materialize_rq123_release.py --stage2-root outputs_new/stage2 --validate-only
<python> Code/materialize_rq123_release.py --stage2-root outputs_new/stage2 --output-root <package_root>
```

从 `package_root` 递归发现并按路径升序排列 `package_manifest.json`；按 `(project_id, target_id)` 分组，只保留同时且恰好具有 C1、C2 的完整 target，按首次出现顺序选择前 N 个。N 必须为正且不超过可用数量。

把 schema/version、选择规则、N、预计 run 数，以及每个 target 的 `project_id`、`target_id`、C1/C2 `package_id` 和 package manifest 相对路径写入 `selection`。不得写绝对路径。

Codex/Claude 对比实验必须使用同一 target 列表。若用户提供另一 provider 的 `selected_cases.json`，优先复用并逐项验证；否则使用确定性前 N 规则。

## 7. Dry-run 门禁与正式运行

根据 `selection` 为每个 target 生成一个 `--case <project_id>:<target_id>`，先运行：

```text
<python> Code/run_rq123_agents.py --config <config> --package-root <package_root> --run-root <run_root> [全部 --case 参数] --dry-run
```

必须看到恰好 `2 × N` 个 run。数量不符、缺 C1/C2、存在 placeholder 或模型/effort 不一致时停止，不调用模型。

门禁通过后，用完全相同命令移除 `--dry-run` 正式运行。不得并发启动多个外层 Runner。瞬时失败时保留 frozen run，以同一 config 和命令恢复；Runner 会跳过 `SKIPPED_FROZEN`。不得改变模型、effort、prompt、tool policy 或样本来重试。

Agent 阶段只有同时满足以下条件才通过：experiment agent ledger 存在；恰好登记 `2 × N` 个唯一 run；`failures` 为空；每个 run 都有冻结 response、SHA-256、run manifest 和日志；manifest 的 provider/model/effort/repetition 与 config 一致；C1/C2 未共享 session/workspace。

## 8. Judge、评分与汇总

Agent provider 不充当 Judge。只检查 `UPWORK_API_KEY`、`UPWORK_BUDGET_ID` 是否存在，不显示值。两者存在时运行：

```text
<python> Code/run_rq123_judges.py --config <config> --run-root <run_root> --log-dir <log_root>
<python> Code/aggregate_rq123_results.py --run-root <run_root> --experiment-id <experiment_id> --output <summary>
```

不要默认添加 `--insecure`；仅在用户明确要求或确认本地证书链问题并获得同意时使用。Judge 通过条件是 ledger 的 `completed_run_count = 2 × N`、`failures` 为空且 summary 已生成。

若 Judge credential 缺失，Agent 阶段可完成，但整体状态必须为 `AGENT_COMPLETE_WAITING_FOR_JUDGE`；给出使用相对路径的续跑命令，不得重跑 Agent。

## 9. 最终报告

报告实际 provider/runtime/MODEL/EFFORT/N/run 数；选择清单或 `selection` 路径；Agent 完成/跳过/失败数；Judge 完成/失败数和 `judge_config_id`；RQ1--RQ3 总体与 C1/C2 主要指标；config、两个 ledger、summary 的相对路径；最终状态 `COMPLETE`、`AGENT_COMPLETE_WAITING_FOR_JUDGE` 或 `FAILED`。

不得只说“命令已运行”。所有结论必须来自 ledger、冻结文件和 summary 的实际检查。

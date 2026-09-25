# RQ1--RQ3 Claude Code 运行手册

本方案只替换 Phase A 的 Agent provider：把 Codex CLI 换成 Claude Code CLI。公开输入、
RQ1--RQ3 response schema、Gold、LLM Judge 请求、确定性 scorer 和汇总协议均保持不变。
Claude Code 不按 RQ 分别运行；每个 `target × condition × repetition` 启动一个全新进程，
一次输出统一 response，再投影到该 package 适用的 RQ1--RQ3。

仓库中的 Claude 配置和脚本只完成了设计与本地单元测试。本机没有执行 Claude；以下命令应在
目标设备上运行。

## 1. 运行边界

Claude Code 命令固定使用：

- `-p`：非交互运行；
- `--restricted`：使用面向评测/共享机器的受限模式，不加载普通用户或项目设置；
- `--no-session-persistence`：不在磁盘保留或恢复 session；
- `--disable-slash-commands`：不加载 slash command；
- `--permission-mode dontAsk --permission-prompts none`：无人值守运行时不弹交互式授权；
- `--tools "" --disallowedTools "mcp__*" --no-chrome`：禁用内置工具、MCP 与浏览器；
- `--json-schema ... --output-format json`：让 Claude Code 生成结构化结果，由 Runner 从
  `structured_output` 中提取统一 RQ response；
- `--model` 和 `--effort`：显式固定模型和思考强度。

不得添加 `--continue`、`--resume`、`-c` 或 `-r`。每个 C1/C2 case 的隔离同时由 Claude 的
无持久 session 参数和 Runner 的新进程、新临时 workspace、`finally` 清理保证。

本方案最低要求 Claude Code `2.1.259`。模板默认使用固定 model ID
`claude-sonnet-5` 和 `high` effort。若要换模型，应复制成新的 experiment config，并修改
`experiment_id`、`model` 和 `model_version`，不能覆盖已有实验身份。

## 2. 目标设备准备

1. 把完整仓库复制或 clone 到目标设备。至少需要 `Code/`、`prompt/`、`schema/` 和
   `outputs_new/stage2/`。
2. 安装 Claude Code `>= 2.1.259`，并执行 `claude auth login`。用
   `claude auth status` 确认当前设备已经登录。
3. 使用本地订阅账户时不要增加 `--bare`。Claude Code 文档说明 bare 模式不使用订阅登录或
   系统 keychain，适用于显式 API key 的另一种实验配置，不能与本实验身份混用。
4. Windows 若 `claude` 无法被 Python 子进程解析，但 `claude.cmd` 可用，把配置中 command
   数组的第一个元素改为 `claude.cmd`。macOS、Linux 和 WSL 通常保持 `claude`。

不要直接复用另一台设备生成的 `outputs_new/rq_agent_inputs`：旧 package manifest 中保存了
源实例绝对路径。应在目标设备重新物化 package。Agent run 冻结后会把已校验的源实例嵌入
run 目录，因此 frozen run 可以再复制到另一台评分设备。

## 3. 在目标设备物化同一组五个 target

建议使用独立目录，避免与 Codex 实验混合：

```powershell
python Code/materialize_rq_agent_inputs.py --project-id 42204309 --target-id 42204309_T001 --stage2-root outputs_new/stage2 --output-root outputs_claude/rq_agent_inputs --mode formal
python Code/materialize_rq_agent_inputs.py --project-id 43214420 --target-id 43214420_T001 --stage2-root outputs_new/stage2 --output-root outputs_claude/rq_agent_inputs --mode formal
python Code/materialize_rq_agent_inputs.py --project-id 43711852 --target-id 43711852_T009 --stage2-root outputs_new/stage2 --output-root outputs_claude/rq_agent_inputs --mode formal
python Code/materialize_rq_agent_inputs.py --project-id 43948285 --target-id 43948285_T003 --stage2-root outputs_new/stage2 --output-root outputs_claude/rq_agent_inputs --mode formal
python Code/materialize_rq_agent_inputs.py --project-id 44132019 --target-id 44132019_T001 --stage2-root outputs_new/stage2 --output-root outputs_claude/rq_agent_inputs --mode formal
```

每条命令默认同时生成 C1 和 C2，因此一共应有 10 个 package。这里不读取 Code Environment，
也不涉及 RQ4。

## 4. 固定实验配置并执行无模型 preflight

复制下面的 pilot 配置，不要原地修改模板：

```powershell
Copy-Item Code/config/rq123_claude_sonnet5_high_5target_pilot.json Code/config/rq123_claude_sonnet5_high_5target_pilot.local.json
claude --version
```

把 local 配置中的
`replace-with-exact-claude-code-version-at-least-2.1.259` 替换成实际精确版本，例如
`2.1.259`。配置中不得保存 token、cookie 或其他凭据。

然后运行 preflight：

```powershell
python Code/preflight_rq123_claude_code.py `
  --config Code/config/rq123_claude_sonnet5_high_5target_pilot.local.json `
  --package-root outputs_claude/rq_agent_inputs
```

preflight 只调用 `claude --version` 和 `claude auth status`，不会向模型发送请求。它还会验证：

- Claude 版本和认证状态；
- 禁止恢复 session、禁用工具和结构化输出参数是否完整；
- 所有 package manifest、源实例路径及 SHA-256 是否有效；
- 配置中是否仍有 placeholder。

成功时输出 `READY_NOT_RUN`。这不表示 Agent 已经运行。

## 5. 先 dry-run，再执行 10 个隔离 run

dry-run 只检查队列，不调用 Claude：

```powershell
python Code/run_rq123_agents.py `
  --config Code/config/rq123_claude_sonnet5_high_5target_pilot.local.json `
  --package-root outputs_claude/rq_agent_inputs `
  --run-root outputs_claude/rq_runs `
  --workspace-root outputs_claude/workspaces `
  --case 42204309:42204309_T001 `
  --case 43214420:43214420_T001 `
  --case 43711852:43711852_T009 `
  --case 43948285:43948285_T003 `
  --case 44132019:44132019_T001 `
  --dry-run
```

应显示 `10 isolated Agent run(s) from 10 package(s)`。确认后移除最后的 `--dry-run`，才会真正
调用 Claude Code。Runner 对每个 package 独立完成：

```text
验证 package -> 新建 opaque workspace -> 嵌入四个公开输入到 stdin
-> 启动一次 claude -p -> 提取 structured_output -> schema 校验
-> 冻结 response/hash/日志/Claude metadata -> 删除 workspace
```

中断后可以用同一命令继续；已经完整冻结的 `run_id` 会被跳过，失败项会重新报告。不要在同一
`experiment_id` 下改模型、命令或 effort 后续跑；配置变化会生成新的 `agent_config_id`，也应使用
新的实验名。

## 6. 产物与回传

需要保留并回传：

```text
outputs_claude/rq_runs/
├── experiments/rq123-claude-code-sonnet5-high-5target-pilot/agent_runs.json
└── run_*/
    ├── private/run_manifest.json
    ├── private/source_instances/RQ*.json
    ├── phase_a/agent_response.json
    ├── phase_a/agent_response.sha256
    └── agent/...
```

`private/source_instances/` 是 evaluator-only Gold，绝不能放入 Agent workspace。它的作用是让
整个 frozen run 目录可迁移；`run_manifest.json` 使用相对路径并保留原 SHA-256。复制时必须完整
复制 `run_*`，不能只复制 `agent_response.json`。

## 7. Judge 与评分

可以在 Claude 设备直接 Judge，也可以把完整 `outputs_claude/rq_runs` 复制回有 Stage 1 Judge
凭据的设备。后者不需要重新运行 Claude：

```powershell
python Code/run_rq123_judges.py `
  --config Code/config/rq123_claude_sonnet5_high_5target_pilot.local.json `
  --run-root outputs_claude/rq_runs

python Code/aggregate_rq123_results.py `
  --run-root outputs_claude/rq_runs `
  --experiment-id rq123-claude-code-sonnet5-high-5target-pilot `
  --output outputs_claude/rq_results/rq123_claude_sonnet5_high_5target_summary.json
```

若评分设备没有 local config，复制该非密钥 JSON 即可；不要复制认证目录。Judge 仍使用配置中的
`upwork_stage1` provider 和现有 RQ Judge/scorer。未来公开仓库改用 OpenAI provider 时，只改变
Judge configuration 和 `judge_config_id`，不需要重新运行 Claude Agent。

## 8. 扩展到全量

五 target pilot 的 Agent、Judge、汇总均通过后，再用
`materialize_rq123_release.py` 物化全量 package，并去掉 `run_rq123_agents.py` 的五个 `--case`
过滤。全量实验必须使用新的 `experiment_id`；pilot frozen runs 不应混入全量 ledger。


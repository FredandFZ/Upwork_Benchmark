# Upwork_Benchmark

ReqMemBench 数据标注、Requirement State Graph 回放、LLM target-time 选择与 Gold State
生成代码仓库。整体流程见 [`Code/README.md`](Code/README.md)，Stage 2 的完整设计和参数说明见
[`Code/README_stage2_gold_state.md`](Code/README_stage2_gold_state.md)。

## Stage 2 Gold State 命令速查

在仓库根目录使用 PowerShell：

```powershell
$py = 'D:\Python_env\Miniconda\python.exe'
$projectId = '42204309'
```

只准备 Candidate Packets，不调用 LLM：

```powershell
& $py Code\stage2_generate_gold_state.py --project-id $projectId --prepare-only
```

只完成 LLM evaluation、生成 threshold 5–10 统计表，不生成最终 Gold：

```powershell
& $py Code\stage2_generate_gold_state.py --project-id $projectId
```

使用已有 evaluation 离线重建并打印 threshold 表，不调用 LLM：

```powershell
& $py Code\stage2_generate_gold_state.py --project-id $projectId --threshold-report-only
```

按指定 threshold 信任 AI、跳过人工审核并直接生成 Gold：

```powershell
& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --auto-accept-ai `
  --score-threshold 7
```

人工审核模式：

```powershell
Copy-Item `
  "outputs\stage2\$projectId\target_time_human_review.template.json" `
  "outputs\stage2\$projectId\target_time_human_review.json"

& $py Code\stage2_generate_gold_state.py `
  --project-id $projectId `
  --finalize `
  --human-review-file "outputs\stage2\$projectId\target_time_human_review.json"
```

强制重新调用 LLM 评估全部 Candidate：

```powershell
& $py Code\stage2_generate_gold_state.py --project-id $projectId --force-evaluation
```

更多模型、并发、输入路径、resume 和输出参数见
[`Code/README_stage2_gold_state.md` 的“完整命令速查”](Code/README_stage2_gold_state.md#完整命令速查)。

# Dataset 项目 PII 清洗

`PII_Clean.py` 遍历 `Datasets/project` 中的项目，对每个项目的
`chat_messages.json` 逐条执行消息改写与 PII 清洗，然后将项目副本写入
`Datasets/PII_clean_project`。

## 输入与输出

默认输入：

```text
Datasets/project/<project_id>/
├── chat_messages.json
├── job.txt
├── job_metadata.csv
├── milestones.json
└── deliverables/...
```

默认输出：

```text
Datasets/PII_clean_project/<project_id>/
├── chat_messages.json          # 已清洗
├── job.txt                     # 原样复制
├── job_metadata.csv            # 原样复制
├── milestones.json             # 原样复制
└── deliverables/...            # 原样复制
```

程序只允许修改 `chat_messages.json` 内的：

- `message`：语义等价改写后进行 PII 替换；
- `sender_id`：替换为项目内稳定的 `[SENDER_ID_###]`。

`created_ts`、`message_user_type` 和其他字段保持不变。项目中的其他文件与目录直接复制，不做内容修改。注意：因此 `PII_clean_project` 中除 `chat_messages.json` 外的文件并不保证已脱敏。

运行 manifest 保存在 `Datasets/PII_clean_project/_manifests`，API 日志保存在
`Datasets/PII_clean_project/_logs`，不会加入各项目目录。

## 核心流程

```text
chat_messages.json
        |
        +-- 1. 为每条聊天分配仅供运行时使用的行号
        |      不会向输出 JSON 新增 message_id
        |
        +-- 2. 长消息由 GPT-5.6 Sol 做语义等价改写
        |      短确认消息保留原文
        |
        +-- 3. 基于改写后的完整项目聊天重新识别 PII
        |      邮箱、URL、账号、密码、电话、@句柄、姓名、sender_id
        |
        +-- 4. 确定性替换并写回 message / sender_id
        |
        +-- 5. 复制项目的其他文件，写入 PII_clean_project
```

同一项目内，相同敏感值使用相同占位符，例如 `[EMAIL_001]`、`[URL_001]`、
`[ACCOUNT_001]`、`[PASSWORD_001]` 和 `[CLIENT_NAME_001]`。无法通过问候、致谢或
签名规则识别的姓名可通过 `--extra-name` 补充。

第一阶段会将原始消息发送到现有 Stage 1 Upwork LLM 服务；请只在已获得数据授权的受信任环境中运行。含原始 PII 的模型返回不会写入 checkpoint，失败响应也会被省略。

## 运行命令

只做本地预检查，不调用 API、不写输出：

```powershell
python .\Code\PII_Clean.py --dry-run
```

处理全部项目：

```powershell
python .\Code\PII_Clean.py --insecure
```

只处理一个项目：

```powershell
python .\Code\PII_Clean.py `
  --project-id 42204309 `
  --reasoning-effort xhigh `
  --max-batch-messages 5 `
  --insecure `
  --no-resume `
  --overwrite
```

明确指定输入和输出：

```powershell
python .\Code\PII_Clean.py `
  --source-root .\Datasets\project `
  --output-root .\Datasets\PII_clean_project `
  --insecure
```

环境变量：

```powershell
$env:UPWORK_API_KEY = "..."
$env:UPWORK_BUDGET_ID = "..."
```

`--resume` 默认开启，会跳过输入、模型、Prompt 和参数签名均未变化且已完成的项目。使用 `--no-resume --overwrite` 强制重新生成。

## 测试

```powershell
python -m unittest Code.tests.test_pii_clean -v
```

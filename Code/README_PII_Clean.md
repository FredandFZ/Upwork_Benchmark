# Stage 1 PII 清洗与消息改写

`PII_Clean.py` 为已完成 Stage 1 标注的项目创建可共享的脱敏副本。默认输入是
`outputs/stage1_runs`；脚本不会原地修改该目录。

## 处理流程（v2.0）

```text
原始 normalized_project.json
        |
        +-- 1. 长消息：GPT-5.6 Sol 语义等价改写
        |      短确认消息（如 ok、thank you、I know）保留原句
        |
        +-- 2. 对每一条“改写后/保留后”的消息重新扫描 PII
        |      本地确定性替换为项目内稳定的占位符
        |
        +-- 3. 按 message_id 回写 normalized_project.json
        |
        +-- 4. 按 message_id 同步最终标注的 source_message.text
```

第一阶段只改写句式和措辞，不做脱敏。Prompt 要求模型逐字保留已有的姓名、邮箱、URL、账号、密码、电话和账号句柄；第二阶段才以改写后的实际文本为准逐段检查并替换。这使 PII 检查覆盖模型实际返回的每一段文字，而不是只覆盖改写前的原文。

## PII 替换

同一个项目中，同一敏感值始终得到同一个占位符，例如：

| 类型 | 占位符示例 |
|---|---|
| 邮箱 | `[EMAIL_001]` |
| URL | `[URL_001]` |
| 账号 | `[ACCOUNT_001]` |
| 密码 | `[PASSWORD_001]` |
| 电话 | `[PHONE_001]` |
| @ 句柄 | `[HANDLE_001]` |
| 姓名 | `[CLIENT_NAME_001]`、`[FREELANCER_NAME_001]`、`[PERSON_NAME_001]` |
| sender_id | `[SENDER_ID_001]` |

姓名会从常见的问候、致谢和签名格式中识别。对于这些规则无法识别的姓名，使用 `--extra-name` 明确指定。账号与密码也会在项目范围内复用同一映射，例如某条消息单独给出密码、另一条消息再次引用时，两处都会得到相同的 `[PASSWORD_###]`。

## 隐私边界与失败恢复

这个顺序意味着第一阶段会把原始消息发送给配置的 Stage 1 Upwork LLM 服务；请只在获得数据授权的受信任环境中运行。

脚本不会把含 PII 的第一阶段改写结果写入 `rewrite_checkpoint.json`，也不会产生这种检查点。若 LLM 阶段中途失败，重新运行该项目会从第一批重新开始；失败响应会被直接省略而非保存。完成后的输出、manifest 和 API 调用日志不记录原始敏感值。

旧版 `rewrite_checkpoint.json`（如存在）会被 v2.0 忽略，不会自动删除。

## 输入与输出

输入项目必须同时包含：

```text
outputs/stage1_runs/<project_id>/
├── normalized_project.json
└── final/<project_id>_stage1_annotation.json
```

输出写入：

```text
outputs/stage1_pii_clean_runs/<project_id>/
├── normalized_project.json
├── final/<project_id>_stage1_annotation.json
└── pii_clean_manifest.json

outputs/stage1_pii_clean_annotations/<project_id>_stage1_annotation.json
```

只有以下字段允许变化：

- `normalized_project.json` 中的 `messages[].text` 与 `messages[].sender_id`
- 最终标注中 `requirements[].events[].source_message.text`

写入前会校验 Stage 1 schema，并确保每个标注事件仍按相同的 `message_id` 和 `speaker` 指向同步后的文本；其他标注字段不变。

## 模型与改写约束

默认使用现有 Stage 1 配置中的 `gpt-5.6-sol` 与 `reasoning_effort=high`。每一批返回都必须：

- 与输入一一对应，且 `message_id` 的 JSON 类型不变；
- 改写长消息而非总结、拆分或合并；
- 保留意图、条件、否定、不确定性、时间顺序和标注相关事实；
- 保留数值、金额、日期、版本、文件名、技术标识符和已有占位符；
- 保留原有 PII 的字面值，禁止在第一阶段自行脱敏、编造或省略。

## 运行

先进行不写文件、不调用 API 的预检查：

```powershell
python .\Code\PII_Clean.py --dry-run
```

处理一个项目：

```powershell
python .\Code\PII_Clean.py --project-id 37923084
```

在受信任的 staging 自签名证书环境中，可额外使用 `--insecure`：

```powershell
python .\Code\PII_Clean.py --project-id 37923084 --insecure
```

环境变量与 Stage 1 相同：

```powershell
$env:UPWORK_API_KEY = "..."
$env:UPWORK_BUDGET_ID = "..."
```

默认会跳过签名相同且已完成的项目。使用 `--no-resume --overwrite` 强制重新生成：

```powershell
python .\Code\PII_Clean.py --project-id 37923084 --insecure --no-resume --overwrite
```

补充无法通过规则自动识别的姓名：

```powershell
python .\Code\PII_Clean.py --project-id 37923084 --extra-name "Alice Smith"
```

## 测试

```powershell
python -m unittest discover -s Code\tests -v
```

PII 单元测试覆盖确定性替换、改写后扫描、短消息保留、LLM 返回约束、分批和标注同步。

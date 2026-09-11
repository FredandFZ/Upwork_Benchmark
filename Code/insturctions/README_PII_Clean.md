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
- `sender_id`：运行期间参与 PII 审计，写入最终 JSON 时删除；
- `created_ts`：写入最终 JSON 时删除。

`message_user_type` 和其他字段保持不变。最终每条聊天记录都不包含 `sender_id` 与
`created_ts`。项目中的其他文件与目录直接复制，不做内容修改。注意：因此
`PII_clean_project` 中除 `chat_messages.json` 外的文件并不保证已脱敏。

运行 manifest 保存在 `Datasets/PII_clean_project/_manifests`，API 日志保存在
`Datasets/PII_clean_project/_logs`，不会加入各项目目录。

## 核心流程

```text
chat_messages.json
        |
        +-- 1. 为每条聊天分配仅供运行时使用的行号
        |      不会向输出 JSON 新增 message_id
        |
        +-- 2. 本地提取候选出现位置，GPT-5.6 Sol 阅读完整消息进行属性分类
        |      按 occurrence 区分列表序号、业务数字、金额、日期、版本、文件名
        |      以及技术标识和 PII 内部数字；本地 hint 不是最终结论
        |
        +-- 3. GPT-5.6 Sol 做结构改写和上下文去定位化
        |      必须改变词序、从句组织、语态或句子拆合
        |      必须为上述可定位值生成无关但类型相近的虚构替代值
        |      仅替换同义词会校验失败；短确认消息保留原文
        |      含待合成值的短消息也会进入本阶段
        |      单独的邮箱、URL、@句柄或电话号码留给 PII 阶段
        |
        +-- 4. GPT-5.6 Sol 逐条审查改写后的全部聊天
        |      邮箱、URL、账号、密码、电话、@句柄、姓名、项目名、sender_id
        |      并兜底清除第一阶段漏掉的真实公共公司/服务名
        |
        +-- 5. LLM 返回实体清单、占位符及最终 message / sender_id
        |      本地只校验：无漏项、非 PII 字符未变化、映射跨批次一致
        |
        +-- 6. 删除输出行中的 sender_id 与 created_ts
        |      复制项目的其他文件，写入 PII_clean_project
```

同一项目内，相同敏感值使用相同占位符，例如 `[EMAIL_001]`、`[URL_001]`、
`[ACCOUNT_001]`、`[PASSWORD_001]`、`[CLIENT_NAME_001]` 和
`[PROJECT_NAME_001]`；公共实体兜底类别为 `[ORGANIZATION_001]` 和 `[SERVICE_001]`。
占位符由第三阶段 LLM 分配，本地状态机检查类别编号、冲突和
复用一致性。`--extra-name` 可向本地漏项审计器补充必须被模型清除的姓名。

第一阶段不再保留数字、日期、金额、版本号、文件名以及真实公共公司/公共服务名称。
模型必须把这些内容改成无关但类型和上下文角色相近的虚构值，例如改变金额和日期、替换
版本号与文件名，并把 `Coinbase Commerce`、`Stripe` 等真实服务改成中性的虚构服务名。
原值不得通过轻微遮盖或派生方式保留，也不能换成另一个真实公共品牌。本地验证器要求原值
完全消失，同时要求数字类、版本类和文件名类的出现数量保持一致，防止模型直接删除事实。
带货币符号或货币代码的值会先按完整金额识别，再进行版本号和普通数字识别；例如
`$15.00` 是一个 `AMOUNT`，不会再把其中的 `15.00` 误判为 `VERSION`。
数字如果属于受保护技术标识的一部分，则不作为独立数字改写。例如 `ERC-721`、`AES-256`
和 `SHA-256` 必须整体原样保留；改变其中数字会改变技术 requirement，而不是完成去定位化。
行首的有序列表编号（例如 `1.`、`2)`、`3\.`）只表示步骤结构，不是可定位项目的业务
数值，因此不会被随机改写；模型必须保持编号及顺序不变。原始消息中没有空格的写法
（例如 `1.Text`），以及 `1 - Text`、`2 – Text` 形式也按列表编号处理；但 `1.5` 这样的
十进制数和 `1-2 days` 这样的范围仍属于业务数值。
识别器会综合行首位置、显式分隔符、Markdown 包裹以及同一消息区块是否构成从 1 开始的
连续编号序列；编号之间允许夹有说明行。因而 `1-grid` 或 `1 #rules` 只有在形成连续列表时才作为结构编号；孤立的
`1 minute`、时间、地址、数值范围和小数仍进入业务数字改写。紧凑写在同一行的连续
`1. ... 2. ...` 也会作为列表处理。
如果数量或类型仍不一致，失败摘要会记录输入和输出的类别计数，便于直接识别模型是遗漏了
普通数字、金额、日期、版本还是文件名，而不会把原始敏感值写入日志。

邮箱、URL、账号、密码、电话号码、@句柄和 `sender_id` 不在上述上下文数值规则中拆开
修改，而是保留到第二阶段整体识别和替换，避免只改变其中的数字后破坏 PII 边界。公共
公司/服务名检测也会跳过这些完整 PII 区域：例如 `docs.google.com` 中的 `Google` 不会让
单独 URL 误入句式改写阶段，第二阶段会直接替换整个 URL。

第二阶段 Prompt 要求 LLM 识别类似 `BooksOnChain` 的项目/产品/品牌私有专名，使用
`PROJECT_NAME`；如果仍有真实公共公司或服务漏过第一阶段，则分别使用 `ORGANIZATION`
或 `SERVICE` 兜底清除。工具、框架、协议、功能机制和其他 requirement 术语仍不能被当成
项目名；`OAuth`、`USDC`、`ETH`、`BTC`、`KYC` 等协议或领域概念继续保留。
本地保守项目名规则不再生成最终替换，只负责发现显著漏项并使该 API 响应重试；
不确定的项目名可用 `--extra-project-term` 加入这层强制审计。程序内置保护常见技术名词以及
`gamification mechanics` / `gameification mechanics`，其他术语可用
`--preserve-term` 补充。

长消息的改写结果还要通过本地结构校验。至少需要满足句子拆分/合并、信息短语或从句
换序，或者足够完整的语法重构之一；保持原词序而只替换少量词语会触发重试。
不超过短消息阈值、但因为包含数字、版本、文件名或公共服务名称而进入第一阶段的消息，
可以只完成合成替换，不强制制造不自然的句式重构。
如果整个批次在重试后仍因内容校验失败，程序会自动降级为逐条改写，并附加明确的
结构修复提示，防止一条浅改消息拖垮整个批次。逐条修复不允许沿用原文开头；一般
疑问句会被要求改成疑问词/选项前置结构，陈述句会被要求前置不同从句、宾语或时间
短语，或者改用明显不同的语态。

三个阶段都会调用现有 Stage 1 Upwork LLM 服务，并使用同一个 `--model` 和
`--reasoning-effort`：分类阶段读取含候选位置的完整原始消息，改写阶段使用已验证分类，
PII 阶段发送改写后的每一条消息及 `sender_id`。请只在已获得数据授权的受信任环境中运行。三个阶段的原始模型
失败响应不会写入 checkpoint，日志只保留调用状态和不含原始值的错误摘要。通过全部本地
校验的成功批次会立即保存；批次降级为逐条修复时，每条验证成功的结果也会立即保存，
不会因同批后续消息失败而丢失。checkpoint 位于
`Datasets/PII_clean_project/_checkpoints/<project_id>/`：`phase0_context.json` 保存分类，
`phase1_rewrite.json` 保存已验证改写，`phase2_pii.json` 保存已验证的 PII 响应及占位符状态。项目失败后再次运行时，会验证输入、模型、Prompt、
批大小及 checkpoint 内容哈希，然后跳过已经完成的批次，从首个未完成批次继续。
v6.0 会兼容读取 v5.7–v5.12 的第一阶段 checkpoint，并用当前规则逐条重新校验后恢复，
因此规则修复不会迫使未完成项目从头改写。

第一阶段 checkpoint 在第二阶段完成前可能仍含有待清除 PII，只应在受信任环境保存。项目
全部成功并写入最终文件和 manifest 后，程序会自动删除该项目的临时 checkpoint。局部续跑
默认开启，并独立于 `--resume/--no-resume`；需要完全从头生成时使用
`--no-partial-resume`。

与旧版“本地确定性替换”相比，正式运行现在会额外调用上下文分类和 PII 审查批次，因此耗时和 API
用量都会增加。`--max-batch-messages` 与 `--max-batch-chars` 同时作用于分类、改写和 PII
阶段；较小批次更容易定位失败消息，但请求数更多。

第三阶段不是让本地正则直接改写结果。本地规则只做 fail-closed 验收：LLM 必须为每个
实际替换声明精确原文片段、类别和占位符；验证器以 LLM 返回的最终文本为准，确认每个变化
都能由一条声明精确还原。模型偶尔会同时声明完整实体及其内部子串，这类没有实际参与最终
文本生成的冗余嵌套声明会被忽略，也不会占用编号或写入跨批次映射；真正使用的替换仍必须
互不冲突且通过逐字符验证。如果模型
漏掉显著 PII、修改了非 PII 内容、误删受保护术语或产生占位符冲突，整批响应会被拒绝并
重试，批量重试失败后自动降级为逐条 API 审查。

## v6.0：先分类，再改写

v6.0 不再让本地正则最终决定每个数字的语义属性。正式运行采用三个 LLM 阶段：

1. `PII_CLEAN_CONTEXT_CLASSIFY`：本地只提取候选出现位置并分配 `C001`、`C002` 等编号；
   GPT-SOL 阅读完整消息，把每个位置分类为 `LIST_INDEX`、`NUMBER`、`AMOUNT`、`DATE`、
   `VERSION`、`FILENAME`、`TECHNICAL_IDENTIFIER` 或 `PII_COMPONENT`。本地 `local_hint`
   只作为提示，不是最终结论。
2. `PII_CLEAN_REWRITE`：根据第一阶段的逐位置分类保留列表序号和技术标识，替换业务数字、
   金额、日期、版本及文件名，同时完成句式结构改写。同一字面值在不同位置可以执行不同动作。
3. `PII_CLEAN_REDACT`：LLM 对改写后的完整消息进行 PII 识别和占位符替换。

列表编号采用两条互补的验收路径：本地结构解析器只严格比较它能确定识别的行首编号，
例如 `1.`、`2)`；LLM 根据完整语境判断出的其他结构编号（例如 `Option 1`）则由逐位置
`LIST_INDEX` 保留校验负责。这样既不会把方案标题误当成需要替换的业务数字，也不会把
LLM 识别出的标题编号错误传给只能识别行首列表的解析器。即使一个批次恢复 checkpoint 后
只剩一条消息，该消息校验失败时也会进入带有具体编号保留要求的单消息修复调用。

分类结果保存到 `_checkpoints/<project_id>/phase0_context.json`。批次失败并降级为逐条分类时，
每条成功结果都会立即保存。旧版 `phase1_rewrite.json` 会按新分类逐条重新验证；不符合新规则的
个别缓存记录只会单独重生成，不会清空整份 checkpoint。

这种设计仍保留本地正则，但正则只负责找出候选片段、提供非强制提示和执行安全校验；数字的
最终语义属性由读取了完整消息的 GPT-SOL 决定。

## 运行命令

只做本地预检查，不调用 API、不写输出。这里的 PII 数量只是本地审计候选估计，实际
识别与替换仍由正式运行中的第二阶段 LLM 完成：

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

补充项目名和必须原样保留的术语：

```powershell
python .\Code\PII_Clean.py `
  --project-id 42204309 `
  --extra-project-term "Project Rebuild" `
  --preserve-term "Small Block" `
  --preserve-term "Big Block" `
  --insecure `
  --no-resume `
  --overwrite
```

人工审核后的个别改写默认从 `Code/PII_Clean_manual_rewrites.json` 加载，也可通过
`--manual-rewrites` 指定其他文件。每条记录必须带原消息的 SHA-256；只要原消息变化，
人工改写就会被拒绝，从而避免套用到错误的行。manifest 只记录当前项目实际使用的
人工改写哈希，不会因其他项目的人工改写变化而失效。

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

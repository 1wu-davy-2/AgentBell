# AgentBell 扩张执行文档

> 策略：纵向优先，横向作为优化项
> 基线：AgentBell v2.9.10
> 状态：草案，待评审
> 日期：2026-11-03
> 适用范围：本机 Windows 桌面版；macOS / Linux 保持基础能力

## 1. 一页结论

AgentBell 下一阶段不追求“更多入口”，而是把提醒从**任务结束**推进到**任务需要你**。

纵向主线按顺序执行：

1. **V1 等待输入提醒**（P0）：Agent 等待权限确认、选项回答、限流恢复或上下文处理时提醒。
2. **V2 运行时间线**（P1）：把通知与会话记录合成一次运行，展示阶段、耗时、工具调用和结果。
3. **V3 可操作通知**（P1）：在通知卡片里查看记录、回到终端、打开项目，不执行审批或任意命令。
4. **V4 规则精细化**（P2）：按等待原因、来源、状态、时长决定声音、弹窗和渠道。

横向优化项在纵向主线稳定后再做：

- **H1 事件协议 + CLI/SDK**：把 `/notify` 固化为稳定协议，提供接入示例。
- **H2 渠道扩展**：Slack、Discord、钉钉、邮件等。
- **H3 编辑器/桌面集成**：VS Code / Cursor 扩展、Windows 小组件。
- **H4 自托管多机聚合**：只读汇总，不做云端 SaaS。

**不做**：云端账号、Web 面板、Agent 编排、自动批准权限、修改 Agent 会话文件、执行任意命令。

## 2. 原则与边界

| 原则 | 具体要求 |
| --- | --- |
| 本地优先 | HTTP 只绑定 `127.0.0.1`；历史只写本机 SQLite；不引入云端依赖 |
| 只读会话 | 只读取 Agent 会话文件，不写入、不改写、不删除 |
| 提醒而非编排 | 不替用户批准权限，不替 Agent 决定下一步 |
| 原生界面 | 继续使用 PySide6，不增加 Web UI |
| 向后兼容 | 老配置、老 `/notify` 客户端不破坏；新增字段全部可选 |
| 降噪优先 | 推断型提醒默认保守；同一等待事件只提醒一次 |
| 可关闭 | 每个新能力都有独立开关，异常时可完全退回 2.9.10 行为 |
| 安全动作 | 动作类型白名单；禁止 `shell=True`；不执行任意命令 |
| 隐私 | 外部渠道默认只发标题、摘要、来源，不发送完整会话内容 |

## 3. 现状与缺口

### 3.1 已有能力

- 通知：成功 / 失败 / 取消 / 进行中，进度、去重更新、优先级、确认、稍后提醒。
- 通知动作：打开链接、复制、重试、打开目录、打开中心、回到终端。
- 策略：免打扰、全屏 / 会议抑制、锁屏保留、聚合摘要、未读升级、规则匹配。
- 渠道：Webhook、飞书、企业微信、ntfy、Bark、Telegram。
- 会话：扫描 Claude Code / Qoder 会话；只读解析转录；「进行中」自动汇集近期活跃会话。
- 统计：成功率、平均耗时、待确认数量、近 7 天趋势。
- 接入：本机 `/notify` API、示例配置、GitHub Releases 自更新。

### 3.2 关键缺口

| 缺口 | 影响 |
| --- | --- |
| 只有“进行中 / 已结束”，没有“需要你” | 用户仍要反复切回窗口查看 Agent 是否卡在确认或提问 |
| 通知与会话记录彼此独立 | 看到提醒后，难以还原这次运行发生了什么 |
| 通知更新是覆盖式写入 | 无法回看“开始 → 等待 → 继续 → 结束”的阶段变化 |
| 规则只看来源、标题、状态 | 无法按项目、等待原因、运行时长分流 |
| 会话推断只做元数据扫描 | 没有针对“等待输入”的增量检测 |
| 接入协议未版本化 | 横向做 SDK / 编辑器扩展时容易反复改字段 |

## 4. 纵向主线

### 4.1 V1 等待输入提醒（P0 / 2.10.0）

#### 目标

当 Agent 停下来等待用户时，AgentBell 在 10–20 秒内给出一次明确提醒；用户点击后能回到对应终端或会话。任务正常结束时，不产生额外的“等待”误报。

#### 用户故事

> 我在等 Claude Code 改一个跨文件 bug。它执行到一半弹出权限确认，但我在做别的事。AgentBell 提醒我“Claude Code 正在等待权限确认”，我点一下回到终端处理，而不是十分钟后才发现它一直停着。

#### 关键决策：不新增状态枚举

不增加 `waiting` 状态，而是在现有 `running` 通知上增加：

```text
needs_input: bool
wait_reason: "permission" | "question" | "rate_limit" | "context_limit" | "other"
wait_source: "explicit" | "inferred"
session_id: str | None
run_id: str | None
```

理由：

- 现有状态筛选、统计、声音和渠道都基于四个状态，新增枚举会扩大回归面。
- “等待输入”本质上是进行中的子状态，不是任务终态。
- 老客户端不传新字段时，行为与 2.9.10 完全一致。

约束：`needs_input=true` 只允许与 `status="running"` 一起使用；其他组合由 API 返回 422。`wait_reason` 缺省为 `other`；`wait_source` 缺省为 `explicit`。

#### 两条检测路径

**A. 显式上报（首选，可靠）**

任何 Agent、脚本或 Hook 都可以调用 `/notify`：

```json
{
  "title": "Claude Code 等待权限确认",
  "status": "running",
  "needs_input": true,
  "wait_reason": "permission",
  "wait_source": "explicit",
  "session_id": "abc123",
  "run_id": "run-20261103-001",
  "source": "Claude Code",
  "summary": "需要允许执行 npm test",
  "origin": { "pid": 12345, "window_title": "Claude Code" }
}
```

后续第一版提供：

- Claude Code Hook 示例；
- Codex / Gemini CLI / 通用 shell 的包装脚本示例；
- 一份最小 Python 调用片段。

显式上报是 V1 的主路径。它不依赖会话文件格式，且能准确表达“等待什么”。

**B. 本地推断（兜底，可关闭）**

新增 `agentbell/attention.py`，与现有元数据扫描分离：

- 只处理最近 10 分钟内活跃、且位于已知根目录下的 Claude Code / Qoder 会话。
- 增量读取文件尾部，最多 256 KB；记录路径、文件大小、偏移和最后一行哈希。
- 每 5 秒扫描一次；同一会话连续两次命中才上报，降低抖动。
- 只做只读解析，不把会话内容写入日志或数据库正文。

推断信号：

| 原因 | 信号 | 默认动作 |
| --- | --- | --- |
| `permission` | 最后一条 assistant 含 `tool_use`，没有匹配的 `tool_result`，文件 20 秒无增长 | 弹窗，标记“推断” |
| `question` | 最后一条 assistant 文本以问号或“是否 / 要不要 / Would you like / Shall I”等结尾，20 秒无新用户输入 | 只进通知中心，默认不弹窗 |
| `rate_limit` | 尾部出现速率限制、配额相关错误文本 | 弹窗 |
| `context_limit` | 尾部出现上下文长度、token 超限相关错误文本 | 弹窗 |
| 其他 | 无明确信号 | 不推断 |

推断结果统一标记 `wait_source="inferred"`，UI 显示“推断”提示；用户可在设置中关闭推断，只保留显式上报。

#### 去重与恢复

- 去重键：`wait:<agent>:<session_id>:<episode_fingerprint>`。
- `episode_fingerprint` 优先取最后一条记录的 `uuid`，否则取最后一行哈希；同一等待事件只产生一个通知。
- 用户确认或点击动作只清除未读与托盘计数；`needs_input` 在会话恢复写入或显式上报 `needs_input=false` 时清除，避免“已点过但仍在等待”被误判为已解决。
- 会话恢复时追加一条 `resumed` 时间线事件（V2 使用），卡片保留“曾等待输入”的历史，但不再计入待输入数量。
- 全局冷却：同一会话 2 分钟内最多一次等待提醒；跨会话沿用现有 `popup_cooldown_seconds`。

#### API 与存储

`agentbell/api.py`：

- `NotifyPayload` 增加上述五个可选字段。
- 校验 `needs_input` 与 `status` 的组合；未知 `wait_reason` 归一化为 `other` 并记录警告。
- 不新增公共端点；继续使用 `POST /notify`。

`agentbell/storage.py`：

- 当前建表是 `CREATE TABLE IF NOT EXISTS`，没有迁移框架；新增 `_ensure_columns()`，用 `PRAGMA table_info` 检查后执行 `ALTER TABLE ADD COLUMN`。
- 新列：`needs_input INTEGER NOT NULL DEFAULT 0`、`wait_reason TEXT NOT NULL DEFAULT ''`、`wait_source TEXT NOT NULL DEFAULT 'explicit'`、`session_id TEXT`、`run_id TEXT`。
- 新索引：`idx_notifications_needs_input`、`idx_notifications_run`。
- 迁移必须幂等，并用 2.9.10 结构的旧数据库做回放测试。

#### 界面

- 通知卡片：等待中的卡片显示“待输入”徽标和原因；推断型增加“推断”小标签。
- 状态筛选：在“进行中”下增加“待输入”子筛选，不新增顶级标签页。
- 进行中页：活跃会话卡片显示“等待确认 / 等待回答 / 限流”状态。
- 托盘：未确认的等待提醒计入托盘提示与未读数。
- 偏好设置：新增“等待提醒”分组：
  - 启用显式上报提醒；
  - 启用本地推断；
  - 推断空闲阈值（默认 20 秒，范围 10–120 秒）；
  - 提问类推断默认只进中心；
  - 每个 Agent 的开关（首版 Claude Code / Qoder）。

#### 验收标准

- 显式上报从发出到通知中心可见小于 1 秒。
- 推断检测 P50 小于 10 秒，P95 小于 20 秒（从文件停止增长算起）。
- 测试语料中误报率低于 10%，同一等待事件重复弹窗不超过 1 次。
- 正常结束、长工具执行、用户主动中断三类场景不产生“等待输入”提醒。
- 不修改任何 Agent 会话文件；不向日志写入会话正文。
- 新增测试覆盖：API 校验、迁移、去重、恢复、Claude/Qoder 适配器、UI 徽标。

#### 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 权限确认提示没有写进 JSONL | 显式上报为主；推断只作为兜底，不承诺 100% 覆盖 |
| 长工具执行被误判为等待 | 连续两次扫描 + 20 秒阈值；首版优先显式上报 |
| 会话格式升级导致解析失效 | 每个 Agent 适配器独立版本；语料回归；失败只降级不崩溃 |
| 询问类误报打扰 | 默认只进中心；用户按需开启弹窗 |
| 迁移破坏历史库 | 幂等 `ALTER TABLE`；旧库回放测试；迁移失败时保留原库并提示 |

### 4.2 V2 运行时间线（P1 / 2.11.0）

#### 目标

把一次 Agent 运行从“几条互相独立的通知”变成“一条可回看的时间线”：

```text
开始 → 执行中 → 等待权限 → 已继续 → 完成（成功）
```

#### 数据模型

新增只追加表 `run_events`：

```sql
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    notification_id TEXT,
    session_id TEXT,
    agent TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_run_events_session ON run_events(session_id);
```

`kind`：`started`、`progress`、`waiting_input`、`resumed`、`finished`、`note`。

不为时间线单独建 `runs` 表；运行状态由首尾事件推导，等统计需要时再引入。

#### 事件写入

- `/notify` 新增可选 `phase` 字段；显式传入时追加一条 `run_events`。
- 未传 `phase` 时，只在状态变化时推断追加：`running` 首次出现记 `started`，终态记 `finished`。
- `run_id` 生成顺序：客户端传入 → `session:<session_id>` → `notify:<dedupe_key>` → `single:<notification_id>`。
- 同一 `run_id` 的同一 `phase` 在 5 秒内重复上报时合并，避免进度刷屏。
- 现有通知表继续作为“当前状态”读模型；`run_events` 只负责历史。

#### 界面

- 通知卡片增加“时间线”按钮（有 `run_id` 时显示）。
- 时间线弹窗展示：阶段、时间、相对耗时、状态、来源、关联会话。
- 会话详情页若找到对应 `run_id`，显示“本次运行”区块。
- 统计页新增：运行数、成功率（按 run 去重）、P50/P90 运行时长、等待输入总时长。

#### 验收标准

- 一次包含等待的完整运行能展示开始、等待、继续、结束四个阶段。
- 时间线 100 条事件内打开时间小于 300 ms。
- 缺少 `run_id` / `session_id` 的旧通知不报错，继续按原方式展示。
- 事件只追加、不覆盖；删除通知时按历史保留策略清理孤儿事件。

### 4.3 V3 可操作通知（P1 / 2.12.0）

#### 范围

在现有动作基础上增加两类**本地只读动作**：

| 动作 | 行为 | 安全边界 |
| --- | --- | --- |
| `session` | 打开 AgentBell 内置会话记录 | 只接受本地已知会话 ID |
| `timeline` | 打开运行时间线 | 只接受 `run_id` |
| `focus` | 回到终端 | 沿用 2.9.7 的前台兜底 |
| `retry` | 重试已有通知动作 | 沿用现有实现 |

**不增加**“批准权限”“自动继续”“发送任意提示词”动作。审批必须回到终端由用户完成。

#### 交互

- 弹窗与通知中心都显示动作按钮，主按钮固定为“回到终端”或“查看记录”。
- 动作失败时给出非阻塞提示，不吞掉错误。
- 键盘可达：`Enter` 执行主动作，`Esc` 关闭。

#### 验收标准

- 动作只执行白名单类型；不存在拼接 shell 命令的路径。
- 未知 `session_id` / `run_id` 给出明确失败提示，不执行任何外部命令。
- 原有动作回归通过。

### 4.4 V4 规则精细化（P2 / 2.13.0）

在 `RuleConfig` 中增加：

```text
needs_input: bool | None
wait_reason: str | None
min_duration_seconds: int | None
max_duration_seconds: int | None
project: str | None          # 基于 origin.working_dir 或会话项目路径
```

匹配顺序保持“后匹配规则覆盖标量字段”。新增字段全部可选，旧配置不变。实际语义：

| 字段 | 匹配规则 |
| --- | --- |
| `needs_input` | 布尔精确匹配；`false` 表示只匹配非等待通知 |
| `wait_reason` | 限定 `permission` / `question` / `rate_limit` / `context_limit` |
| `project` | 忽略大小写的 glob，取 `origin.working_dir` 或会话项目路径的末级目录名 |
| `min_duration_seconds` / `max_duration_seconds` | 从 `duration` 解析，边界包含；缺失或无法解析时带时长条件的规则不匹配 |

`/notify` 与本地推断的等待通知都会经过规则；规则从 `ConfigRef` 实时读取，设置保存后立即生效，无需重启 HTTP 服务。

典型规则（见设置页示例）：

```json
[
  {"name": "等待权限时高优先级", "wait_reason": "permission", "needs_input": true, "priority": "high"},
  {"name": "测试项目仅在失败时确认", "project": "demo-*", "status": "failed", "priority": "critical", "require_ack": true},
  {"name": "长任务完成后转投", "min_duration_seconds": 600, "channels": ["webhook"]}
]
```

验收：规则匹配单测覆盖空值、组合条件、优先级覆盖；设置页保存后立即生效；非法时长被校验拒绝。

## 5. 横向优化项

横向项不进入 2.10.0 主线；只有纵向指标达标后才排期。

### H1 事件协议 + CLI/SDK（P1，依赖 V1 字段冻结）

- 把 `/notify` 字段固化为文档化协议，增加 `schema_version: "1"`。
- 提供 `examples/integrations/`：
  - Claude Code Hook；
  - Codex / Gemini CLI 包装脚本；
  - 通用 shell 与 Python 片段；
  - Node 最小客户端。
- 第一阶段只做“事件上报”，不做 Agent 进程托管；CLI 包装器只负责开始/结束/等待事件。
- 验收：示例可复制运行；不依赖第三方包；错误不阻断被包装命令。

### H2 渠道扩展（P2）

- 新增 Slack、Discord、钉钉、邮件。
- 等待输入使用独立文案模板，不直接复用“完成”模板。
- 外部渠道默认只发标题、摘要、来源；完整会话内容永不外发。
- 验收：每个渠道有发送成功/失败测试；超时与重试策略一致。

### H3 编辑器 / 桌面集成（P2）

- VS Code / Cursor 扩展：状态栏显示当前等待状态，点击打开 AgentBell 通知中心。
- Windows 小组件：显示今日运行数、待输入数。
- 不嵌入 WebView，不复制一套通知 UI。
- 验收：扩展不可用时不影响 AgentBell 主程序。

### H4 自托管多机聚合（P3，暂不排期）

- 可选自托管中继，聚合多台机器的只读通知流。
- 不做账号体系、不做云端托管、不做团队管理后台。
- 只有在前三项稳定且有明确多机需求时再评估。

## 6. 版本与里程碑

| 版本 | 内容 | 优先级 | 估算 | 退出条件 |
| --- | --- | --- | --- | --- |
| 2.10.0 | 数据字段、迁移、API、V1 显式上报 + 本地推断、设置与徽标 | P0 | 8–12 人日 | 误报率 <10%，重复 ≤1 次/事件，285+ 测试通过 |
| 2.10.x | 语料调优、误报修复、文档 | P0 | 2–4 人日 | 连续 2 周日常使用无阻断问题 |
| 2.11.0 | `run_events`、时间线、运行统计 | P1 | 8–12 人日 | 90% 运行有开始/结束；时间线可用 |
| 2.12.0 | `session` / `timeline` 动作、规则扩展 | P1/P2 | 5–8 人日 | 动作白名单与规则测试通过 |
| 2.13.0 | 规则精细化：等待原因、`needs_input`、时长、项目分流、规则实时生效 | P2 | 3–5 人日 | 规则匹配与非法时长测试通过 |
| 2.14+ | H1 协议/SDK、H2 渠道、H3 编辑器集成 | P2 | 视范围 | 纵向指标连续两个版本达标 |

估算口径：单人、熟悉现有代码、含测试与文档，不含 macOS/Linux 适配。

## 7. 技术落点

| 文件 | 改动 |
| --- | --- |
| `agentbell/config.py` | 新增 `AttentionConfig`、规则字段、默认值与校验 |
| `agentbell/models.py` | `Notification` 增加等待字段；`WaitReason` 类型 |
| `agentbell/api.py` | `NotifyPayload` 新字段、组合校验、`phase` |
| `agentbell/storage.py` | 幂等列迁移、`run_events` 表、事件查询、统计扩展 |
| `agentbell/agent_sessions.py` | 增量尾部读取器；保持元数据扫描不变 |
| `agentbell/attention.py`（新） | 等待检测器、Claude/Qoder 适配器、去重与冷却 |
| `agentbell/app.py` | 连接检测器与通知管线；恢复事件 |
| `agentbell/policy.py` | `needs_input` / `wait_reason` / 时长 / 项目规则匹配 |
| `agentbell/ui/window.py` | 待输入徽标、筛选、时间线弹窗 |
| `agentbell/ui/settings.py` | “等待提醒”设置分组、规则字段 |
| `agentbell/channels.py` | 等待输入文案模板；后续渠道 |
| `tests/` | 会话语料、迁移、检测、去重、规则、UI 测试 |
| `config.example.json` | 新配置示例 |

## 8. 测试与验收

### 8.1 单元与集成

- 用匿名 JSONL 语料覆盖：权限等待、提问等待、限流、上下文超限、长工具执行、正常结束、用户中断、格式损坏。
- 旧库迁移：用 2.9.10 表结构创建数据库，打开后断言新列、索引、历史数据完整。
- API：字段组合、未知枚举、超长文本、旧客户端请求。
- 去重：同一事件重复扫描、恢复后再次等待、应用重启后去重。
- 规则：`needs_input` 与来源、状态、时长组合。

### 8.2 性能与安全

- 会话尾部读取不超过 256 KB/次；8 个活跃会话扫描一轮小于 50 ms。
- 空闲 CPU 增量小于 2%；内存增量小于 30 MB。
- 只读打开文件；路径必须位于已知会话根目录；拒绝符号链接逃逸。
- 不执行 shell；不记录 token；不把会话正文写入日志。
- 推断失败只降级，不影响通知、托盘和 HTTP 服务。

### 8.3 打包与冒烟

- 新版本使用新 spec（例如 `AgentBell22.spec`），CI 自动选择编号最大的 spec。
- 冒烟必须使用隔离配置、端口和实例名，禁止占用生产 `8765`。
- 验证首次运行配置、等待通知、点击动作、退出与单实例行为。
- 未经明确批准不重启生产；发布后同步 README、官网与 Release。

## 9. 风险、开放问题与决策门

### 开放问题

1. Claude Code 的权限确认是否稳定写入 JSONL？先用真实脱敏语料验证；不确定时以显式 Hook 为准。
2. 提问类推断是否值得默认弹窗？首版默认只进中心，观察两周再决定。
3. 运行时间线是否需要独立“运行”页？优先复用通知卡片详情，避免新增页面。
4. 是否支持 Codex / Gemini CLI 的本地推断？首版只做显式上报，推断按适配器逐步增加。

### 决策门

- V1 误报率连续两周高于 15%：关闭推断默认值，只保留显式上报，不进入 V2。
- 时间线关联率低于 70%：先补 `session_id` / `run_id` 上报，不急于做 UI。
- 横向项导致核心测试或启动性能回退：暂停横向，回到纵向。

## 10. 第一迭代任务清单

- [x] F1：`Notification` 等待字段与 `WaitReason` 类型。
- [x] F2：SQLite 幂等迁移与新索引，旧库回放测试。
- [x] F3：`/notify` 新字段、组合校验与文档。
- [x] F4：`AttentionConfig`、设置页“等待提醒”分组。
- [x] V1.1：Claude Code / Qoder 脱敏语料与解析夹具。
- [x] V1.2：增量尾部读取器（偏移、哈希、大小上限）。
- [x] V1.3：两类适配器与等待信号识别。
- [x] V1.4：连续扫描、去重、冷却、恢复处理。
- [x] V1.5：通知中心徽标、进行中子筛选、活跃会话状态。
- [x] V1.6：显式 Hook / 脚本示例。
- [x] V1.7：单元、集成、UI 与隔离冒烟。
- [ ] V1.8：README、system-architecture 已更新；官网更新与版本发布待确认。

完成定义（DoD）：

- 功能默认配置可用，关闭开关后行为与 2.9.10 一致；
- 新增测试与既有测试全部通过（当前全量 305 项）；
- 无生产端口占用、无会话文件写入、无任意命令执行；
- 文档说明检测原理、置信边界和已知限制。

## 11. 第二迭代任务清单（V2 运行时间线）

- [x] V2.1：`run_events` 只追加表、两个索引与旧库幂等迁移。
- [x] V2.2：`run_id` 生成顺序、可选 `phase` 字段与组合校验。
- [x] V2.3：自动阶段推断（开始 / 等待 / 继续 / 完成）与同阶段 5 秒合并。
- [x] V2.4：通知卡片时间线弹窗、会话详情「本次运行」区块。
- [x] V2.5：统计页运行数、运行成功率、P50/P90 耗时与累计等待。
- [x] V2.6：存储 / 推断 / API / UI 测试与隔离冒烟（当前全量 324 项）。
- [ ] V2.7：官网更新与版本发布待确认。

V2 完成定义（DoD）：

- 一次包含等待的完整运行能展示开始、等待、继续、完成四个阶段；
- 事件只追加、不覆盖；删除或裁剪通知时同步清理孤儿事件；
- 缺少 `run_id` / `session_id` 的旧通知不报错，按原方式展示；
- 关闭历史存储时时间线入口隐藏，通知与弹窗行为与 2.10.0 一致；
- 新增测试与既有测试全部通过；文档说明 `run_id` 生成顺序与推断边界。

隔离冒烟（端口 `8791`、独立实例 `smoke22`、独立配置与数据库）：完整运行按 `started → waiting_input → resumed → finished` 入库，显式 `phase=progress` 单独成条；100 条事件的时间线弹窗构建约 118 ms。全程未占用生产端口 `8765`，未重启生产实例。

## 12. 第三迭代任务清单（V3 可操作通知）

- [x] V3.1：动作白名单扩展 `session` / `timeline`，`value` 一律忽略，未知类型仍返回 422。
- [x] V3.2：API 校验：`session` 必须有 `session_id`，`timeline` 必须能确定 `run_id`；缺失时忽略并记录警告。
- [x] V3.3：动作排序固定为 `focus` → `session` → `timeline` → 原有顺序，上限 4 个。
- [x] V3.4：弹窗与通知中心渲染只读动作按钮，主按钮保持「回到终端」/「查看记录」。
- [x] V3.5：打开本地会话记录与运行时间线；未知 ID 走托盘非阻塞提示并记录警告。
- [x] V3.6：明确不提供批准权限、自动继续、发送提示词动作；接入说明同步声明。
- [x] V3.7：API / 存储 / UI / 窗口测试与隔离冒烟。
- [ ] V3.8：官网更新与版本发布待确认。

V3 完成定义（DoD）：

- 动作只执行白名单类型，不存在拼接 shell 命令的路径；
- `session` / `timeline` 只读取通知自身的 `session_id` / `run_id`，不执行任何外部命令；
- 未知 `session_id` / `run_id` 给出明确失败提示，不阻塞界面；
- 原有 `focus` / `retry` / `open` / `copy` / `path` / `center` 行为回归通过；
- 通知中心键盘可达：`Tab` 到动作按钮、`Enter` 执行、`Esc` 关闭；弹窗保持不抢焦点；
- 新增测试与既有测试全部通过；README 中英文与系统架构文档同步说明只读边界。

## 13. 第四迭代任务清单（V4 规则精细化）

- [x] V4.1：`RuleConfig` 新增 `needs_input` / `wait_reason` / `min_duration_seconds` / `max_duration_seconds` / `project`，全部可选。
- [x] V4.2：配置校验：等待原因枚举、时长 0–604800 秒、`min ≤ max`、项目长度上限 120，非法值拒绝启动。
- [x] V4.3：规则匹配新增等待原因、`needs_input`、项目 glob（忽略大小写）与时长边界（包含）。
- [x] V4.4：`ConfigRef` 共享实时配置，`/notify` 与本地推断通知均按当前规则匹配，设置保存立即生效。
- [x] V4.5：设置页规则示例与说明更新，覆盖“等待权限”“测试项目”“长任务转投”。
- [x] V4.6：规则 / 配置 / API 测试补充空值、组合条件、优先级覆盖、实时配置与非法时长。
- [x] V4.7：全量回归、2.13.0 打包与隔离冒烟（当前全量 348 项）。
- [x] V4.9：活跃会话卡片移除整卡重复 tooltip，仅在文字截断时显示 32 字换行的紧凑提示，并统一 tooltip 配色。
- [ ] V4.8：官网更新与版本发布待确认。

V4 完成定义（DoD）：

- 规则字段全部可选，旧 `config.json` 无需迁移即可加载；
- 后匹配规则覆盖优先级、静音、确认、自动关闭、弹窗与皮肤等标量字段，`channels` 保持累加；
- 缺少 `duration` 或格式非法时，带时长条件的规则不匹配，不影响其他条件；
- 项目名取自工作目录末级，匹配忽略大小写；本地推断通知使用会话项目路径；
- 设置保存后 `/notify` 立即按新规则分流，无需重启服务；
- 悬停提示只在文字截断时出现，按 32 字换行并使用统一浅色样式，不再出现整卡大提示；
- 新增测试与既有测试全部通过；README 中英文与系统架构文档同步说明字段语义。

隔离冒烟（端口 `8793`、独立实例 `smoke24`、独立配置与数据库，`dist/AgentBell-24.exe`）：`/health` 返回 `2.13.0`；`status=running`、`wait_reason=permission`、`duration=12m`、项目 `demo-api` 的通知同时命中三条示例规则，落库为 `priority=critical`、`require_ack=1`、`channel_types=["webhook"]`；`wait_reason=question`、`5m`、项目 `other-app` 的通知不命中任何规则，保持 `priority=high`、`require_ack=0`、空通道。冒烟时生产实例仍为 `2.9.9`，端口 `8765` 未受影响；随后用户已将生产切换到 `AgentBell-24` / `2.13.0`，并反馈活跃会话悬停提示遮挡相邻记录，修复后重建为 `dist/AgentBell-25.exe`（版本仍为 `2.13.0`）。

# AgentBell develop-cc 执行文档

> 主题：cc-switch 能力迁移（仅 4 个 CLI Agent）+ 后续能力递进
> 状态：待执行，等待用户通知后开始
> 基线：AgentBell 2.13.0 / `develop` 分支 `d600333`
> 目标分支：`develop-cc`（从 `develop` 创建）
> 平台：Windows 10/11 优先；macOS / Linux 保持基础能力
> 日期：2026-11-04

## 1. 一页结论

只迁移 cc-switch 的**供应商档案、配置备份、配置读取**，不迁移代理、路由、聚合、故障转移、MCP/Skills 市场、云同步和十余个工具适配。

四个 Agent 的支持方式不同：

- **Claude Code**：环境变量启动注入，最成熟；
- **Codex**：`-c` 覆盖 + `env_key`，不需要改全局 `config.toml`；
- **Gemini CLI**：环境变量注入，不需要改全局 `settings.json`；
- **Grok Build**：启动注入在官方 Overlay 中受限制，首版只做只读感知与跳转 cc-switch；全局切换作为可选后续项。

版本递进：

| 版本 | 内容 | 优先级 | 估算 |
| --- | --- | --- | --- |
| 2.14.0 | 一键接入器（Hook / 包装脚本）+ 供应商感知（只读） | P0 | 9–15 人日 |
| 2.15.0 | 启动档案：Claude / Codex / Gemini 按启动注入，Grok 只读 | P0/P1 | 8–12 人日 |
| 2.16.0 | 环境体检 Doctor + 项目视图 / 每日摘要 | P1 | 6–10 人日 |
| 2.17.0 | Slack / Discord / 钉钉 / 邮件渠道 + VS Code / Cursor 状态栏 | P2 | 13–20 人日 |
| 2.18+ | 多机只读聚合 | P3 | 15 人日以上，需单独批准 |

**不做**：cc-switch 全量复制、本地代理、自动故障转移、自动批准权限、修改 Agent 会话文件、云端账号与同步、Web 面板。

## 2. 边界与原则

| 原则 | 要求 |
| --- | --- |
| 本地优先 | HTTP 只绑定 `127.0.0.1`；配置、密钥、历史只在本机 |
| 最小写入 | Claude / Codex / Gemini 首版不写全局配置；只有 Hook 安装与可选的 Grok 全局切换会写文件，且必须备份、预览、可撤销 |
| 会话只读 | 只读取 Agent 会话文件，不写入、不改写、不删除 |
| 提醒而非编排 | 不自动批准权限，不自动继续，不发送任意提示词 |
| 密钥最小暴露 | 密钥用 DPAPI 保护；不进入命令行、日志、通知、外部渠道 |
| 原生界面 | 继续使用 PySide6，不增加 Web UI |
| 可回退 | 每个能力独立开关；关闭后行为与 2.13.0 一致 |
| 兼容 cc-switch | 不读取 cc-switch 内部数据库；只读检测当前配置；默认不与 cc-switch 争抢全局配置 |
| 发布克制 | 未经明确批准不推送 tag、不发布 Release、不更新官网、不重启生产实例 |

## 3. 分支与执行流程

### 3.1 分支

开始执行时：

```bash
cd E:/opt/Qoder/TaskBeacon/agentbell
git switch develop
git pull --ff-only
git switch -c develop-cc
```

若 `develop-cc` 已存在，直接 `git switch develop-cc`，不要重建。

- `develop-cc` 只承载本轮 cc-switch 迁移与递进功能；
- 每个里程碑单独提交，提交信息使用 `feat(cc): ...` / `fix(cc): ...`；
- 不直接改 `main`；合并与发布必须等用户确认；
- 官网仓库 `agentbell-site` 使用独立分支 `develop-cc-site`，发布前再合并到 `main`。

### 3.2 版本与构建

| 版本 | 新 spec |
| --- | --- |
| 2.14.0 | `AgentBell26.spec` |
| 2.15.0 | `AgentBell27.spec` |
| 2.16.0 | `AgentBell28.spec` |
| 2.17.0 | `AgentBell29.spec` |

CI 自动选择编号最大的 spec。每个版本都要：

1. 全量测试通过；
2. 隔离冒烟通过（独立配置、独立数据库、独立实例名、端口不得使用生产 `8765`）；
3. README / system-architecture / config.example 同步；
4. 官网与 Release 仅在用户批准后更新。

### 3.3 每阶段检查点

每个版本结束提交一份简短验收记录：

```text
版本 / 分支 / 提交
新增测试数量 / 全量测试结果
隔离冒烟端口、实例名、结果
已知限制
未做事项
等待用户确认后再进入下一版本
```

## 4. 2.14.0：一键接入器 + 供应商感知

### 4.1 目标

1. Claude Code、Gemini CLI、Grok Build 能通过官方 Hook 把“开始 / 等待 / 继续 / 结束”写入 AgentBell；
2. Codex 至少覆盖完成事件，等待权限尽量通过会话推断补齐；
3. 用户能在启动器与会话卡片看到“当前用的是哪个供应商和模型”，但 AgentBell 不读取、不复制密钥；
4. 不修改任何 Agent 会话文件。

### 4.2 一键接入器

#### 4.2.1 接入方式预研门

实现前先用本机 CLI 版本做能力探测，以实际事件为准：

| Agent | 候选机制 | 事件 | 首版覆盖 |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/settings.json` 的 `hooks` | `SessionStart`、`UserPromptSubmit`、`Notification`、`Stop` 等 | 权限等待、提问、结束、恢复 |
| Gemini CLI | `~/.gemini/settings.json` 的 `hooks` | `SessionStart`、`BeforeAgent`、`AfterAgent`、`Notification`、`AfterTool`、`SessionEnd` | 等待、结束、恢复 |
| Grok Build | `~/.grok/hooks/*.json` 或 `~/.grok/config.toml` 的 hooks | 按官方事件表实现 | 等待、结束 |
| Codex | `~/.codex/config.toml` 的 `notify` + 包装脚本 | `agent-turn-complete` | 完成；等待权限需另做会话推断 |

事件名称、字段和触发条件以开始执行时的本机版本为准。若某 Agent 不支持所需事件，只实现已支持部分，并在 UI 与文档标注“部分接入”。

#### 4.2.2 Hook 辅助程序

首版推荐 PowerShell 辅助脚本，避免新增第二个 exe 与更新链路：

- 位置：安装目录下 `assets/hooks/agentbell-hook.ps1`；
- 输入：从 stdin 读取 Hook JSON；
- 行为：
  1. 读取 AgentBell `config.json` 的端口与 token；
  2. 把 Hook 事件映射为 `/notify` 字段；
  3. 只向 `127.0.0.1` 发送，超时 2 秒；
  4. 失败只静默退出，不阻塞 Agent；
  5. 不把 token、Hook 原文写入日志。
- 调用示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<app>\assets\hooks\agentbell-hook.ps1" -Agent claude
```

若实测 Hook 延迟超过 500 ms 或 PowerShell 启动不稳定，再评估独立的 `AgentBellHook.exe` 控制台程序。

#### 4.2.3 安装、预览与撤销

- UI 入口：Agent 启动页的每个已安装 Agent 卡片增加“接入提醒”；
- 点击后先展示将要修改的文件、合并内容和备份路径，不直接写入；
- 安装前备份为 `<原文件>.agentbell-backup-YYYYMMDD-HHMMSS`；
- JSON 使用深度合并，保留已有 hooks、plugins、MCP 等无关键；
- TOML 使用解析后合并，保留未知表与注释无法完全保留时，必须在预览中说明；
- 写文件采用临时文件 + 原子替换 + 文件锁；
- 提供“测试事件”“撤销接入”；
- 撤销只恢复 AgentBell 自己新增的条目，不覆盖用户安装后新加的配置；若文件已被外部修改，提示冲突并让用户选择恢复备份或放弃。

#### 4.2.4 事件映射

| Hook 场景 | `/notify` |
| --- | --- |
| 会话开始 | `status=running`, `phase=started` |
| 等待权限 | `status=running`, `needs_input=true`, `wait_reason=permission`, `wait_source=explicit` |
| 等待回答 | `status=running`, `needs_input=true`, `wait_reason=question`, `wait_source=explicit` |
| 限流 / 上下文 | 对应 `rate_limit` / `context_limit` |
| 用户继续 | `phase=resumed` |
| 结束 | `status=succeeded/failed/cancelled`, `phase=finished` |

`run_id` 读取顺序：Hook 环境变量 `AGENTBELL_RUN_ID` → 事件内的 session id → Hook 生成的稳定哈希。`source` 固定为 Agent 名称；能确定供应商时附带 `provider`。

#### 4.2.5 接入验收

- Claude 权限确认后 2 秒内出现“等待权限”提醒；
- Gemini / Grok 对应等待事件可触发提醒；
- Codex 至少完成事件可触发；等待权限若无法覆盖，必须在 UI 显示“部分接入”；
- 同一等待事件只提醒一次；
- 撤销后配置文件恢复到接入前的语义状态；
- 现有 hooks、MCP、plugins、projects 不丢失；
- 不修改 Agent 会话文件，不读取密钥。

### 4.3 供应商感知（只读）

#### 4.3.1 读取矩阵

| Agent | 文件 | 只读字段 |
| --- | --- | --- |
| Claude Code | `~/.claude/settings.json` | `env.ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`model` |
| Codex | `~/.codex/config.toml` | `model_provider`、`model`、`model_providers.<id>.base_url`、`name` |
| Gemini CLI | `~/.gemini/settings.json`、`~/.gemini/.env` | `model.name`、认证方式、`GOOGLE_GEMINI_BASE_URL`（若存在） |
| Grok Build | `~/.grok/config.toml` | `models.default`、`model.<id>.base_url`、`name`、`api_backend` |

要求：

- 只读取白名单字段，跳过 `api_key`、`token`、`experimental_bearer_token` 等密钥字段；
- 解析失败、文件不存在、字段缺失时返回“未知/默认”，不阻塞界面；
- 按文件 mtime 缓存，启动器刷新时重新读取；
- 不写入任何 Agent 配置文件；
- 检测到 cc-switch 正在管理时，只显示“外部工具管理”，不尝试读取其内部存储。

#### 4.3.2 UI 与通知

- 启动器卡片显示：`当前：DeepSeek / deepseek-chat`（仅示例，实际按读取结果）；
- 通知卡片来源行显示：`Claude Code · DeepSeek`；
- 时间线详情显示本次运行的供应商；
- `/notify` 增加可选 `provider` 字段（长度限制、空值兼容），不传时行为与 2.13.0 一致；
- `RuleConfig` 增加可选 `provider`，支持忽略大小写的 glob；
- 设置页说明“供应商信息只读，不会上传”。

#### 4.3.3 依赖与性能

- Python 3.10 没有 `tomllib`；增加纯 Python `tomli` 依赖，或在源码模式把下限提到 3.11。打包版统一使用 `tomli`，避免版本差异；
- 单次读取 4 个文件目标小于 20 ms；只在启动器刷新、通知到达或设置页打开时读取；
- 不在每次通知发送时同步读盘。

### 4.4 2.14.0 测试、文档与冒烟

新增测试至少覆盖：

- Hook 配置合并、备份、撤销、冲突、非法 JSON/TOML 不写入；
- Hook 事件映射、字段上限、去重、`run_id` 生成；
- 四个 Agent 的配置解析夹具、缺失文件、损坏文件、密钥字段不出现在结果；
- `/notify` 的 `provider` 校验与旧客户端兼容；
- 规则按 `provider` 匹配、大小写与空值；
- 隔离冒烟使用临时 HOME，禁止触碰真实 `~/.claude`、`~/.codex`、`~/.gemini`、`~/.grok`。

验收：

- 全量测试通过，基线为 2.13.0 的 348 项；
- 隔离冒烟端口 `8794`、实例 `smoke26`、独立配置与数据库；
- 生产 `8765` 未占用、生产实例未重启；
- 文档说明每个 Agent 的实际覆盖等级与已知限制。

## 5. 2.15.0：启动档案

### 5.1 目标

把“当前供应商”推进到“每次启动选择档案”，实现 cc-switch 做不到的并行多供应商：

- 同一台机器、两个终端可以同时用不同供应商；
- Claude / Codex / Gemini 不写全局配置；
- Grok 首版只读，提供“打开 cc-switch”跳转；
- 通知、时间线、规则里能区分档案。

### 5.2 数据模型

首版放在 `config.json`，复用现有 DPAPI 配置保存与原子写入：

```text
provider_profiles:
  id / agent_id / name / base_url / model / auth_mode
  secret(dpapi) / extra_env / notes / created_at / updated_at

profile_bindings:
  project_path / agent_id / profile_id

launch_defaults:
  agent_id -> profile_id
```

`secret` 只保存 `dpapi:...` 或 `plain:...` 形式，UI 永远只显示掩码；导出配置默认剔除密钥。

### 5.3 启动注入矩阵

| Agent | 注入方式 | 安全要求 |
| --- | --- | --- |
| Claude Code | 环境变量 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_MODEL`、可选 `ANTHROPIC_SMALL_FAST_MODEL` | 密钥只进子进程环境，不进命令行 |
| Codex | `-c model_provider=...`、`-c model=...`、`-c model_providers.<id>.base_url=...`、`-c model_providers.<id>.env_key=AGENTBELL_PROVIDER_KEY`、`-c model_providers.<id>.wire_api=responses` | provider id 只允许 `[a-z0-9_-]`；密钥由环境变量 `AGENTBELL_PROVIDER_KEY` 提供；参数通过环境变量 JSON 数组传递，不在 PowerShell 字符串中拼接 |
| Gemini CLI | `GOOGLE_GEMINI_BASE_URL`、`GEMINI_API_KEY`、`GEMINI_MODEL` | Base URL 只允许 HTTPS 或 localhost；密钥只进环境 |
| Grok Build | 首版不注入，只读显示 + 打开 cc-switch | 不写 `~/.grok/config.toml` |

启动器改动：

- 现有 `launch_agent(extra_env=...)` 已支持环境注入；
- 为 Codex 增加安全参数传递路径，禁止字符串拼接与 `shell=True`；
- 启动前显示“Agent + 档案 + 项目”，失败时回退到默认配置；
- 每次启动生成 `AGENTBELL_RUN_ID`，Hook 自动沿用。

### 5.4 档案 UI

- 入口：运行环境页新增“供应商档案”分组；
- 档案列表：名称、Agent、地址、模型、最后使用时间、状态；
- 新建 / 编辑 / 复制 / 删除；
- “从当前配置导入”只导入地址、模型、供应商名，密钥留空；
- 项目绑定：手动选择 + 记住上次选择；自动按 cwd 推断放到后续版本；
- 测试连接：可选，用户点击才发起；不发送提示词，不打印密钥；失败只提示状态码/错误类型；
- Grok 档案卡显示“只读；如需切换请使用 cc-switch”，提供跳转按钮。

### 5.5 通知与规则

- `/notify` 的 `provider` 字段正式使用；
- 规则示例：

```json
[
  {"name": "DeepSeek 等待权限", "provider": "deepseek*", "wait_reason": "permission", "priority": "high"},
  {"name": "备用线路失败", "provider": "backup-*", "status": "failed", "require_ack": true}
]
```

- 时间线、统计、会话卡片显示档案名；
- 外部渠道仍只发送标题、摘要、来源和档案名，不发送密钥或完整会话。

### 5.6 2.15.0 验收

- 同一 Agent 两个终端同时使用两个档案，互不影响；
- Claude / Codex / Gemini 启动前后全局配置文件 mtime 不变；
- 密钥不出现在命令行、日志、通知、测试快照；
- DPAPI 往返、旧配置加载、密钥为空、导入不复制密钥；
- 档案删除后不影响已运行会话；
- Grok 只读显示正确，跳转 cc-switch 可用；
- 全量测试通过；隔离冒烟端口 `8795`、实例 `smoke27`；
- 生产未重启，`8765` 未占用。

## 6. 2.16.0：环境体检 Doctor + 项目视图 / 每日摘要

### 6.1 环境体检

- Node / npm / 四个 CLI 的版本与路径；
- 配置文件是否存在、是否可解析、当前供应商与模型；
- 认证状态只显示“已配置 / 未配置”，不显示密钥；
- 供应商连通性：用户点击才测试，优先 `GET /models` 等轻量端点；不发提示词；不记录 token；
- 通知端口是否被占用、数据库是否可写、运行目录权限；
- cc-switch 共存检查：是否安装、是否管理同一 Agent；
- 诊断导出：默认脱敏，剔除 token、key、完整路径中的用户名可选。

### 6.2 项目视图 / 摘要

- 按项目聚合通知、运行、等待时长、成功率；
- 每日/每周摘要：完成数、失败数、等待次数、平均耗时、最活跃 Agent；
- 复用 `run_events` 与统计页，不新增数据库表，除非性能证明需要；
- 摘要可只进通知中心，不默认外发。

### 6.3 验收

- Doctor 在缺 Node、缺 CLI、配置损坏、端口占用、cc-switch 共存五种场景下给出可执行建议；
- 诊断文件不含密钥；
- 项目视图与旧通知兼容；
- 摘要数据与统计页口径一致；
- 全量测试与隔离冒烟通过。

## 7. 2.17.0：渠道扩展 + 编辑器状态栏

### 7.1 渠道

- 新增 Slack、Discord、钉钉、邮件；
- 等待输入使用独立模板，不复用“完成”模板；
- 每个渠道有“测试发送”；
- 默认只发标题、摘要、来源、档案名；
- 超时、重试、限流策略与现有渠道一致；
- 密钥/Webhook 用 DPAPI 保存，不进入日志。

### 7.2 VS Code / Cursor 状态栏

- 状态栏显示当前等待数、最近一次运行状态；
- 点击打开 AgentBell 通知中心；
- 不嵌入 WebView，不复制通知 UI；
- 扩展不可用时不影响主程序；
- 作为独立扩展包维护，版本与主程序解耦。

### 7.3 验收

- 四个渠道发送成功/失败/超时测试；
- 外部渠道无密钥、无完整会话；
- 扩展在无 AgentBell 运行时优雅降级；
- 全量测试与隔离冒烟通过。

## 8. 2.18+：多机只读聚合

仅在 2.14–2.17 稳定、用户明确要求后启动：

- 可选自托管中继，聚合多台机器的只读通知流；
- 不做账号体系、云端托管、团队管理后台；
- 默认关闭，显式配置；
- 先做安全评审，再排期。

## 9. cc-switch 共存策略

1. 不读取 cc-switch 内部数据库或私有存储；其供应商数据没有稳定公开协议。
2. 只读取 Agent 自己的配置文件，且只读白名单字段。
3. Claude / Codex / Gemini 首版不写全局配置，天然不与 cc-switch 冲突。
4. Grok 首版不写 `~/.grok/config.toml`；如后续做全局切换，必须：
   - 默认关闭；
   - 写入前备份；
   - 原子替换 + 文件锁；
   - 检测 cc-switch 是否在管理同一文件并提示；
   - 提供一键撤销。
5. 官网 FAQ 明确写：AgentBell 不是 cc-switch 替代品，可同时使用；cc-switch 管全局切换与代理，AgentBell 管每次启动与提醒。
6. 不在 AgentBell 中托管 cc-switch 的 API Key，也不做代理转发。

## 10. 官网与海报

### 10.1 2.14.0 官网

文案主线：**先看清当前用的是谁。**

新增：

- 四 Agent 兼容矩阵：

| Agent | 等待检测 | 配置档案 | 只读动作 |
| --- | --- | --- | --- |
| Claude Code | 显式 Hook + 本地推断 | 只读显示，2.15 启动注入 | 会话 / 时间线 / 回到终端 |
| Codex | 完成 Hook；等待权限按实现情况标注 | 只读显示，2.15 启动注入 | 会话 / 时间线 / 回到终端 |
| Gemini CLI | 显式 Hook | 只读显示，2.15 启动注入 | 会话 / 时间线 / 回到终端 |
| Grok Build | 显式 Hook | 只读显示；切换跳转 cc-switch | 会话 / 时间线 / 回到终端 |

- FAQ：`和 cc-switch 会冲突吗？`
  - 默认不写全局配置；
  - 不读取 cc-switch 内部数据；
  - Grok 全局切换需显式开启并备份；
  - 可同时使用，互不替代。
- 安全说明：
  - 密钥只在本机，DPAPI 加密；
  - 密钥不进日志、通知、外部渠道；
  - 不做代理、不上传会话；
  - 不自动批准权限。

### 10.2 2.15.0 官网

文案主线：**供应商跟着项目走，不再全局切来切去。**

新增：

- 启动档案说明与截图；
- 同一 Agent 双档案并行示例；
- 更新兼容矩阵中的“启动注入”列；
- 保留 2.14 的安全与共存 FAQ。

### 10.3 海报

沿用现有 `agentbell-promo/posters/` 的 HTML + Playwright + 本机 Chrome 渲染流程，输出：

- 1080×1440 站点版；
- 2160×2880 交付版；
- 900×1200 站点缩略图。

概念：

1. **2.14《一个铃，四条终端》**：浅色编辑风；四张终端卡片分别显示权限等待、提问、限流、完成；中间一枚铃；强调“四个 Agent，一个提醒入口”。
2. **2.15《供应商跟着项目走》**：深色 UI 风；两个项目文件夹各自挂着供应商标签，终端并行运行；强调“不用全局切来切去”。

要求：

- 继续使用 Smiley Sans / 现有品牌色；
- 不出现真实 API Key、真实账号、真实内部地址；
- 发布前检查中英文、移动端、暗色模式、图片加载与横向溢出；
- 官网海报区、缓存版本号、缩略图尺寸同步更新；
- 官网发布必须等用户明确批准。

## 11. 测试与验收总表

| 层 | 内容 |
| --- | --- |
| 单元 | Hook 合并/撤销、事件映射、四个解析器、DPAPI、规则、档案 CRUD、参数构造 |
| API | `provider` 字段、旧客户端兼容、非法值、长度限制 |
| 集成 | 临时 HOME 下安装 Hook、模拟事件、去重、恢复、撤销 |
| UI | 启动器徽标、档案选择、预览 diff、错误提示、密钥掩码 |
| 安全 | 日志无密钥、argv 无密钥、无 `shell=True`、路径不逃逸、只写白名单配置 |
| 性能 | 配置读取 < 20 ms；Hook 端到端 < 2 s；8 个会话扫描不回归 |
| 冒烟 | 独立端口 8794/8795/8796，独立实例 smoke26/27/28，独立配置与数据库 |
| 回归 | 2.13.0 全量 348 项为基线，新增测试不得降低覆盖率与稳定性 |

每个版本完成定义：

- 新功能默认配置可用，关闭开关后行为与 2.13.0 一致；
- 全量测试通过；
- 隔离冒烟通过，未占用生产 `8765`，未重启生产；
- README、system-architecture、config.example、官网文案同步；
- 提交验收记录，等待用户确认后再进入下一版本；
- 发布 tag / Release / 官网更新 / 生产切换均需单独批准。

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Codex 没有权限等待 Hook | 首版明确标注“部分接入”；用会话推断补齐；不承诺四 Agent 完全等价 |
| 各 Agent Hook 事件随版本变化 | 开始时做能力探测；适配器独立版本；失败只降级不崩溃 |
| 写 Hook 配置破坏用户设置 | 预览、备份、原子替换、文件锁、撤销、冲突提示 |
| 密钥进入日志/命令行 | DPAPI、环境变量、argv 白名单、测试快照扫描 |
| cc-switch 与 AgentBell 互相覆盖 | 首版不写全局配置；Grok 全局切换默认关闭并提示冲突 |
| Python 3.10 无 tomllib | 引入 `tomli`，打包与源码行为一致 |
| PowerShell Hook 启动慢 | 实测；超过 500 ms 再评估独立 Hook exe |
| 供应商地址/模型格式变化 | 档案用户自定义；不做硬编码供应商目录；连接测试可选 |
| 官网/海报过度承诺 | 兼容矩阵按实际能力标注“部分/预研/只读” |

## 13. 待决策项

1. Hook 辅助程序首版用 PowerShell 还是独立 `AgentBellHook.exe`（建议 PowerShell）。
2. Codex 等待权限是否投入会话推断（建议先做能力探测，再决定）。
3. Grok 全局切换是否进入 2.15.x（建议默认不做，用户明确要求再做）。
4. 档案存储用 `config.json` 还是 SQLite（建议首版 config，档案多再迁移）。
5. 项目绑定是否首版就做自动按 cwd 推断（建议手动 + 记住上次，自动后置）。
6. 官网 `develop-cc-site` 分支的合并与发布时间（发布必须批准）。

## 14. 开始执行时的任务清单

- [ ] 用户确认本执行文档范围与版本顺序。
- [ ] 从 `develop` 创建 `develop-cc`。
- [ ] 记录基线：全量测试数量、当前 spec、生产端口未占用。
- [ ] 2.14 M1：四 Agent Hook 能力探测与接入器骨架。
- [ ] 2.14 M2：Hook 合并/备份/撤销/测试事件。
- [ ] 2.14 M3：四 Agent 供应商只读解析与 UI 徽标。
- [ ] 2.14 M4：`provider` 字段、规则、通知卡片、时间线。
- [ ] 2.14 M5：测试、文档、隔离冒烟、`AgentBell26.spec`。
- [ ] 2.14 M6：官网 2.14 文案、兼容矩阵、FAQ、安全说明、海报 A（待批准发布）。
- [ ] 2.15 M1：档案模型、DPAPI、CRUD、项目绑定。
- [ ] 2.15 M2：Claude/Codex/Gemini 启动注入；Grok 只读跳转。
- [ ] 2.15 M3：通知/时间线/统计显示档案；规则示例。
- [ ] 2.15 M4：测试、文档、隔离冒烟、`AgentBell27.spec`。
- [ ] 2.15 M5：官网 2.15 文案、海报 B（待批准发布）。
- [ ] 2.16：Doctor + 项目视图/摘要。
- [ ] 2.17：渠道 + VS Code/Cursor。
- [ ] 2.18+：多机只读聚合，单独批准。

## 15. 完成定义

本轮开发的完成不是“代码写完”，而是：

1. 2.14 与 2.15 的功能、测试、文档、官网、海报全部闭环；
2. 所有写入行为都有预览、备份、撤销；
3. 密钥不进入日志、命令行、通知和外部渠道；
4. Claude / Codex / Gemini 首版不写全局配置；
5. Grok 明确标注只读与限制；
6. 生产实例未被未授权重启；
7. 每个版本都有验收记录，合并、发布、官网更新均经用户确认。

---

**当前状态：文档已就绪，等待用户通知后从 `develop-cc` 开始执行。**

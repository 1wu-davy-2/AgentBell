# AgentBell

一个只做提醒的本地桌面工具：AI Agent 每轮任务结束后调用本机 HTTP 接口，桌面右上角立刻弹出置顶提醒：

> 上一轮【生成竞品分析报告】已完成，请查看

2.0 在原有弹窗基础上补齐了「少打扰、可闭环、能配置、可追溯」：优先级、免打扰、全屏/会议抑制、聚合摘要、待确认与稍后提醒、通知卡片动作、规则与外部渠道、SQLite 历史与统计。

2.1 增加弹窗外观与展示方式（四套皮肤、右侧卡片 / 居中确认 / 全屏遮挡三种模式）、锁屏与息屏期间不丢提醒、Agent 会话扫描页，并修复设置页在较小窗口下内容被裁切的问题。

2.2 让 `overlay` 真正铺满整块屏幕（覆盖任务栏），支持自定义全屏背景图、在设置里一键「测试」预览；双击启动后默认自动打开通知中心，并带淡入上浮动画，启动状态一眼可见。仍然没有 Web 页面，界面全部是 PySide6 原生窗口。

## 特性

- 只监听 `127.0.0.1:8765`（可在 `config.json` 改端口），不暴露到局域网。
- 弹窗置顶、不抢键盘焦点，打字不会被打断。
- 状态：成功 / 失败 / 取消 / 进行中；进行中通知可带 0–100 进度并在原卡片更新。
- 优先级：`low` / `normal` / `high` / `critical`；紧急通知常驻，必须点「知道了」才消失。
- 弹窗外观：`midnight` 午夜蓝 / `light` 晨光白 / `ocean` 深海青 / `amber` 琥珀暖四套皮肤，可按全局配置、规则或单条通知指定。
- 弹窗模式：`corner` 右侧小卡片、`center` 居中弹窗（必须确认）、`overlay` 全屏遮挡；全屏模式真正铺满整块屏幕并覆盖任务栏，可搭配自定义背景图。同一时刻只显示一种弹窗，避免卡片与全屏层互相干扰。
- 全屏背景图：`overlay` 支持 PNG / JPG / BMP / WebP，自动等比裁剪铺满并叠加半透明压暗层；留空或图片失效时回落到内置渐变。
- 效果预览：偏好设置底部「测试」按钮，按当前选择的模式、皮肤与背景图立即弹出一条预览，不写入历史、不影响真实通知。
- 启动反馈：默认双击启动后自动打开通知中心（可在偏好设置关闭），窗口以淡入 + 上浮动画出现。
- 锁屏保护：锁屏 / 息屏 / 屏保时暂停倒计时并暂缓新弹窗，解锁后补发；默认开启，可在偏好设置关闭。
- 打扰控制：成功可只进通知中心；失败与高优先级弹窗；免打扰时段；全屏/会议程序前台时延后，结束后补发。
- 冷却与聚合：短时间连续弹窗会自动合并成一条摘要，避免刷屏。
- 去重更新：相同 `dedupe_key` 原地更新同一张卡片，适合长任务的进度推送。
- 闭环处理：`require_ack` 待确认、5/15/30 分钟稍后提醒、未读升级（重新弹出 + 托盘闪烁 + 提示音）。
- 卡片动作：打开链接、复制文本、重试回调、打开本地文件、打开通知中心。
- 规则引擎：按来源 / 标题 / 状态自动设置优先级、静音、待确认、免打扰例外、弹窗外观、外部渠道。
- 模板与声音：四种状态的弹窗文案、五类 WAV 提示音均可配置。
- 外部渠道：企业微信、飞书、Telegram、Bark、ntfy、通用 Webhook；可按“离开电脑”或规则触发，失败只记日志，不影响主流程。
- Agent 会话扫描：只读扫描本机 Claude Code / Qoder 的会话元数据，按项目分组展示，支持搜索与打开目录，不读取对话内容。
- 可选 SQLite 历史：通知中心支持搜索、状态筛选、成功率 / 平均耗时 / 待确认统计和 7 天趋势图。
- 全局快捷键（默认 `Ctrl+Alt+A`）打开通知中心；托盘显示未读数。
- 常驻托盘、单实例启动、可复制 Agent 接入指令、滚动日志、PyInstaller 单文件打包。

## 目录结构

```text
agentbell/
├─ agentbell/
│  ├─ __init__.py         版本号
│  ├─ __main__.py         python -m agentbell 入口
│  ├─ main.py             启动流程、配置/端口错误提示
│  ├─ app.py              调度层：弹窗节奏、延时队列、确认/稍后/升级、动作、渠道
│  ├─ api.py              FastAPI 路由、鉴权、字段校验、去重写入
│  ├─ server.py           环回监听、uvicorn 线程
│  ├─ config.py           config.json 读写与校验
│  ├─ models.py           Notification 数据模型、模板、链接/路径白名单
│  ├─ policy.py           优先级、免打扰、全屏/会议/锁屏、规则与渠道决策
│  ├─ presence.py         Windows 空闲时间、前台全屏、会议进程、锁屏/息屏检测
│  ├─ agent_sessions.py   Claude Code / Qoder 会话元数据只读扫描
│  ├─ channels.py         外部渠道后台投递线程
│  ├─ hotkey.py           全局快捷键（RegisterHotKey）
│  ├─ storage.py          SQLite 历史、搜索与统计
│  ├─ store.py            线程安全通知历史、去重索引
│  ├─ integration.py      Agent 接入指令生成（复制到剪贴板）
│  ├─ single_instance.py  QLockFile 单实例锁 + QLocalServer 唤醒通道
│  ├─ log.py              滚动日志、异常钩子
│  ├─ paths.py            源码/打包后的路径解析
│  ├─ autostart.py        Windows/macOS/Linux 开机自启
│  └─ ui/
│     ├─ icons.py         程序图标、状态图标
│     ├─ window.py        cc-switch 风格通知中心、搜索、统计、Agent 会话页
│     ├─ settings.py      偏好设置对话框
│     ├─ toast.py         置顶弹窗、皮肤/模式、倒计时、堆叠调度、聚合摘要
│     └─ tray.py          托盘菜单、未读与最近通知
├─ tests/                 API、策略、存储、配置、会话扫描、窗口/弹窗与单实例测试
├─ assets/agentbell.ico   打包用图标
├─ config.json            当前配置
├─ config.example.json    配置示例
├─ requirements.txt       运行依赖
├─ requirements-dev.txt   测试/打包依赖
├─ run.py                 源码启动入口
├─ AgentBell.spec         PyInstaller 配置（AgentBell.exe）
├─ AgentBell2.spec        PyInstaller 配置（AgentBell-2.exe，可与 1.x 并存）
├─ AgentBell3.spec        PyInstaller 配置（AgentBell-3.exe，2.1 功能）
├─ AgentBell4.spec        PyInstaller 配置（AgentBell-4.exe，2.2 功能）
└─ README.md
```

## 环境要求

- Python 3.10+
- Windows 10/11（全屏检测、会议进程检测、提示音、全局快捷键仅 Windows 完整可用）；macOS/Linux 可运行基础弹窗与通知中心
- 依赖：FastAPI、uvicorn、Pydantic v2、PySide6

## 快速开始（源码）

```bash
cd agentbell

# Windows
py -3 -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

启动后托盘出现蓝紫色铃铛图标，通知中心自动弹出（淡入 + 上浮动画），日志里会看到：

```text
AgentBell 已就绪：http://127.0.0.1:8765（X-Token 鉴权已开启）
```

关闭窗口后程序继续驻留托盘；右键托盘图标选择「打开通知中心」即可再次查看记录，按 `Ctrl+Alt+A` 也可以打开。重复启动不会产生第二份服务，只会让已有实例打开通知中心。

也可以用 `python -m agentbell` 启动。

> Windows 下想双击免黑框运行源码，可把 `run.py` 的打开方式设为 `pythonw.exe`；更推荐直接使用打包后的 exe。

## 配置

首次运行若目录下没有 `config.json`，会自动生成一份完整默认配置（`token` 为空，即关闭鉴权）。本仓库自带的 `config.json` 使用示例 token `your-token`。

```json
{
  "port": 8765,
  "token": "your-token",
  "auto_close_seconds": 30,
  "autostart": false,
  "open_center_on_start": true,
  "instance_name": "",
  "history": { "enabled": true, "limit": 1000, "path": "" },
  "quiet_hours": {
    "enabled": false,
    "start": "22:00",
    "end": "08:00",
    "allow_critical": true
  },
  "suppress_fullscreen": true,
  "meeting_processes": ["zoom.exe", "teams.exe", "wemeetapp.exe", "webexmta.exe"],
  "success_popup": true,
  "require_ack_by_default": false,
  "popup_cooldown_seconds": 15,
  "popup_mode": "corner",
  "popup_skin": "midnight",
  "overlay_image": "",
  "hold_when_locked": true,
  "agent_sessions": {
    "enabled": true,
    "scan_interval_seconds": 120,
    "max_sessions": 80
  },
  "digest": { "enabled": true, "threshold": 4, "window_seconds": 60 },
  "escalation": {
    "unread_seconds": 0,
    "max_times": 2,
    "flash_tray": true,
    "sound": true
  },
  "hotkey": "Ctrl+Alt+A",
  "sounds": {
    "succeeded": "",
    "failed": "",
    "canceled": "",
    "running": "",
    "critical": ""
  },
  "templates": {
    "succeeded": "上一轮【{title}】已完成，请查看",
    "failed": "上一轮【{title}】执行失败",
    "canceled": "上一轮【{title}】已取消",
    "running": "上一轮【{title}】进行中"
  },
  "rules": [],
  "channels": [],
  "away_idle_seconds": 300,
  "allow_local_paths": false,
  "presence_poll_seconds": 5
}
```

### 基础

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `port` | 整数 | `8765` | 仅绑定 `127.0.0.1`，范围 1–65535 |
| `token` | 字符串 | `""` | 非空时，`POST /notify` 必须携带相同的 `X-Token`；为空则关闭鉴权 |
| `auto_close_seconds` | 整数 | `30` | 弹窗自动关闭秒数，范围 0–3600；`0` 表示不自动关闭 |
| `autostart` | 布尔 | `false` | 是否随当前用户登录启动；修改后下次启动生效 |
| `open_center_on_start` | 布尔 | `true` | 双击启动后自动打开通知中心，并播放淡入上浮动画；再次启动已有实例时也会打开 |
| `instance_name` | 字符串 | `""` | 单实例名称后缀，便于并行运行多份做调试 |
| `hotkey` | 字符串 | `Ctrl+Alt+A` | 打开通知中心的全局快捷键；空字符串关闭；支持 `Ctrl/Alt/Shift/Win` 加字母、数字、F1–F24 等 |
| `away_idle_seconds` | 整数 | `300` | 无键鼠操作超过该秒数视为离开；`0` 关闭离开判定 |
| `presence_poll_seconds` | 整数 | `5` | 空闲/全屏/会议状态轮询间隔，范围 1–60 |
| `allow_local_paths` | 布尔 | `false` | 是否允许通知携带 `path` 动作打开本地文件 |

> 修改 `port` 或 `token` 后需要重启 AgentBell；在设置对话框里保存端口也只会在下次启动生效。

### 打扰控制

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `success_popup` | 布尔 | `true` | `false` 时普通成功通知只进通知中心；`high` / `critical` 成功仍弹窗 |
| `require_ack_by_default` | 布尔 | `false` | 所有弹窗默认需要点「知道了」确认 |
| `quiet_hours.enabled` | 布尔 | `false` | 开启免打扰时段 |
| `quiet_hours.start` / `end` | `HH:MM` | `22:00` / `08:00` | 支持跨午夜；二者相同表示全天免打扰 |
| `quiet_hours.allow_critical` | 布尔 | `true` | 紧急通知是否穿透免打扰 |
| `suppress_fullscreen` | 布尔 | `true` | 前台全屏时暂停弹窗 |
| `hold_when_locked` | 布尔 | `true` | 锁屏 / 息屏 / 屏保期间暂停倒计时并暂缓新弹窗，解锁后补发 |
| `meeting_processes` | 字符串数组 | Zoom/Teams/腾讯会议/Webex | 这些进程在前台时不弹窗；设为空数组关闭会议检测 |
| `popup_cooldown_seconds` | 整数 | `15` | 非紧急弹窗的最小间隔，冷却期内的通知进入聚合缓冲 |
| `digest.enabled` | 布尔 | `true` | 是否启用聚合摘要 |
| `digest.threshold` | 整数 | `4` | 窗口内达到该数量后合并弹窗 |
| `digest.window_seconds` | 整数 | `60` | 聚合统计窗口 |
| `escalation.unread_seconds` | 整数 | `0` | 待确认通知多久未处理就升级；`0` 关闭升级 |
| `escalation.max_times` | 整数 | `2` | 最多重复提醒次数 |
| `escalation.flash_tray` | 布尔 | `true` | 升级时闪烁托盘图标 |
| `escalation.sound` | 布尔 | `true` | 升级时播放提示音 |

### 弹窗外观

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `popup_mode` | 字符串 | `corner` | `corner` 右侧小卡片 / `center` 居中确认弹窗 / `overlay` 全屏遮挡弹窗 |
| `popup_skin` | 字符串 | `midnight` | `midnight` 午夜蓝 / `light` 晨光白 / `ocean` 深海青 / `amber` 琥珀暖；通知卡片与通知中心共用配色 |
| `overlay_image` | 字符串 | `""` | `overlay` 模式的自定义背景图路径，支持 PNG / JPG / BMP / WebP；留空使用内置渐变；图片无法加载时自动回落 |

- `corner`：出现在主屏右侧，多张卡片自上而下堆叠，保留原有的不抢焦点行为。
- `center`：屏幕中央单张弹窗，必须点「知道了」（或稍后提醒）才消失；该模式会强制 `require_ack`。
- `overlay`：真正铺满整块屏幕（含任务栏区域）的遮挡层 + 居中卡片，适合必须马上看到的提醒；点击遮罩空白处可关闭，待确认时点击会轻微脉冲提示。
- `overlay_image`：图片按屏幕比例等比裁剪铺满，并叠加半透明黑色压暗层，保证卡片文字清晰；推荐使用与屏幕同比例的高分辨率图片。设置里可用「选择图片 / 清除」维护，并点击底部「测试」立即预览。
- 三种模式互斥：同一时刻只显示一种模式的弹窗，其余通知继续排队；进行中通知更新时保持原模式与原尺寸。
- 单条通知可用请求字段 `popup_mode` / `popup_skin` 覆盖；规则里也可以设置，优先级为「规则 > 单条请求 > 全局配置」。

### Agent 会话

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `agent_sessions.enabled` | 布尔 | `true` | 是否在通知中心显示「Agent 会话」页并定时扫描 |
| `agent_sessions.scan_interval_seconds` | 整数 | `120` | 后台扫描间隔，范围 30–3600 秒；手动刷新不受限制 |
| `agent_sessions.max_sessions` | 整数 | `80` | 最多展示的会话数，范围 10–500 |

扫描范围固定为本机只读目录：

- Claude Code：`~/.claude/projects/*/*.jsonl`
- Qoder：`~/.qoder/projects/*/*/state.json`

只解析项目路径、会话 ID、创建/更新时间、文件大小和记录条数，不读取或展示对话正文；没有对应目录时页面显示空状态。每轮扫描结果按更新时间倒序，通知中心里可按标题/项目搜索，并支持打开项目目录或复制路径。

### 历史

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `history.enabled` | 布尔 | `true` | 开启 SQLite 历史；关闭后仅保留内存记录 |
| `history.limit` | 整数 | `1000` | 最多保留条数，启动时自动裁剪 |
| `history.path` | 字符串 | `""` | 数据库路径；空则使用 `config.json` 同目录的 `agentbell.db`，相对路径按配置目录解析 |

### 提示声音与模板

- `sounds`：键为 `succeeded` / `failed` / `canceled` / `running` / `critical`，值为 WAV 绝对路径，空表示静音；紧急通知优先使用 `critical`。仅 Windows 通过 `winsound` 播放。
- `templates`：四种状态的弹窗标题模板，必须包含 `{title}` 占位符，例如 `"上一轮【{title}】已完成，请查看"`。

### 规则 `rules`

规则按顺序全部匹配、后面的规则覆盖前面的标量设置，`channels` 会累加。最多 50 条。

```json
{
  "rules": [
    {
      "name": "部署失败必须确认",
      "source": "deploy-*",
      "status": "failed",
      "priority": "critical",
      "require_ack": true,
      "bypass_quiet_hours": true,
      "channels": ["wecom"]
    },
    {
      "name": "数据抓取成功只记录",
      "title_contains": "抓取",
      "status": "succeeded",
      "silent": true
    }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `name` | 规则名，用于日志和卡片标记 |
| `source` | 来源匹配，支持 `*`、`?` 通配符；默认 `*` |
| `title_contains` | 标题包含的文本，不区分大小写 |
| `status` | 仅匹配指定状态 |
| `priority` | 覆盖优先级 |
| `silent` | 是否只进通知中心 |
| `require_ack` | 是否强制确认 |
| `auto_close_seconds` | 覆盖自动关闭时间 |
| `popup_mode` | 覆盖弹窗模式（`corner` / `center` / `overlay`） |
| `popup_skin` | 覆盖弹窗皮肤（`midnight` / `light` / `ocean` / `amber`） |
| `bypass_quiet_hours` | 是否忽略免打扰 |
| `channels` | 追加外部渠道类型（`webhook` / `feishu` / `wecom` / `ntfy` / `bark` / `telegram`） |

### 外部渠道 `channels`

最多 20 个。渠道投递在后台线程执行，失败只写日志，不影响弹窗和 HTTP 响应。

```json
{
  "channels": [
    {
      "type": "wecom",
      "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
      "when_away": true,
      "min_priority": "high"
    },
    {
      "type": "ntfy",
      "topic": "agentbell",
      "url": "https://ntfy.sh",
      "when_away": false,
      "min_priority": "normal"
    },
    {
      "type": "telegram",
      "token": "123456:bot-token",
      "chat_id": "123456789",
      "when_away": true,
      "min_priority": "high"
    }
  ]
}
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `type` | — | `webhook` / `feishu` / `wecom` / `ntfy` / `bark` / `telegram` |
| `enabled` | `true` | 是否启用 |
| `when_away` | `true` | 仅在离开电脑（空闲达到 `away_idle_seconds`）时发送；`false` 表示始终发送 |
| `min_priority` | `high` | 达到该优先级才发送 |
| `url` | — | webhook/feishu/wecom 必填；ntfy 默认 `https://ntfy.sh`；bark 默认 `https://api.day.app` |
| `topic` | — | ntfy 必填 |
| `device_key` | — | Bark 必填 |
| `token` / `chat_id` | — | Telegram bot token 与目标会话 |
| `headers` | `{}` | 自定义请求头（值不能包含换行） |

选择逻辑：渠道启用 → 通知优先级不低于 `min_priority` → `when_away` 满足 → 若通知或规则限定了渠道类型则只投递这些类型。`running` 通知不投递外部渠道；同一 `dedupe_key` 的更新只有失败/取消会再次投递。

## 接口

### `GET /health`

无需鉴权，用于探活：

```bash
curl http://127.0.0.1:8765/health
```

```json
{"ok":true,"app":"AgentBell","version":"2.2.0","auth":true}
```

AgentBell 只提供 `GET /health` 和 `POST /notify` 两个接口，不提供 Web 页面或 HTTP 通知列表；记录显示在应用内的原生通知中心里。

### `POST /notify`

请求头：

```text
Content-Type: application/json
X-Token: your-token        # 仅当 config.token 非空时必需
```

请求体：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `title` | 字符串 | `未命名任务` | 任务名，最长 200 字符 |
| `status` | 字符串 | `succeeded` | `succeeded` / `failed` / `canceled` / `running` |
| `summary` | 字符串 | `""` | 结果摘要，最长 4000 字符 |
| `duration` | 字符串 | `""` | 耗时文本，如 `8m30s`，最长 64 字符 |
| `link` | 字符串 | `null` | 仅接受 `http` / `https`，其他协议会被忽略 |
| `error` | 字符串 | `null` | 仅 `status=failed` 时展示，最长 2000 字符 |
| `priority` | 字符串 | 按状态推断 | `low` / `normal` / `high` / `critical`；失败默认 `high`，进行中默认 `low`，成功/取消默认 `normal` |
| `source` | 字符串 | `""` | 来源标识（Agent 名、任务类型），最长 100 字符，参与规则匹配与搜索 |
| `dedupe_key` | 字符串 | `null` | 去重键，最长 200 字符；相同键会更新已有卡片并累加次数 |
| `require_ack` | 布尔 | `false` | 需要用户点「知道了」；此类弹窗不自动关闭，并出现稍后提醒菜单 |
| `silent` | 布尔 | `false` | 只记录到通知中心，不弹窗 |
| `progress` | 整数 | `null` | `0–100`，仅 `status=running` 时生效，用于进度条 |
| `actions` | 数组 | `[]` | 最多 4 个动作按钮，见下表 |
| `bypass_quiet_hours` | 布尔 | `false` | 本条忽略免打扰时段 |
| `popup_mode` | 字符串 | `null` | 本条弹窗模式：`corner` / `center` / `overlay`；为空用全局配置 |
| `popup_skin` | 字符串 | `null` | 本条弹窗皮肤：`midnight` / `light` / `ocean` / `amber`；为空用全局配置 |
| `auto_close_seconds` | 整数 | `null` | 覆盖本条自动关闭秒数（0–3600）；待确认/进行中仍强制不自动关闭 |
| `expires_in` | 整数 | `null` | 有效秒数（1–604800），过期后不再弹出或补发 |
| `channel_types` | 字符串数组 | `[]` | 限定只投递到这些外部渠道类型，最多 10 个 |

`actions` 每项：

| 字段 | 说明 |
| --- | --- |
| `kind` | `open` / `copy` / `retry` / `path` / `center` |
| `label` | 按钮文字，最长 40 字符；为空时用默认文案 |
| `value` | `open` 为 http(s) 链接（为空时用通知的 `link`）；`copy` 为文本；`retry` 仅接受本机 http 回调地址（`127.0.0.1` / `localhost` / `::1`）；`path` 为本地绝对路径，且需 `allow_local_paths=true` |

未知字段会被忽略；`null` 会回落到默认值；字符串首尾及连续空白会被压缩。

成功响应（HTTP 202）：

```json
{
  "ok": true,
  "id": "391cd8903658",
  "queued": true,
  "updated": false,
  "priority": "high",
  "require_ack": false,
  "occurrence": 1,
  "popup_mode": "corner",
  "popup_skin": "midnight"
}
```

`updated` 表示命中了已有 `dedupe_key` 并原地更新；`occurrence` 是该卡片累计更新次数。

错误响应：

| 状态码 | 场景 |
| --- | --- |
| `400` | 空请求体、JSON 格式错误、编码无法识别 |
| `401` | `X-Token` 缺失或不匹配 |
| `413` | 请求体超过 1 MB |
| `422` | 字段类型/长度不合法，如未知 `status` |
| `503` | 通知队列已满（200 条），历史仍会记录该通知 |

请求体会先按 UTF-8（含 BOM）解码，失败后兼容按 GB18030 解码，以适配 Windows 命令行下 curl 发送中文的情况。

## 提醒行为说明

### 何时弹窗

1. `silent=true`：不弹窗，只进通知中心。
2. `running`：仅 `high` / `critical` 弹窗，且不自动关闭；建议配合 `dedupe_key` 更新进度。
3. `succeeded`：`success_popup=true` 时弹窗；设为 `false` 后只有高优先级才弹。
4. `canceled`：默认弹窗；设为 `low` 且未要求确认时不弹。
5. `failed`：弹窗（`silent` 除外）。
6. `critical`：始终需要确认，不自动关闭，并跳过冷却与聚合，直接弹出。
7. 免打扰、全屏、会议进程会在弹窗之前拦截；被拦截的通知进入延时队列，条件解除后补发，多条会合并成摘要。过期（`expires_in`）的通知直接丢弃。
8. 普通通知在冷却期或短时间内达到聚合阈值时进入摘要缓冲；缓冲只有 1 条时仍按普通弹窗显示。

### 弹窗模式与皮肤

- `corner`（默认）：主屏右侧小卡片，不抢焦点、逐条堆叠，保留冷却/聚合/暂停倒计时等行为。
- `center`：居中单张弹窗，强制确认，不自动关闭；多个待确认通知按队列依次展示。点击「知道了」或稍后提醒后释放给下一条。
- `overlay`：真正铺满整块屏幕（覆盖任务栏）的不透明遮挡层，居中展示卡片；使用自定义背景图时等比裁剪铺满并叠加压暗层，未设置或加载失败时使用皮肤渐变。点击遮罩空白处即关闭，若该通知必须确认则改为脉冲提示，仍需点「知道了」。
- 同一条通知更新（`dedupe_key`）时不会切换已显示的皮肤/模式；新推送可用 `popup_mode` / `popup_skin` 覆盖全局设置，规则命中时以规则为准。
- 四套皮肤同时作用于通知卡片与通知中心，可在「偏好设置 → 弹窗外观」中选择。

### 锁屏与息屏

- `hold_when_locked=true`（默认）时，Windows 锁屏、息屏、屏保或切换输入桌面都视为锁定：已显示的倒计时暂停，新通知进入延时队列（日志记为「通知延后提醒：locked」）。
- 解锁后恢复所有卡片倒计时，并按原队列补发延期通知；多条同样会合并成摘要。
- 该检测依赖 Windows 会话状态；其他平台会退回「屏保/显示器关闭」判断，检测不到时按未锁定处理。
- 关闭该选项后行为与旧版一致：锁屏期间仍会弹窗并正常倒计时，但用户解锁后可能已经自动消失。

### 去重与进度

- 相同 `dedupe_key` 的推送复用同一张卡片和同一条历史记录，`occurrence` 累加，弹窗内容原地刷新。
- 合并时保留原 `id` 与首次接收时间，摘要/耗时/链接/错误/动作取新值或回落到旧值，优先级取较高者，确认状态会重置。
- 外部渠道只会在失败/取消的更新时重发，避免进度刷新刷屏。

### 确认、稍后与升级

- `require_ack=true`、`require_ack_by_default=true` 或 `critical` 会要求确认；确认按钮同时出现在弹窗和通知中心卡片上。
- 待确认通知可以「稍后提醒」5 / 15 / 30 分钟；到点后重新弹出并播放提示音。
- 配置 `escalation.unread_seconds > 0` 后，未确认通知会按间隔重复提醒，最多 `max_times` 次，可同时闪烁托盘和播放提示音；点击「知道了」立即停止。
- 进行中通知不自动关闭，更新为成功/失败后恢复普通行为。

### 全屏、会议与离开

- 全屏检测基于前台窗口矩形是否覆盖所在显示器，桌面、任务栏、壁纸窗口不算全屏。
- 前台进程命中 `meeting_processes` 时同样延后；默认包含 Zoom、Teams、腾讯会议、Webex。
- 延时队列每 30 秒复查一次，退出全屏、会议结束或解锁后立即补发；免打扰时段在结束时刻补发。
- `away_idle_seconds` 只影响外部渠道的 `when_away` 判断，不影响本地弹窗。

## 通知中心与统计

- 左侧筛选：全部 / 成功 / 失败 / 已取消 / 进行中；顶栏显示当前筛选数量与未读数。
- 搜索：标题、摘要、错误、来源；输入后 260ms 自动搜索，搜索状态下可一键清除。
- 卡片：状态、优先级、来源、`更新 ×N`、`待确认/已确认`、进度条、摘要、耗时、错误、动作按钮、重新弹出、确认、稍后提醒。
- 数据统计：总通知数、成功率（成功 / 已结束）、平均耗时（可解析的 `duration`）、待确认数，以及最近 7 天每日总量/失败量柱状图。
- 偏好设置：端口、token、自启、启动打开通知中心、自动关闭、冷却、成功弹窗、默认确认、快捷键、免打扰、全屏抑制、锁屏保留、弹窗模式与皮肤、全屏背景图、Agent 会话扫描、会议进程、离开判定、聚合、升级、模板、声音、规则与渠道 JSON。所有标签页均可滚动，小窗口下不会裁切内容。保存后立即应用可热更新的项并写回 `config.json`；端口、token 等监听相关配置需重启。
- 效果预览：设置对话框底部「测试」按钮按当前选择的模式、皮肤和背景图弹出一条预览。预览使用临时通知，不写入 SQLite 历史；`overlay` 预览会实际铺满屏幕，点「知道了」即可返回设置。
- Agent 会话页：左侧侧栏切换到「Agent 会话」，按项目分组显示本机会话的更新时间、记录条数与大小，支持搜索、手动刷新、打开项目目录、复制路径；数据只读，不进入通知历史。
- 关闭窗口只是隐藏到托盘，程序继续接收通知；`Ctrl+Alt+A` 可随时唤出。

## 托盘与弹窗行为

- 左键/右键托盘图标：菜单显示监听地址、鉴权状态、未读数、「打开通知中心」、「显示最近通知」、「退出」。
- 最近通知保留本次运行的最后 20 条，菜单展示最新 10 条；点击某条会重新弹出该通知。
- 再次启动 AgentBell 时，新进程会通知已有实例打开通知中心，然后自行退出，不会启动第二份 HTTP 服务。
- 双击启动后默认自动打开通知中心（`open_center_on_start=true`），窗口以 260ms 淡入 + 上浮动画出现；可在「偏好设置 → 通用」关闭。
- `corner` 模式弹窗显示在主屏右侧，逐条向下堆叠，最多 5 条，其余 FIFO 排队；`center` / `overlay` 为单张独占显示。
- 鼠标悬停在卡片上时倒计时暂停，移开后继续；锁屏期间所有倒计时都会暂停。
- 弹窗使用 `WS_EX_NOACTIVATE` / `WA_ShowWithoutActivating`，显示时不会抢走当前输入焦点。

## 日志

- 位置：源码运行在项目根目录 `logs/agentbell.log`；打包后位于 exe 同目录 `logs/agentbell.log`。
- 目录不可写时（例如放在 `Program Files`）自动退到系统临时目录：`%TEMP%\AgentBell\logs\`（macOS/Linux 为 `/tmp/AgentBell/logs/`）。
- 单个文件 2 MB，保留 3 个历史文件，UTF-8 编码。
- 记录：启动参数、配置路径、收到的通知、鉴权拒绝、字段校验失败、规则命中、延时/聚合/升级、渠道投递结果、弹窗显示/关闭原因、动作执行、异常堆栈。
- 不会记录 token 本身；标题和摘要会截断后写入。

## 开机自启

把 `config.json` 中的 `autostart` 改为 `true` 并重启 AgentBell：

- Windows：写入当前用户 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，名称为 `AgentBell`。
- macOS：写入 `~/Library/LaunchAgents/com.agentbell.app.plist`。
- Linux：写入 `$XDG_CONFIG_HOME/autostart/agentbell.desktop`（默认 `~/.config/autostart/`）。

改回 `false` 并重启即可移除。自启配置失败只记录警告，不会阻止程序启动。

## 用 curl 测试

在 `config.json` 的 token 为 `your-token` 时：

```bash
# 普通成功
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"生成竞品分析报告","status":"succeeded","summary":"已完成 12 页报告","duration":"8m30s","link":"https://example.com/report","source":"qoder"}'

# 长任务进度（重复推送同一个 dedupe_key）
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"批量导出 PDF","status":"running","progress":40,"dedupe_key":"export-pdf","source":"qoder"}'

# 失败并要求确认 + 重试按钮
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"爬取行情数据","status":"failed","error":"目标站点返回 403","priority":"high","require_ack":true,"actions":[{"kind":"retry","label":"重试","value":"http://127.0.0.1:9000/retry"}]}'
```

预期：桌面右上角出现对应弹窗；待确认通知不自动关闭，可点「知道了」或在菜单里选 5/15/30 分钟后提醒；通知中心能看到状态、来源、次数和动作按钮。

Windows 的 `curl.exe` 会把命令行字面量按当前代码页（通常是 GBK）发送。AgentBell 已做 GB18030 兼容；若仍遇到编码问题，推荐把 JSON 存成 UTF-8 文件：

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  --data-binary @payload.json
```

## 让 Agent 每轮自动推送（推荐）

1. 右键托盘图标，选择「打开通知中心」。
2. 点击窗口右上角的「复制 Agent 接入指令」按钮，按钮会变为「已复制接入指令」。
3. 把剪贴板内容直接粘贴给 Agent（Claude Code、Codex、Qoder 等），发送一次即可。

复制内容包含当前端口、当前 `X-Token`、请求头、全部字段说明、curl 示例，以及规则：**每一轮任务结束都必须推送一次通知，无论成功、失败还是取消**。同时说明了 `dedupe_key`、`progress`、`require_ack` 和 `actions` 的推荐用法。

> 修改 `config.json` 的端口或 token 后需要重启 AgentBell，并重新点击复制。复制动作会把 token 写入系统剪贴板，请勿在不受信任的环境粘贴。

## Agent 侧调用

### Python

```python
import time
import requests

BASE = "http://127.0.0.1:8765"
HEADERS = {"X-Token": "your-token"}

def run_task():
    started = time.monotonic()
    try:
        # ... 你的 Agent 任务 ...
        requests.post(
            f"{BASE}/notify",
            headers=HEADERS,
            json={
                "title": "生成竞品分析报告",
                "status": "succeeded",
                "summary": "已完成 12 页报告，包含 5 个竞品对比。",
                "duration": f"{time.monotonic() - started:.0f}s",
                "link": "https://example.com/report",
                "source": "qoder",
            },
            timeout=3,
        )
    except Exception as exc:
        requests.post(
            f"{BASE}/notify",
            headers=HEADERS,
            json={
                "title": "生成竞品分析报告",
                "status": "failed",
                "error": str(exc)[:2000],
                "duration": f"{time.monotonic() - started:.0f}s",
                "priority": "high",
                "require_ack": True,
                "source": "qoder",
            },
            timeout=3,
        )
        raise
```

### Shell 包装

```bash
notify_done() {
  local title="$1" status="$2" summary="${3:-}" link="${4:-}"
  curl -sS -X POST http://127.0.0.1:8765/notify \
    -H "Content-Type: application/json" \
    -H "X-Token: your-token" \
    --data-binary "$(python -c 'import json,sys; print(json.dumps({"title":sys.argv[1],"status":sys.argv[2],"summary":sys.argv[3],"link":sys.argv[4] or None}, ensure_ascii=False))' "$title" "$status" "$summary" "$link")" \
    >/dev/null || true
}

your-agent-command && notify_done "生成竞品分析报告" "succeeded" "已完成 12 页报告" "https://example.com/report" \
  || notify_done "生成竞品分析报告" "failed" "执行失败"
```

通知失败不应影响主任务：调用侧建议设置短超时并忽略通知本身的错误。

## 打包

PyInstaller 不能跨平台交叉编译，请在目标系统上分别打包。

### Windows

```bash
pip install -r requirements-dev.txt

# 1.x 名称：dist\AgentBell.exe
python -m PyInstaller --noconfirm --clean AgentBell.spec

# 2.x 名称：dist\AgentBell-2.exe（可与 1.x 同时安装/运行）
python -m PyInstaller --noconfirm --clean AgentBell2.spec

# 2.1 名称：dist\AgentBell-3.exe（包含弹窗皮肤/模式、锁屏保留、Agent 会话页）
python -m PyInstaller --noconfirm --clean AgentBell3.spec

# 2.2 名称：dist\AgentBell-4.exe（整屏遮挡、自定义背景图、测试预览、启动动画）
python -m PyInstaller --noconfirm --clean AgentBell4.spec
```

把 `config.json` 复制到 exe 旁边再运行：

```bash
copy config.json dist\config.json
dist\AgentBell-4.exe
```

> 新旧版本默认共用单实例锁：若托盘中已有 AgentBell（1.x / 2.x）在运行，双击 AgentBell-4 只会唤醒旧实例。切换版本前先从托盘退出旧版，再启动新 exe。

打包后 `config.json`、`logs/` 与 `agentbell.db` 都位于 exe 所在目录。单文件模式首次启动需要解压到临时目录，通常会有 1–3 秒延迟。

### macOS / Linux

仍可使用 spec，但需要把 `icon=` 换成对应平台的图标（macOS 用 `.icns`，Linux 可省略）。也可以直接执行：

```bash
pyinstaller --noconfirm --clean --onefile --windowed \
  --name AgentBell-4 \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.asyncio \
  --hidden-import uvicorn.protocols.http.h11_impl \
  --hidden-import uvicorn.lifespan.off \
  run.py
```

`uvicorn` 的 loop / HTTP 协议 / lifespan 实现是运行时按字符串导入的，必须显式加 `--hidden-import`，否则打包后启动 HTTP 服务会报模块找不到。通知中心与设置窗口全部使用 PySide6 原生控件，不需要打包 HTML 资源。

## 测试

```bash
pip install -r requirements-dev.txt

# Windows PowerShell
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest -q

# macOS / Linux / Git Bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

覆盖：鉴权与 401、字段默认值/空值/长度、非法状态、危险链接、GB18030 请求体、空/坏 JSON、超大请求体、队列满、去重合并、待确认与动作、规则匹配、免打扰/全屏/会议/锁屏决策、优先级弹窗策略、弹窗模式与皮肤、全屏自定义背景图与失效回落、渠道选择、配置校验、SQLite 存取/搜索/统计/裁剪、通知中心筛选/搜索/统计/设置/Agent 会话页、设置效果预览与清理、弹窗文案/按钮/去重更新/聚合、居中与全屏弹窗互斥、锁屏暂停、单实例唤醒、自动关闭与悬停暂停、启动自动打开与会话动画收尾。

## 常见问题

**端口被占用，弹窗提示启动失败**

程序启动时会同步绑定端口，占用时直接弹窗并退出。按提示执行：

```bash
netstat -ano | findstr :8765
```

关闭占用进程，或修改 `config.json` 的 `port` 后重启。不要改成 `0.0.0.0`：AgentBell 代码内固定只绑定 `127.0.0.1`。

**`401 {"ok":false,"error":"invalid token"}`**

`X-Token` 缺失或与 `config.json` 的 `token` 不一致。若不需要鉴权，把 `token` 设为空字符串并重启；本机使用仍建议保留随机 token。

**Windows 下 curl 中文报 400**

优先使用 UTF-8 文件 + `--data-binary @payload.json`。AgentBell 对 GB18030 有兼容解码，正常情况下直接内联中文也可用。

**没有托盘图标**

确认桌面环境支持系统托盘（部分精简 Linux 桌面默认没有）。托盘不可用时程序会弹窗提示并以退出码 3 退出。

**弹窗没有出现**

1. 访问 `GET /health` 确认服务在运行；
2. 查看 `logs/agentbell.log` 是否有「拒绝通知」「字段校验失败」「通知延后提醒」「通知进入聚合摘要」；
3. 检查是否开启免打扰、前台是否全屏、是否命中会议进程、是否正在锁屏或息屏（锁屏消息会等到解锁后补发）；
4. 检查通知中心：`silent=true` 或 `success_popup=false` 的成功通知只进中心；
5. 已达 5 条可见上限时新通知在排队；独占全屏游戏可能覆盖任何置顶窗口。

**双击启动后没看到页面？**

2.2 起默认 `open_center_on_start=true`，启动约 0.2 秒后自动打开通知中心。如果只看到托盘图标而没有窗口，检查该配置是否被改为 `false`；若托盘里已有实例，再次双击会唤醒已有实例并打开通知中心。

**全屏提醒没有铺满屏幕 / 背景图没显示？**

确认 `popup_mode` 为 `overlay`（或单条通知指定了 `popup_mode=overlay`）。全屏模式覆盖主屏整块屏幕，多显示器时其他屏幕不受影响；全屏独占游戏可能盖住任何置顶窗口。自定义背景图支持 PNG / JPG / BMP / WebP，路径失效时自动回落为皮肤渐变，可在「偏好设置 → 弹窗外观」里选择图片并点「测试」预览。

**待确认通知为什么一直不消失？**

`require_ack=true`、`require_ack_by_default=true` 或 `priority=critical` 的弹窗不自动关闭，必须点「知道了」；也可以在通知中心卡片上确认，或先「稍后提醒」。

**通知中心记录为什么重启后还在？**

2.0 起默认启用 SQLite 历史（`history.enabled=true`）。想恢复「退出即清空」，把该项设为 `false`，或删除 `agentbell.db`。

**Agent 会话页是空的？**

确认 `agent_sessions.enabled=true`，且本机存在 `~/.claude/projects` 或 `~/.qoder/projects`（Windows 为用户目录下的 `.claude` / `.qoder`）。扫描只读取会话元数据，不会读取对话内容；没有对应目录时显示空状态属于正常。可在页面右上角手动刷新，或在偏好设置里调整扫描间隔与最大条数。

**锁屏后通知为什么没弹出来？**

默认 `hold_when_locked=true`：锁屏、息屏、屏保期间通知会延后，解锁后再补发，避免解锁时消息已经自动消失。想恢复旧行为，在「偏好设置 → 提醒策略」关闭「锁屏时保留通知」。

**外部渠道没有收到消息？**

1. 检查渠道 `enabled`、`min_priority` 是否匹配；
2. `when_away=true` 需要先离开电脑达到 `away_idle_seconds`；
3. 查看日志中「外部渠道发送失败」的具体原因；
4. 渠道配置在设置对话框保存后立即生效，无需重启。

**全局快捷键没反应？**

可能被其他程序占用，日志会记录「注册全局快捷键失败」。在设置里换一个组合，或把 `hotkey` 设为空字符串关闭。

**重复双击会启动多个 AgentBell 吗？**

不会。第一个实例在系统临时目录持有单实例锁（`AgentBell-single-<用户摘要>.lock`）并监听同名本地通道；后续启动会让已有实例打开通知中心，然后以退出码 `0` 结束。若提示「已有实例持有单实例锁，但无法连接」，先确认托盘里是否已有 AgentBell；确认没有后，可删除提示中的锁文件再启动。

**杀毒软件误报 / 首次启动慢**

PyInstaller 单文件包常见现象。可将 exe 加入信任目录，或改用 `--onedir` 打包。请从本机源码自行构建，不要运行来路不明的同名程序。

## 安全说明

- HTTP 服务只绑定环回地址，不对局域网开放；仍建议设置随机 `X-Token`，防止本机其他程序随意弹窗。
- 通知内容只在本机进程内显示；SQLite 历史保存在本地文件，不会上传。请不要在 `summary`、`error`、`title` 中放入 token、密码等敏感信息。
- Agent 会话扫描只读取本机 Claude Code / Qoder 的会话元数据（路径、时间、大小、记录数），不解析对话正文，也不会发送到任何外部服务；可在偏好设置中完全关闭。
- 「复制 Agent 接入指令」会把当前 `X-Token` 写入系统剪贴板；剪贴板可能被本机其他程序读取，请在可信环境中使用。
- 通知动作有白名单：链接仅 `http/https`；`retry` 只允许回环地址；`path` 默认关闭，开启后也只打开指定文件；`copy` 只写入剪贴板，不执行命令。
- 外部渠道由你自己配置 URL/token，通知内容会发送到对应服务；启用前请确认接收方可信。
- 单实例通道只接受「打开通知中心」请求，不执行任意命令；通道使用当前用户的本地套接字 / 命名管道。
- 请求体限制 1 MB，字段有长度上限，队列和历史都有界，避免异常调用拖垮程序。
- 本项目没有远程访问、文件上传、命令执行等能力。

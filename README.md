# AgentBell

一个只做一件事的本地桌面小工具：AI Agent 的一轮任务结束后，调用本机 HTTP 接口，桌面右上角立刻弹出置顶提醒：

> 上一轮【生成竞品分析报告】已完成，请查看

没有数据库、没有管理后台、没有 Web 页面、没有多通道推送，也不依赖任何云端服务。

## 特性

- 只监听 `127.0.0.1:8765`（可在 `config.json` 改端口），不暴露到局域网。
- 弹窗置顶、不抢键盘焦点，打字不会被打断。
- 成功 / 失败 / 取消三种状态图标，标题、摘要、耗时、错误信息。
- 「查看」用浏览器打开链接，「知道了」立即关闭。
- 默认 30 秒自动关闭，鼠标悬停暂停倒计时，底部进度条显示剩余时间。
- 同时最多显示 5 条，其余 FIFO 排队，关闭一条自动补一条。
- 常驻系统托盘，可查看最近通知、重新弹出、退出。
- 单实例启动：重复双击不会启动第二份服务，而是唤醒已有实例并打开通知中心。
- 内置原生通知中心（PySide6，风格参考 cc-switch）：左侧视图筛选、状态统计、通知卡片、空状态，关闭窗口后继续驻留托盘。
- 通知中心右上角「复制 Agent 接入指令」：一键把接口地址、`X-Token`、JSON 字段和「每轮结束必须推送」规则复制到剪贴板，粘贴给 Agent 即可。
- 可选 `X-Token` 校验。
- 每个请求和弹窗结果写入本地滚动日志。
- PyInstaller 单文件打包，Windows 下双击即用。

## 目录结构

```text
agentbell/
├─ agentbell/
│  ├─ __init__.py         版本号
│  ├─ __main__.py         python -m agentbell 入口
│  ├─ main.py             启动流程、配置/端口错误提示
│  ├─ app.py              托盘 + 弹窗 + HTTP 线程的协调层
│  ├─ api.py              FastAPI 路由、鉴权、字段校验
│  ├─ server.py           环回监听、uvicorn 线程
│  ├─ config.py           config.json 读写与校验
│  ├─ models.py           Notification 数据模型、链接白名单
│  ├─ store.py            线程安全的通知历史（本次运行，最多 200 条）
│  ├─ integration.py      Agent 接入指令生成（复制到剪贴板）
│  ├─ single_instance.py  QLockFile 单实例锁 + QLocalServer 唤醒通道
│  ├─ log.py              滚动日志、异常钩子
│  ├─ paths.py            源码/打包后的路径解析
│  ├─ autostart.py        Windows/macOS/Linux 开机自启
│  └─ ui/
│     ├─ icons.py         程序图标、状态图标
│     ├─ window.py        cc-switch 风格原生通知中心
│     ├─ toast.py         置顶弹窗、倒计时、堆叠调度
│     └─ tray.py          托盘菜单与最近通知
├─ tests/                 API、配置、窗口、单实例与 UI 自动化测试
├─ assets/agentbell.ico   打包用图标
├─ config.json            当前配置
├─ config.example.json    配置示例
├─ requirements.txt       运行依赖
├─ requirements-dev.txt   测试/打包依赖
├─ run.py                 源码启动入口
├─ AgentBell.spec         PyInstaller 配置
└─ README.md
```

## 环境要求

- Python 3.10+
- Windows 10/11、macOS 或常见 Linux 桌面（需要系统托盘）
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

启动后托盘出现蓝紫色铃铛图标，日志里会看到：

```text
AgentBell 已就绪：http://127.0.0.1:8765（X-Token 鉴权已开启）
```

右键托盘图标选择「打开通知中心」即可查看本次运行的通知记录。重复启动不会产生第二份服务，只会让已有实例打开通知中心。

也可以用 `python -m agentbell` 启动。

> Windows 下想双击免黑框运行源码，可把 `run.py` 的打开方式设为 `pythonw.exe`；更推荐直接使用打包后的 exe。

## 配置

首次运行若目录下没有 `config.json`，会自动生成一份（`token` 为空，即关闭鉴权）。本仓库自带的 `config.json` 使用示例 token `your-token`。

```json
{
  "port": 8765,
  "token": "your-token",
  "auto_close_seconds": 30,
  "autostart": false
}
```

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `port` | 整数 | `8765` | 仅绑定 `127.0.0.1`，范围 1–65535 |
| `token` | 字符串 | `""` | 非空时，`POST /notify` 必须携带相同的 `X-Token`；为空则关闭鉴权 |
| `auto_close_seconds` | 整数 | `30` | 弹窗自动关闭秒数，范围 0–3600；`0` 表示不自动关闭，只能手动关 |
| `autostart` | 布尔 | `false` | 是否随当前用户登录启动；修改后下次启动生效 |

注意：

- **请务必把 `your-token` 换成随机值**，例如：
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(24))"
  ```
- 修改端口或 token 后需要重启 AgentBell。
- `config.json` 格式错误时程序会弹窗说明具体行号并退出，不会带着错误配置继续运行。

## 接口

### `GET /health`

无需鉴权，用于探活：

```bash
curl http://127.0.0.1:8765/health
```

```json
{"ok":true,"app":"AgentBell","version":"1.2.0","auth":true}
```

AgentBell 只提供 `GET /health` 和 `POST /notify` 两个接口，不提供 Web 页面或 HTTP 通知列表；通知记录显示在应用内的原生通知中心里。

### `POST /notify`

请求头：

```text
Content-Type: application/json
X-Token: your-token        # 仅当 config.token 非空时必需
```

请求体：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `title` | 字符串 | 否 | `未命名任务` | 任务名，最长 200 字符，弹窗内超长会截断 |
| `status` | 字符串 | 否 | `succeeded` | `succeeded` / `failed` / `canceled` |
| `summary` | 字符串 | 否 | `""` | 结果摘要，最长 4000 字符 |
| `duration` | 字符串 | 否 | `""` | 耗时文本，如 `8m30s`，最长 64 字符 |
| `link` | 字符串 | 否 | `null` | 仅接受 `http` / `https`，其他协议会被忽略 |
| `error` | 字符串 | 否 | `null` | 仅 `status=failed` 时展示，最长 2000 字符 |

未知字段会被忽略；`null` 会回落到默认值；字符串首尾及连续空白会被压缩。

成功响应（HTTP 202）：

```json
{"ok":true,"id":"391cd8903658","queued":true}
```

错误响应：

| 状态码 | 场景 |
| --- | --- |
| `400` | 空请求体、JSON 格式错误、编码无法识别 |
| `401` | `X-Token` 缺失或不匹配 |
| `413` | 请求体超过 1 MB |
| `422` | 字段类型/长度不合法，如未知 `status` |
| `503` | 内存队列已满（200 条），通常意味着 UI 长时间无响应 |

请求体会先按 UTF-8（含 BOM）解码，失败后兼容按 GB18030 解码，以适配 Windows 命令行下 curl 发送中文的情况。

## 用 curl 测试

在 `config.json` 的 token 为 `your-token` 时，直接运行：

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"生成竞品分析报告","status":"succeeded","summary":"已完成 12 页报告","duration":"8m30s","link":"https://example.com/report"}'
```

预期：立即弹出「上一轮【生成竞品分析报告】已完成，请查看」，显示摘要、`耗时 8m30s`、查看/知道了按钮和 30 秒倒计时。

失败示例：

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"爬取行情数据","status":"failed","error":"目标站点返回 403","duration":"42s"}'
```

取消示例：

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json" \
  -H "X-Token: your-token" \
  -d '{"title":"批量导出 PDF","status":"canceled","summary":"用户手动停止"}'
```

### Windows 下中文乱码或 400

Windows 的 `curl.exe` 会把命令行字面量按当前代码页（通常是 GBK）发送。AgentBell 已做 GB18030 兼容，上面的示例可直接使用。若仍遇到编码问题，推荐把 JSON 存成 UTF-8 文件发送：

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

复制内容包含当前端口、当前 `X-Token`、请求头、JSON 字段说明、curl 示例，以及一条明确规则：**每一轮任务结束都必须推送一次通知，无论成功、失败还是取消**。Agent 会据此在后续每轮结束时自动调用 `POST /notify`。

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

## 托盘与弹窗行为

- 左键/右键托盘图标：菜单显示监听地址、鉴权状态、「打开通知中心」、「显示最近通知」、「退出」。
- 最近通知保留本次运行的最后 20 条，菜单展示最新 10 条；点击某条会重新弹出该通知。
- 再次启动 AgentBell（例如重复双击 exe）时，新进程会通知已有实例打开通知中心，然后自行退出，不会启动第二份 HTTP 服务。
- 通知中心是应用内的原生窗口，不依赖浏览器；关闭/最小化窗口只隐藏到托盘，程序继续接收通知。左侧可按全部/成功/失败/已取消筛选，卡片上的铃铛按钮可再次弹出提醒。
- 通知历史只在内存中，退出即清空（本项目不落数据库）。通知中心显示最近 200 条（单页最多渲染最近 100 条），托盘菜单读取最近 20 条。
- 弹窗固定显示在主屏右上角，逐条向下堆叠；最多 5 条。
- 第 6 条起进入 FIFO 队列，关闭任意一条后自动补位。
- 鼠标悬停在卡片上时倒计时暂停，移开后继续。
- 「查看」仅在链接为合法 `http/https` 时可用；点击后打开默认浏览器并关闭弹窗。
- 「知道了」立即关闭，队列中的下一条会自动补上。
- 弹窗使用 `WS_EX_NOACTIVATE` / `WA_ShowWithoutActivating`，显示时不会抢走当前输入焦点。

## 日志

- 位置：源码运行在项目根目录 `logs/agentbell.log`；打包后位于 exe 同目录 `logs/agentbell.log`。
- 目录不可写时（例如放在 `Program Files`）自动退到系统临时目录：`%TEMP%\AgentBell\logs\`（macOS/Linux 为 `/tmp/AgentBell/logs/`，实际以 `tempfile.gettempdir()` 为准）。
- 单个文件 2 MB，保留 3 个历史文件，UTF-8 编码。
- 记录：启动参数、配置路径、收到的通知、鉴权拒绝、字段校验失败、弹窗显示/关闭原因、点击查看、托盘重新显示、异常堆栈。
- 不会记录 token 本身；标题和摘要会截断后写入。

## 开机自启

把 `config.json` 中的 `autostart` 改为 `true` 并重启 AgentBell：

- Windows：写入当前用户 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，名称为 `AgentBell`。
- macOS：写入 `~/Library/LaunchAgents/com.agentbell.app.plist`。
- Linux：写入 `$XDG_CONFIG_HOME/autostart/agentbell.desktop`（默认 `~/.config/autostart/`）。

改回 `false` 并重启即可移除。自启配置失败只记录警告，不会阻止程序启动。

## 打包

PyInstaller 不能跨平台交叉编译，请在目标系统上分别打包。

### Windows

项目已提供 `AgentBell.spec`（单文件、无控制台、带图标）：

```bash
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean AgentBell.spec
```

产物：`dist\AgentBell.exe`。

把 `config.json` 复制到 exe 旁边再运行：

```bash
copy config.json dist\config.json
dist\AgentBell.exe
```

打包后 `config.json` 和 `logs/` 都位于 exe 所在目录。单文件模式首次启动需要解压到临时目录，通常会有 1–3 秒延迟。

### macOS / Linux

仍可使用 spec，但需要把 `icon=` 换成对应平台的图标（macOS 用 `.icns`，Linux 可省略）。也可以直接执行：

```bash
pyinstaller --noconfirm --clean --onefile --windowed \
  --name AgentBell \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.asyncio \
  --hidden-import uvicorn.protocols.http.h11_impl \
  --hidden-import uvicorn.lifespan.off \
  run.py
```

`uvicorn` 的 loop / HTTP 协议 / lifespan 实现是运行时按字符串导入的，必须显式加 `--hidden-import`，否则打包后启动 HTTP 服务会报模块找不到。通知中心已全部使用 PySide6 原生控件绘制，不需要再打包 HTML 资源；Windows 建议直接使用仓库内的 `AgentBell.spec`。

## 测试

```bash
pip install -r requirements-dev.txt

# Windows PowerShell
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest -q

# macOS / Linux / Git Bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

覆盖：鉴权顺序与 401、字段默认值/空值/长度、非法状态、危险链接、GB18030 中文请求体、空/坏 JSON、超大请求体、队列满、共享通知历史、Web 路由已移除、接入指令内容与 token 处理、通知中心筛选/计数/空状态/复制/关闭隐藏、单实例锁与二次启动唤醒、配置校验、弹窗文案与按钮、最多 5 条与排队补位、去重、自动关闭与悬停暂停。

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
2. 查看 `logs/agentbell.log` 是否有「拒绝通知」或字段校验失败；
3. 检查是否已达 5 条可见上限，此时新通知在排队；
4. 独占全屏应用（部分游戏）可能覆盖任何置顶窗口，切回桌面即可看到。

**弹窗会不会抢焦点？**

不会。窗口使用 `WindowDoesNotAcceptFocus`、`WA_ShowWithoutActivating`，Windows 下带 `WS_EX_NOACTIVATE` 扩展样式；鼠标移入也不会激活窗口，按钮点击除外。

**重复双击会启动多个 AgentBell 吗？**

不会。第一个实例在系统临时目录持有单实例锁（`AgentBell-single-<用户摘要>.lock`）并监听同名本地通道；后续启动会连接这个通道，让已有实例打开通知中心，然后以退出码 `0` 结束。若提示「已有实例持有单实例锁，但无法连接」，先确认托盘里是否已有 AgentBell；确认没有后，可删除提示中的锁文件再启动。

**通知中心打不开、没有记录或复制按钮不可用？**

1. 右键托盘图标选择「打开通知中心」；若托盘没有图标，先看日志确认程序是否正常启动；
2. 通知中心是原生窗口，不再提供浏览器页面；`GET /` 与 `/api/notifications` 均返回 404 属于正常行为；
3. 新通知只在本次运行内保留，重启程序后记录会清空；
4. 复制按钮写入的是当前端口与 token；修改配置并重启后需要重新复制接入指令。

**复制给 Agent 后没有自动推送？**

1. 确认 Agent 已按指令在每轮结束时调用 `POST /notify`，而不是只在被要求时调用；
2. 用 `GET /health` 确认服务在运行，并检查 token 是否与复制时的配置一致；
3. 查看 `logs/agentbell.log` 是否有 401、422 或字段校验失败记录；
4. 部分 Agent 只会在当前会话内遵守粘贴的规则，新开会话后需要重新粘贴接入指令。

**杀毒软件误报 / 首次启动慢**

PyInstaller 单文件包常见现象。可将 exe 加入信任目录，或改用 `--onedir` 打包。请从本机源码自行构建，不要运行来路不明的同名程序。

## 安全说明

- HTTP 服务只绑定环回地址，不对局域网开放；但仍建议设置随机 `X-Token`，防止本机其他程序随意弹窗。
- 通知中心只在本机进程内显示，不通过 HTTP 暴露通知内容；记录仅保存在内存中。请不要在 `summary`、`error`、`title` 中放入 token、密码等敏感信息。
- 「复制 Agent 接入指令」会把当前 `X-Token` 写入系统剪贴板，便于直接粘贴给 Agent；剪贴板可能被本机其他程序读取，请在可信环境中使用。
- 单实例通道只接受「打开通知中心」请求，不执行任意命令；通道使用当前用户的本地套接字 / 命名管道。
- 链接只允许 `http/https`，且仅在用户点击「查看」时用默认浏览器打开，不会自动打开；通知中心同样只渲染 `http/https` 链接。
- 请求体限制 1 MB，字段有长度上限，队列和历史都有界，避免异常调用拖垮程序。
- 本项目没有远程访问、文件上传、命令执行等能力。

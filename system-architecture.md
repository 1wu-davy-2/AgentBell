# AgentBell 系统架构与完整手册

> 项目介绍、页面截图、安装与使用教程见 [README](README.md)。本文件保留架构、配置、接口、打包与安全等完整技术细节。

一个只做提醒的本地桌面工具：AI Agent 每轮任务结束后调用本机 HTTP 接口，桌面右上角立刻弹出置顶提醒：

> 上一轮【生成竞品分析报告】已完成，请查看

2.0 在原有弹窗基础上补齐了「少打扰、可闭环、能配置、可追溯」：优先级、免打扰、全屏/会议抑制、聚合摘要、待确认与稍后提醒、通知卡片动作、规则与外部渠道、SQLite 历史与统计。

2.1 增加弹窗外观与展示方式（四套皮肤、右侧卡片 / 居中确认 / 全屏遮挡三种模式）、锁屏与息屏期间不丢提醒、Agent 会话扫描页，并修复设置页在较小窗口下内容被裁切的问题。

2.2 让 `overlay` 真正铺满整块屏幕（覆盖任务栏），支持自定义全屏背景图、在设置里一键「测试」预览；双击启动后默认自动打开通知中心，并带淡入上浮动画，启动状态一眼可见。仍然没有 Web 页面，界面全部是 PySide6 原生窗口。

2.2.1 修复接入指令导致的乱码隐患：要求所有字段按 UTF-8 发送，补充 Python、PowerShell 5.1 与 curl 的正确写法；服务端收到连续问号时会记录「疑似编码丢失」告警。已经被发送端转成 `?` 的文本无法还原。

2.3.0 新增「回到终端」：Agent 只要在请求里带上 `origin.pid`（推荐）或窗口标题，通知卡片就会多一个按钮，点击后把宿主终端窗口切到前台。只做窗口级聚焦，不选中具体标签页；找不到窗口时会提示并把项目路径复制到剪贴板。

2.4.0 让全屏遮挡模式的卡片可以摆放：新增 `overlay_area`，支持九宫格位置、卡片宽度、屏幕边距和水平/垂直微调；设置页可直接修改，并用「测试」立即预览。适合把提醒放到背景图不重要的角落，或避开画面主体。

2.5.0 把「摆放」变成所见即所得：设置页新增「全屏拖拽定位」，在真实全屏预览里直接拖动通知卡片，位置实时显示，点「保存位置」即按最近的九宫格锚点自动换算并写入配置。Agent 会话页也从只能看元数据升级为可直接在软件内阅读完整记录：按轮次折叠对话、查看工具调用与结果、跳转大纲、会话内搜索，并可复制全文或导出 Markdown；解析完全在本机只读完成。

2.6.0 重做启动体验与标志：双击后先出现带铃响动画的启动卡片，约 2.2 秒内依次显示本机服务、监听地址与下一步状态；首次启动随后进入四步介绍，可跳过或暂停自动播放，走完或跳过后写入 `onboarding_seen`，再次打开只显示「正在打开通知中心」。标志改为蓝底白铃、铃舌与铃身分开的圆标，缩到 16 像素仍能认出是铃；托盘和偏好设置新增「关于 AgentBell」，可查看 16/24/32/48/64 尺寸、彩色/单色变体、重响启动铃声并导出 SVG。

2.7.0 新增「Agent 启动」页：像 cc-switch 一样在程序内管理本机 Agent，自动检测 Claude Code、Claude Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes、Pi、MiniMax Code、Antigravity 是否安装；选择项目目录并填写初始提示词后，直接在 PowerShell 新终端里启动对应 Agent 并传入提示词，最近项目与最近使用的 Agent 会保存到配置。终端从 AgentBell 打开时记录精确 PID，可一键切回。同时把「回到终端」入口放到会话卡片、会话详情和启动记录上，不用等通知卡片也能窗口级跳转。

2.8.0 把软件职责收敛为「启动 / 更新 Agent」：Agent 启动页默认使用安装目录下自动创建的 `chat/` 工作区，选择其他项目仍可浏览或从最近项目切换；每个 Agent 卡片可一键打开项目主页 / GitHub 仓库。新增 AgentBell 自身的更新检查：在设置里填 `owner/repo` 后，启动时向 GitHub Releases 查询新版本，发现更新即下载稳定命名的 `AgentBell.exe`，校验大小与 SHA-256 后由独立 PowerShell 脚本等待退出、备份旧文件、替换并重启。下载只接受 GitHub 域名，源码模式只下载不替换。仓库同时附 GitHub Actions 工作流：测试、PyInstaller 打包、上传 artifact，打 `v*` 标签时自动发布 Release。

2.8.1 让 Agent 启动更直接：在「Agent 启动」页双击任意已安装的 Agent 卡片，就会用当前项目目录（默认 `chat/`）和初始提示词立即打开终端，不用再点「打开终端并开始」；双击未安装的卡片只选中并显示安装提示。通知中心标题栏的双击最大化/还原行为不变。

2.9.0 新增「运行环境」页：普通用户不用自己准备 Node。点「一键安装全部」即把官方 Node LTS 便携包和 7 个官方 Agent CLI（Claude Code、Codex、Gemini CLI、OpenCode、OpenClaw、Hermes、Pi）装进安装目录的 `runtime/`，全程免管理员权限、不改系统 PATH；下载只走 HTTPS 白名单并校验 SHA-256（Node 用官方 `SHASUMS256.txt`），支持单个卸载与重新检测。Agent 启动页会自动识别 `runtime/` 里的 CLI；DeepSeek 没有官方 CLI，改为供应商预设，用 DPAPI 加密保存的 API Key 直接以 DeepSeek 端点启动 Claude Code。

2.9.1 收窄运行环境职责：只安装 Node 与 npm Agent CLI，不再代下载、代解压 cc-switch 等外部 exe；「其他工具」行改为「打开下载页」跳转 GitHub Releases，下载白名单同步收窄到 nodejs.org 与 npm 官方源 / 镜像。

2.9.6 补齐「回到终端」与来源识别：通知未填 `origin` 时，服务端按本机 HTTP 连接的客户端端口反查发送进程 PID，再沿父进程链定位宿主窗口；`source` 为空时也会按进程链自动补出 Agent 名（如 Qoder、Claude Code）。显式填写的 `origin.pid` / `source` 仍然优先。此前 2.9.5 修复了切换「已完成 / 失败」筛选时约 10 秒的界面假死与偶发空白窗口。

2.9.7 修复「终端窗口已置前，但系统未授予键盘焦点」：Windows 前台锁会拒绝普通 `SetForegroundWindow`，现在依次尝试附加前台与目标线程输入队列、`SwitchToThisWindow`，最后用一次短暂的 Alt 输入满足前台锁；仍失败才退回仅置前并提示。该兜底只在用户明确点击「回到终端」后触发。

2.9.8 优化通知来源展示与筛选：「来源 Agent」从摘要下方移到卡片标题行；通知中心在状态标签右侧新增 Agent 来源下拉，可与状态、搜索叠加，计数和总条数同步变化，重置筛选时一并恢复。更新设置支持填写仓库并在启动约 9 秒后自动检查，托盘与 Agent 启动页仍可手动检查；GitHub Actions 改为自动选用编号最大的 spec，不再写死旧版文件名。

2.9.9 让「进行中」不再只等显式通知：会话扫描结果中最近 2 个扫描周期（至少 120 秒，默认 240 秒）内仍有写入的会话，会以「活跃会话」卡片自动出现在「进行中」页，标注 Agent、项目、最近活动时间与记录数，可直接查看记录或回到终端。活跃会话是只读推断，不写入 SQLite、不进入「全部」计数，但会计入「进行中」标签，并随来源筛选与搜索收窄；扫描关闭时自动隐藏。

2.9.10 补齐首次运行的更新配置：生成的 `config.json` 默认填入 `1wu-davy-2/AgentBell` 并保持「启动时自动检查」，下载后约 9 秒即可查询 Releases；从旧版本升级且仓库为空的配置不会被覆盖，仍可在偏好设置中填写。

2.10.0 新增等待输入提醒，但不新增状态枚举：在 `running` 通知上增加 `needs_input` / `wait_reason` / `wait_source` / `session_id` / `run_id`，显式上报是主路径，本地推断是可选兜底。通知卡片显示等待原因，通知中心「进行中」下新增「待输入」子筛选；同一会话的后续事件或 `needs_input=false` 会结束等待。旧数据库启动时幂等补齐新列，老客户端不传新字段时行为不变。

2.11.0 新增运行时间线：`run_events` 只追加记录一次运行的开始、执行中、等待、继续、结束与备注，`run_id` 按「客户端传入 → `session:<session_id>` → `notify:<dedupe_key>` → `single:<通知 id>`」生成。`/notify` 可选 `phase`；不传时按状态变化自动推断，同一运行同一阶段 5 秒内合并。通知表仍是当前状态读模型，时间线只负责历史；卡片新增时间线弹窗，会话详情显示最近一次运行，统计页增加运行数、运行成功率、P50/P90 耗时与累计等待。删除或裁剪通知时同步清理孤儿事件。

2.12.0 新增只读动作：`/notify` 的 `actions` 接受 `session` 与 `timeline`，分别打开内置会话记录与本次运行时间线。两类动作只读取通知自身的 `session_id` / `run_id`，忽略 `value`，不执行任何外部命令；未知标识或缺少标识时给出非阻塞提示。动作顺序固定为 `focus` → `session` → `timeline` → 其他，弹窗与通知中心的首个按钮因此总是「回到终端」或「查看记录」。不提供批准权限、自动继续或发送提示词的动作，审批必须回到终端完成。

2.20.0 托盘图标新增点击打开通知中心：`TrayIcon` 连接 `QSystemTrayIcon.activated`，收到 `Trigger` 或 `DoubleClick` 时发出 `open_center_requested`，由应用打开并置前既有的通知中心单例；`Context` 等其他原因不处理，右键菜单保持原样。Windows 托盘溢出面板中的图标同样响应左键单击与双击，双击只会重复置前，不会创建第二个窗口。

2.19.1 修复 Linux 托盘菜单生命周期：`QSystemTrayIcon` 不持有上下文菜单的所有权，菜单此前只作为局部变量传给 `setContextMenu`；同时 PySide6 6.8 在回收子菜单的 `menuAction` 包装器时会连带删除子菜单。现在 `TrayIcon` 同时保存上下文菜单与「显示最近通知」「勿扰模式」两个子菜单 action 的强引用，打开子菜单不再触发 `QMenu already deleted`。同步修正 macOS 测试夹具，在非 Windows 环境同时关闭 `_IS_LINUX` 与 `_IS_MACOS`，让 mock 的 Windows 路径按预期执行。功能与 2.19.0 相同，2.19.0 标签因 Linux arm64 与 macOS 测试未通过而没有发布。

2.19.0 扩充日常观测、规则调试与平台能力：会话页新增 Codex / Gemini / Grok / OpenCode 只读扫描，等待输入推断扩展到 Codex / Gemini / Grok；通知中心搜索支持 `status:` / `source:` / `priority:` / `session:` / `run:` / `ack:` 字段过滤，统计支持 7 / 30 / 90 天区间与 CSV 导出，并可批量归档、按日期或来源分组；托盘新增 30 分钟 / 1 小时 / 到明早的快捷免打扰；设置页规则区新增「试运行」，用一条样例通知展示命中的规则与最终字段。平台侧补齐 macOS 的全局快捷键、回到终端、空闲 / 全屏 / 会议 / 锁屏推断、便携 Node 与原地更新；Linux Wayland 通过 XDG GlobalShortcuts portal 注册全局快捷键，窗口聚焦明确提示系统限制；Windows Authenticode 与 macOS Developer ID 签名 / 公证接入 CI。签名证书、密码与 App Store Connect 密钥只从环境变量或 GitHub Secrets 读取，不写入仓库、命令行日志或构建产物。

2.18.0 新增 Windows ARM64 与 macOS 双架构：Windows 在 `windows-11-arm` runner 上用原生 Arm64 Python、Arm64 PySide6 与 PyInstaller 构建，产物命名 `AgentBell-arm64.exe`，与 x64 的 `AgentBell.exe` 并存。更新器新增按架构选资产：Arm64 只接受名称含 `arm64` 的 exe，x64 排除 arm64 资产，绝不交叉替换。macOS 使用 `AgentBell-macos.spec` 生成 `.app`（`EXE` + `COLLECT` + `BUNDLE`），`scripts/make_macos_icon.py` 通过 QSvgRenderer 与 `iconutil` 生成 `.icns`，`scripts/build_macos_packages.py` 负责 ad-hoc `codesign`、`ditto` zip 与 `hdiutil` dmg，并按架构输出 `AgentBell-macos-<arch>.dmg` / `.zip`。冻结的 macOS 应用把 `config.json`、`logs/`、`agentbell.db` 与 `chat/` 写入 `~/Library/Application Support/AgentBell`，应用包保持只读；自启写入 `~/Library/LaunchAgents/com.agentbell.app.plist`。提示音在 macOS 走 `afplay`，Linux 走 `paplay` / `aplay`，端口占用提示按平台给出 `lsof` / `ss` / `netstat` 命令。

2.18.2 修复 Release 校验文件：Windows x64 与 arm64 打包任务此前都写 `dist/SHA256SUMS.txt`，两个 artifact 经 `download-artifact` 合并后同名文件互相覆盖，最终 `SHA256SUMS.txt` 只保留 x64 的两个 exe。现在按架构输出 `SHA256SUMS-windows-<arch>.txt`，与 Linux / macOS 的命名方式一致，合并后覆盖全部 16 个可下载产物。

2.18.1 修复 arm64 构建机上的测试：更新器与资产选择用例此前依赖宿主机默认架构，在 Windows / Linux / macOS 的 arm64 runner 上按 arm64 选包导致断言失败，现在统一显式传入 `machine`；时间格式用例改为按本地时区处理跨夏令时的旧时间。产品代码未改动，功能与 2.18.0 相同。2.18.0 标签因 arm64 测试失败而没有发布。

2.17.0 把 Linux 产物扩展为四种格式：x64 与 arm64 各生成 `tar.gz`、`AppImage`、`deb` 与 `rpm`，由 `scripts/build_linux_packages.py` 统一构建。2.17.1 修复了 CI 中 `appimagetool` 相对路径未解析为绝对路径、以及等待扫描测试 30 秒边界偶发失败的问题。AppImage 使用固定版本的 appimagetool 1.9.1 与 type2-runtime 20251108，AppDir 内含 `AppRun`、桌面项、图标与 `/usr/bin/AgentBell`；deb 安装到 `/opt/agentbell/AgentBell` 并提供 `/usr/bin/agentbell` 符号链接；rpm 关闭 strip、debuginfo 与 build-id，避免破坏 PyInstaller 单文件。更新器仍只选择 tar.gz；AppImage 通过 `APPIMAGE` 环境变量识别，deb/rpm 的安装目录通常不可写，二者都拒绝原地替换并提示下载新包或使用 apt/dnf。

2.16.1 新增 Linux x64 / arm64 通用版：窗口聚焦、「回到终端」、全屏 / 会议 / 锁屏检测、全局快捷键、托盘、终端启动与包内更新全部按平台实现。X11 会话功能完整；Wayland 会话可正常弹窗与使用通知中心，但自动降级为无全局快捷键、无窗口聚焦、无全屏 / 空闲检测，并在界面与日志中提示。Release 同时提供 `AgentBell.exe`、`AgentBell-linux-x64.tar.gz` 与 `AgentBell-linux-arm64.tar.gz`，更新器按当前架构选择资产；插件 Hook 在 Linux 上改用 `AgentBell --hook` 子命令，便携 Node 与 Agent CLI 支持 Linux `tar.xz`，配置中的 API Key 在 Linux 优先写入 Secret Service。2.16.0 标签因 Linux CI 测试未通过而未发布。

2.15.0 新增「仅在主屏显示提醒卡片」：全屏遮挡仍逐屏铺满所有显示器并覆盖任务栏，启用 `overlay_area.card_on_primary_only` 后只有主屏绘制卡片，副屏仅保留背景图与遮罩；点击任意屏幕仍会关闭全部提醒，必须确认的通知仍按脉冲提示处理。设置页「全屏显示区域」提供同名开关，默认关闭以保持每屏显示卡片的行为；旧配置缺少该字段时按 `false` 解析。

2.14.0 新增「一键接入提醒」：运行环境页可把本机 Agent 的 Hook 写入各自用户配置，Claude Code 使用 `~/.claude/settings.json` 的 `UserPromptSubmit` / `Notification` / `Stop`，Gemini CLI 使用 `~/.gemini/settings.json` 的 `BeforeAgent` / `Notification` / `AfterAgent`，Grok 使用 `~/.grok/hooks/agentbell.json` 的 `UserPromptSubmit` / `Notification` / `Stop` / `StopFailure` / `StopCancelled`；Codex 只支持顶层 `notify`，因此仅提醒每轮结束。写入前展示完整预览，按时间戳备份，使用配置锁与原子替换，只追加带 `agentbell-hook` 标记的条目；撤销只移除自己的条目，已有 Hook / MCP / 密钥保持不变，已有 Codex `notify` 不会被覆盖。Hook 脚本读取本机 `config.json` 的端口与 token，按会话维护最小状态（轮次、是否等待、更新时间），只向环回接口上报；不批准权限、不自动继续、不发送提示词。

2.13.0 规则精细化：`rules` 在来源 / 标题 / 状态之外新增 `needs_input`、`wait_reason`、`project`、`min_duration_seconds`、`max_duration_seconds`。项目名取自 `origin.working_dir` 目录名或本地会话项目名，支持通配符；时长条件按通知的 `duration` 解析，缺失或不合法时不匹配。`/notify` 改为读取实时配置，设置页保存规则后立即对新通知生效；本地推断的等待提醒也走同一套规则。规则仍按顺序匹配、后匹配覆盖标量字段，最多 50 条。通知中心的悬停提示同步收紧：仅在文字被截断时出现，按 32 字换行并统一浅色样式，避免遮挡相邻卡片。

## 特性

- 只监听 `127.0.0.1:8765`（可在 `config.json` 改端口），不暴露到局域网。
- 弹窗置顶、不抢键盘焦点，打字不会被打断。
- 状态：成功 / 失败 / 取消 / 进行中；进行中通知可带 0–100 进度并在原卡片更新。
- 等待输入：进行中通知可带 `needs_input` 与等待原因（权限、提问、限流、上下文超限、其他），卡片与「进行中」页的活跃会话同步标记；「待输入」子筛选只显示等待中的通知与会话。显式上报为主，Claude Code / Qoder / Codex / Gemini / Grok 尾部只读推断为可关闭的兜底。
- 一键接入提醒：在运行环境页写入 Claude Code / Gemini CLI / Grok 的等待与结束 Hook，Codex 支持结束提醒；写入前预览，按时间戳备份，使用配置锁与原子替换，只追加带标记的条目，可随时撤销。
- 运行时间线：同一 `run_id` 的事件写入只追加的 `run_events`，卡片「时间线」按钮展示阶段、相对耗时、状态与来源；会话详情显示最近一次运行摘要，统计页增加运行数、运行成功率、P50/P90 耗时与累计等待。
- 只读动作：通知可带「查看记录」「时间线」按钮，直接打开本地会话与运行时间线；不包含审批、自动继续、发送提示词或任意命令。
- 优先级：`low` / `normal` / `high` / `critical`；紧急通知常驻，必须点「知道了」才消失。
- 弹窗外观：`midnight` 午夜蓝 / `light` 晨光白 / `ocean` 深海青 / `amber` 琥珀暖四套皮肤，可按全局配置、规则或单条通知指定。
- 弹窗模式：`corner` 右侧小卡片、`center` 居中弹窗（必须确认）、`overlay` 全屏遮挡；全屏模式在每块显示器逐屏铺满并覆盖任务栏，可搭配自定义背景图。同一时刻只显示一种弹窗，避免卡片与全屏层互相干扰。
- 全屏背景图：`overlay` 支持 PNG / JPG / BMP / WebP，自动等比裁剪铺满并叠加半透明压暗层；留空或图片失效时回落到内置渐变。
- 全屏显示区域：`overlay_area` 可把卡片放到九宫格的任意位置（居中、上下左右、四角），设置宽度、屏幕边距与水平/垂直微调；卡片高度随内容自动，设置页「测试」可即时预览。多显示器默认每屏都显示卡片，勾选「仅在主屏显示提醒卡片」后副屏只保留背景与遮罩，点击副屏任意位置仍可关闭提醒。
- 全屏拖拽定位：设置页「全屏拖拽定位…」打开真实全屏预览（背景图与皮肤同步），拖动卡片即可摆放，顶部实时显示坐标与尺寸，点「保存位置」自动换算成锚点与偏移并立即生效。
- 效果预览：偏好设置底部「测试」按钮，按当前选择的模式、皮肤与背景图立即弹出一条预览，不写入历史、不影响真实通知。
- 启动过渡：双击后先显示白底启动卡片，铃形标志播放一次铃声（双圈扩散 + 轻微摆动），约 2.2 秒内依次显示「正在唤起本机服务」「127.0.0.1:端口 · 已连接」和下一步状态；支持系统「减少动画」设置。
- 首次启动介绍：首次启动在通知中心上覆盖四步介绍（只读元数据、一轮任务一声铃、会话文件留在本机、关窗后服务常驻），默认 4.6 秒自动推进，可暂停、跳过、点上一步/下一步或用方向键操作；完成或跳过后写入 `onboarding_seen`，以后不再出现。
- 标志与关于：蓝底白铃、铃身与铃舌分开的圆标，16 像素下仍保持铃的轮廓；「关于 AgentBell」展示 16/24/32/48/64 尺寸与彩色/单色变体，可重响启动铃声并导出 SVG。
- 再次打开：服务已在运行时不再走完整介绍，只显示带「正在打开通知中心」的启动卡片，然后唤醒已有窗口。
- 锁屏保护：锁屏 / 息屏 / 屏保时暂停倒计时并暂缓新弹窗，解锁后补发；默认开启，可在偏好设置关闭。
- 打扰控制：成功可只进通知中心；失败与高优先级弹窗；免打扰时段；全屏/会议程序前台时延后，结束后补发。托盘「勿扰模式」可快速暂停 30 分钟、1 小时或到明早，并与配置中的安静时段叠加。
- 冷却与聚合：短时间连续弹窗会自动合并成一条摘要，避免刷屏。
- 去重更新：相同 `dedupe_key` 原地更新同一张卡片，适合长任务的进度推送。
- 闭环处理：`require_ack` 待确认、5/15/30 分钟稍后提醒、未读升级（重新弹出 + 托盘闪烁 + 提示音）。
- 卡片动作：回到终端、打开链接、复制文本、重试回调、打开本地文件、打开通知中心。
- 回到终端：请求带 `origin`（`pid` / `window_title` / `working_dir`）时自动生成按钮，沿父进程链定位宿主终端或编辑器窗口并切到前台；只聚焦窗口，不选中标签页，也不执行任何命令。未带 `origin` 时按本机连接反查发送进程，尽力补出按钮与来源 Agent。Windows、macOS 与 Linux X11 可用；Wayland 会说明系统不允许应用主动切换焦点。macOS 需要辅助功能权限。会话卡片、会话详情与启动记录也有「回到终端 / 回到窗口」入口。
- Agent 启动：内置 11 个常见 Agent 的检测规则（Claude Code、Claude Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes、Pi、MiniMax Code、Antigravity），已安装的排在前面并显示可执行文件路径；选择项目目录、填写初始提示词后，点「打开终端并开始」或直接双击卡片，即打开 PowerShell 新窗口并启动对应 Agent。提示词通过环境变量传入，不拼接进 shell 命令；桌面应用只打开窗口，不会假装能预填提示词。最近 6 个项目与上次使用的 Agent 会写入 `agent_launcher`。
- 默认 chat 工作区：首次启动在安装目录（源码模式为仓库根目录）自动创建 `chat/`，Agent 启动页默认选中它；要回到「本目录里直接聊」的用法，不用每次浏览文件夹。也可继续选择其他项目，最近项目仍会保留。
- 便携运行环境：内置「运行环境」页把 Node LTS 与 7 个官方 npm Agent CLI 装到安装目录 `runtime/`；下载只接受 HTTPS 白名单域名并校验 SHA-256，免管理员权限、不改系统 PATH，安装后可卸载与重新检测；cc-switch 等外部 exe 不代装，点按钮跳转官方下载页；DeepSeek 作为供应商预设注入 Claude Code 启动环境。
- Agent 项目主页：每张 Agent 卡片都可点右上角「项目主页」打开对应的官网或 GitHub 仓库，方便查安装方式、更新与文档。
- 自身更新：安装包预填 GitHub 仓库 `1wu-davy-2/AgentBell`，启动约 9 秒后检查 Releases；发现新版本会提示并按平台与架构下载 `AgentBell.exe` / `AgentBell-arm64.exe`（macOS 为 `AgentBell-macos-<arch>.zip`，Linux 为 `AgentBell-linux-<arch>.tar.gz`），校验大小与 SHA-256 后在退出时自动替换、备份旧版并重启。Windows ARM64 只接受 arm64 资产，绝不回落到 x64。macOS 用 zip 内签名并公证过的 `.app` 做原地更新，dmg 仅用于首次安装；AppImage 与 deb/rpm 提示下载新包或使用包管理器升级。托盘和 Agent 启动页都有「检查更新」入口；源码模式只下载安装包，不会替换正在运行的 Python 程序。仓库可在设置里改为其他 `owner/repo` 或清空。
- 规则引擎：按来源 / 标题 / 状态 / 等待原因 / 是否等待输入 / 时长 / 项目自动设置优先级、静音、待确认、免打扰例外、弹窗外观、外部渠道；保存设置后立即生效。设置页提供「试运行」，输入一条样例通知即可查看命中的规则名与最终优先级、皮肤、渠道等字段。
- 模板与声音：四种状态的弹窗文案、五类 WAV 提示音均可配置。
- 外部渠道：企业微信、飞书、Telegram、Bark、ntfy、通用 Webhook；可按“离开电脑”或规则触发，失败只记日志，不影响主流程。
- Agent 会话：只读扫描本机 Claude Code / Qoder / Codex / Gemini / Grok 的会话文件与 OpenCode 的 SQLite 数据库，可在软件内直接阅读完整记录（轮次、工具调用、结果与思考过程）、跳转大纲、会话内搜索、复制或导出 Markdown，支持按项目、标题与路径筛选。
- 可选 SQLite 历史：通知中心支持全文与字段过滤搜索（`status:` / `source:` / `priority:` / `session:` / `run:` / `ack:`）、状态与 Agent 来源筛选、7 / 30 / 90 天统计区间与 CSV 导出、批量归档和按日期 / 来源分组，以及成功率 / 平均耗时 / 待确认统计和趋势图。
- 跨平台：Windows x64 / arm64、macOS 14+（Intel / Apple Silicon）与 Linux x64 / arm64 功能对齐。Windows 与 macOS 支持托盘、弹窗、通知中心、会话、Hook、全局快捷键、回到终端、空闲 / 全屏 / 会议 / 锁屏推断、终端启动、便携运行环境与包内更新；Linux X11 同样支持这些桌面能力，Wayland 通过 XDG GlobalShortcuts portal 注册全局快捷键，但系统不允许应用主动切换窗口焦点，相关入口会给出说明。
- 全局快捷键（默认 `Ctrl+Alt+A`）打开通知中心；托盘显示未读数。Windows 使用 `RegisterHotKey`，macOS 使用 Carbon `RegisterEventHotKey`，Linux X11 使用 `XGrabKey`，Wayland 使用 `org.freedesktop.portal.GlobalShortcuts`。
- 常驻托盘、单实例启动、可复制 Agent 接入指令、滚动日志、PyInstaller 打包（Windows 为单文件 `AgentBell-<构建号>.exe` / `AgentBell-arm64.exe`，macOS 为 `AgentBell.app` 的 dmg / zip，Linux 为 `AgentBell` tar.gz / AppImage / deb / rpm）。

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
│  ├─ presence.py         Windows / macOS / Linux 空闲时间、前台全屏、会议进程、锁屏/息屏检测
│  ├─ linux_desktop.py    Linux X11 / DBus 后端：窗口聚焦、全屏、空闲、锁屏与热键抓取
│  ├─ wayland_desktop.py  Wayland XDG GlobalShortcuts portal 客户端（dbus-next，后台线程）
│  ├─ macos_desktop.py    macOS 原生后端：Carbon 热键、CoreGraphics 空闲/全屏、lsappinfo/osascript 窗口与聚焦
│  ├─ search_query.py     通知中心字段过滤语法解析（status/source/priority/session/run/ack）
│  ├─ agent_sessions.py   Claude Code / Qoder / Codex / Gemini / Grok / OpenCode 会话扫描与导出
│  ├─ attention.py        等待输入推断：尾部增量读取、信号识别、去重与恢复
│  ├─ agent_launch.py     Agent 检测、项目内启动终端（PowerShell / macOS / Linux）与提示词传递
│  ├─ toolchain.py        便携 Node / Agent CLI 安装（Windows zip / macOS & Linux tar.xz）、校验与清单
│  ├─ hooks.py            Agent Hook 检测、预览、备份、原子写入与撤销
│  ├─ hook_cli.py         `--hook` 上报子命令：事件分类、轮次状态与环回发送
│  ├─ updater.py          GitHub Release 检查、按平台/架构选包、替换脚本与重启
│  ├─ window_focus.py     Windows / macOS / Linux X11 窗口解析与聚焦（回到终端）
│  ├─ channels.py         外部渠道后台投递线程
│  ├─ hotkey.py           全局快捷键（Windows RegisterHotKey / macOS Carbon / Linux XGrabKey / Wayland portal）
│  ├─ storage.py          SQLite 历史、run_events、搜索与统计
│  ├─ store.py            线程安全通知历史、去重索引、运行事件推断
│  ├─ integration.py      Agent 接入指令生成（复制到剪贴板）
│  ├─ single_instance.py  QLockFile 单实例锁 + QLocalServer 唤醒通道
│  ├─ log.py              滚动日志、异常钩子
│  ├─ paths.py            源码/打包后的路径解析
│  ├─ autostart.py        Windows/macOS/Linux 开机自启
│  └─ ui/
│     ├─ icons.py         程序标志绘制、SVG 导出、程序/状态图标
│     ├─ logo.py          可动画的标志控件（铃声扩散、铃身摆动、点击重响）
│     ├─ motion.py        系统「减少动画」检测与环境变量覆盖
│     ├─ splash.py        启动过渡窗口与三行状态时间线
│     ├─ onboarding.py    四步首次启动介绍覆盖层（自动播放、暂停、跳过）
│     ├─ about.py         「关于 AgentBell」标志展示、尺寸/变体与 SVG 导出
│     ├─ window.py        cc-switch 风格通知中心、搜索、统计、Agent 会话、Agent 启动与阅读视图
│     ├─ timeline.py      运行时间线弹窗（阶段、相对耗时、状态与来源）
│     ├─ toolchain_page.py 「运行环境」页面（安装、卸载、进度、提醒接入、DeepSeek 预设）
│     ├─ hooks_panel.py   「提醒接入」行、预览确认、批量接入与撤销
│     ├─ settings.py      偏好设置对话框
│     ├─ overlay_editor.py 全屏拖拽定位编辑器（真实背景预览、拖动、保存位置）
│     ├─ toast.py         置顶弹窗、皮肤/模式、倒计时、堆叠调度、聚合摘要
│     └─ tray.py          托盘菜单、未读、最近通知与「关于」
├─ tests/                 API、策略、存储、配置、会话扫描、启动、更新与标志测试
├─ assets/agentbell.ico   打包用多尺寸图标（Windows 16–256）
├─ assets/agentbell.svg   标志 SVG 源文件
├─ assets/agentbell.icns  打包用 macOS 图标（由脚本生成）
├─ assets/macos_entitlements.plist  macOS Hardened Runtime 权限（JIT、未签名可执行内存、库校验豁免、Apple Events）
├─ assets/hooks/agentbell-hook.ps1  Hook 上报脚本（Windows PowerShell 5.1，UTF-8 BOM；macOS / Linux 使用 `AgentBell --hook`）
├─ scripts/make_macos_icon.py       从 SVG 生成 iconset 与 `.icns`
├─ scripts/build_macos_packages.py  macOS 签名、公证、zip / dmg 与校验文件
├─ scripts/sign_windows.py          Windows Authenticode 签名（signtool / PFX / 指纹 / 时间戳）
├─ scripts/build_linux_packages.py  Linux tar.gz / AppImage / deb / rpm 与校验文件
├─ docs/screenshots/      README 使用的界面截图
├─ docs/releases/         每个版本的发布说明
├─ config.json            当前配置
├─ config.example.json    配置示例
├─ chat/                  运行后自动创建：Agent 启动的默认工作目录（不提交）
├─ runtime/               运行后自动创建：便携 Node、Agent CLI 与 tools.json（不提交）
├─ hooks/                 运行后自动创建：Hook 脚本副本与 state/ 会话状态（不提交）
├─ updates/               运行后自动创建：更新包与替换脚本（不提交）
├─ .github/workflows/build.yml  测试、Windows / macOS / Linux 双架构打包、artifact 与 Release 发布
├─ requirements.txt       运行依赖
├─ requirements-dev.txt   测试/打包依赖
├─ run.py                 源码启动入口
├─ AgentBell34.spec       PyInstaller 配置（Windows，AgentBell-34.exe，含 Hook 脚本资源）
├─ AgentBell-macos.spec   PyInstaller 配置（macOS，AgentBell.app，含 icns 与版本信息）
├─ AgentBell-linux.spec   PyInstaller 配置（Linux x64/arm64，产物名 AgentBell，不含 PowerShell 脚本）
├─ LICENSE                MIT 许可证
├─ README.md              项目介绍、截图、安装与使用教程
└─ system-architecture.md 本文件：架构、配置、API 与打包手册
```

## 环境要求

- Python 3.10+
- Windows 10/11 x64 / arm64：全屏 / 会议 / 锁屏检测、提示音、全局快捷键、窗口聚焦、便携运行环境与包内更新完整可用。
- macOS 14+（Intel / Apple Silicon）：托盘、弹窗、通知中心、历史、搜索、统计、提示音、Hook、全局快捷键、回到终端、空闲 / 全屏 / 会议 / 锁屏推断、终端启动、便携运行环境与 zip 包内更新均可用；「回到终端」需要辅助功能权限。发布构建可使用 Developer ID 签名与 Apple 公证，未配置证书时回退为 ad-hoc 签名。
- Linux x64 / arm64：X11 会话支持窗口聚焦、全屏 / 会议 / 锁屏检测与全局快捷键；Wayland 会话可运行弹窗、通知中心与托盘，并通过 XDG GlobalShortcuts portal 注册全局快捷键，但系统不允许主动切换窗口焦点，全屏 / 空闲推断也会降级。需要系统托盘与 Qt xcb 运行库。
- 依赖：FastAPI、uvicorn、Pydantic v2、PySide6；Linux 可选 `secret-tool`（libsecret）保存 API Key；macOS 使用 `afplay` 播放提示音。

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

启动后先出现约 2.2 秒的启动卡片（蓝底白铃、两声铃响），随后托盘出现铃铛图标，通知中心自动弹出（淡入 + 上浮动画）。首次启动还会在窗口上覆盖四步介绍；走完或跳过即记住，下次不再出现。日志里会看到：

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
  "onboarding_seen": false,
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
  "overlay_area": {
    "anchor": "center",
    "width": 0,
    "offset_x": 0,
    "offset_y": 0,
    "margin": 32,
    "card_on_primary_only": false
  },
  "hold_when_locked": true,
  "agent_sessions": {
    "enabled": true,
    "scan_interval_seconds": 120,
    "max_sessions": 80
  },
  "agent_launcher": {
    "recent_projects": [],
    "last_agent": ""
  },
  "update": {
    "enabled": true,
    "repo": "",
    "check_on_start": true
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
| `onboarding_seen` | 布尔 | `false` | 是否已完成首次启动介绍；走完或点「跳过介绍」后自动写为 `true`，改回 `false` 可重看 |
| `instance_name` | 字符串 | `""` | 单实例名称后缀，便于并行运行多份做调试 |
| `hotkey` | 字符串 | `Ctrl+Alt+A` | 打开通知中心的全局快捷键；空字符串关闭；支持 `Ctrl/Alt/Shift/Win`（Linux 可用 `Super` / `Meta`）加字母、数字、F1–F24 等；Wayland 会话通过 XDG GlobalShortcuts portal 注册 |
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
| `overlay_area.anchor` | 字符串 | `center` | 卡片位置：`center` / `top` / `bottom` / `left` / `right` / `top_left` / `top_right` / `bottom_left` / `bottom_right` |
| `overlay_area.width` | 整数 | `0` | 卡片宽度像素，`0` 使用默认 540；有效范围 240–1600，超出屏幕时自动收窄 |
| `overlay_area.margin` | 整数 | `32` | 靠边位置与屏幕边缘的距离，0–600；居中时只影响可用宽度与高度 |
| `overlay_area.offset_x` / `offset_y` | 整数 | `0` | 在锚点基础上的水平/垂直微调，-2000–2000；最终位置会被限制在屏幕内 |
| `overlay_area.card_on_primary_only` | 布尔 | `false` | 为 `true` 时仅主屏绘制提醒卡片，其余屏幕只显示全屏背景与遮罩；任意屏幕仍可点击关闭 |

- `corner`：出现在主屏右侧，多张卡片自上而下堆叠，保留原有的不抢焦点行为。
- `center`：屏幕中央单张弹窗，必须点「知道了」（或稍后提醒）才消失；该模式会强制 `require_ack`。
- `overlay`：在每块显示器铺满（含任务栏区域）的遮挡层 + 可定位卡片，适合必须马上看到的提醒；任意屏幕点击遮罩空白处可关闭全部，待确认时点击会轻微脉冲提示。
- `overlay_area`：卡片高度随标题、摘要、错误与动作按钮自动调整；位置先按九宫格锚点，再叠加微调。推荐点「偏好设置 → 弹窗外观 → 全屏显示区域 → 全屏拖拽定位…」，在真实全屏预览里直接把卡片拖到想要的位置，点「保存位置」即按最近锚点自动换算并保存；也可手动调整锚点、宽度、边距与偏移，再用底部「测试」预览最终效果。
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
- Qoder：`~/.qoder/projects/*/*.jsonl`（新格式），兼容旧版 `~/.qoder/projects/*/*/state.json`
- Codex：`~/.codex/sessions/*/*/*/rollout-*.jsonl`
- Gemini CLI：`~/.gemini/tmp/*/chats/session-*.json*`
- Grok：`~/.grok/sessions/*/*/chat_history.jsonl`
- OpenCode：`~/.local/share/opencode/opencode.db`（以只读方式查询 SQLite，不写入源数据库）

扫描阶段只解析项目路径、会话 ID、创建/更新时间、文件大小、记录条数和首条用户提问作为标题，不读取完整正文；只有点「查看记录」时才会解析该会话的对话内容。阅读视图完全在本机运行，不会发送到任何外部服务。OpenCode 的阅读视图按数据库内的消息结构转换，其他 Agent 使用各自的 JSON / JSONL 记录格式。

阅读视图参考 cc-switch 的会话页：

- 按轮次折叠：每轮显示序号、提问摘要和工具调用/失败/文件/耗时统计，点击标题展开正文；最后一轮默认展开，其余按需构建，长会话不卡顿。
- 工具过程：Read / Edit / Bash 等工具调用与结果折叠在「过程」里，失败项标红，长内容截断并给出提示。
- 大纲与搜索：顶栏「大纲」按轮次跳转；会话内搜索实时过滤匹配轮次并自动展开命中轮次与工具过程，显示「匹配 N / M 轮」。
- 复制与导出：可把当前会话复制为 Markdown 或导出 `.md`；返回列表后保留解析缓存，重复打开不再等待。

没有对应目录时页面显示空状态；扫描结果按更新时间倒序，可按标题、项目、会话 ID 或路径搜索，并支持打开项目目录或复制路径。

### 等待输入提醒 `attention`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `attention.enabled` | 布尔 | `true` | 是否启用等待输入提醒；关闭后不接收推断，也不显示「待输入」子筛选 |
| `attention.infer` | 布尔 | `true` | 是否启用本地推断；关闭后只保留显式 `/notify` 上报 |
| `attention.idle_seconds` | 整数 | `20` | 会话文件闲置多少秒后才推断为等待，范围 10–120 |
| `attention.poll_interval_seconds` | 整数 | `5` | 推断扫描间隔，范围 2–60 秒 |
| `attention.question_popup` | 布尔 | `false` | 推断出的「提问」是否弹窗；默认只进通知中心 |
| `attention.agents` | 字符串数组 | `["claude", "qoder", "codex", "gemini", "grok"]` | 参与推断的 Agent，取值 `claude` / `qoder` / `codex` / `gemini` / `grok`；未知项会被忽略，重复项自动去重 |

显式上报是主路径：`POST /notify` 带 `needs_input=true` 与 `status=running` 即生成等待卡片，随后同一 `session_id` 的任何新通知或 `needs_input=false` 都会结束等待。

本地推断只读最近 10 分钟内活跃的会话尾部，并按偏移增量读取，最多保留 256 KB：Claude Code / Qoder 读取 `projects/*/*.jsonl` 尾部，Codex 读取 `sessions/*/*/*/rollout-*.jsonl`，Grok 读取 `sessions/*/*/chat_history.jsonl`，Gemini CLI 读取 `tmp/*/chats/session-*.json*`。不同 Agent 的记录会先归一化为「用户/助手消息与工具事件」，再按同一组信号判断：

- 最后一条 assistant 含 `tool_use` 且没有匹配的 `tool_result` → `permission`；
- 最后一条 assistant 文本以问号或「是否 / 要不要 / Would you like / Shall I」等结尾 → `question`（默认不弹窗）；
- 尾部出现速率限制、配额相关错误文本 → `rate_limit`；
- 尾部出现上下文长度、token 超限相关错误文本 → `context_limit`。

同一指纹需连续两次扫描命中，且文件闲置达到 `idle_seconds` 才上报；同一会话 2 分钟内最多提醒一次。推断结果标记 `wait_source="inferred"`，去重键为 `wait:<agent>:<session_id>:<episode_fingerprint>`；会话恢复写入或推断消失时清除等待状态。推断不写入会话文件，不把会话正文写入日志或数据库。

### Agent 启动

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `agent_launcher.recent_projects` | 字符串数组 | `[]` | 最近从「Agent 启动」页打开过的项目目录，最多 6 个，单项最长 260 字符 |
| `agent_launcher.last_agent` | 字符串 | `""` | 上次使用的 Agent ID，例如 `claude-code`；下次打开页面时优先选中 |

「Agent 启动」页的检测顺序：

- 先查 `PATH` 中的命令：`claude`、`codex`、`gemini`、`grok`、`opencode`、`openclaw`、`hermes`、`pi`、`minimax`。
- 再查桌面应用固定安装位置（仅 Windows）：Claude Desktop（`%LOCALAPPDATA%\AnthropicClaude\claude.exe`、`%LOCALAPPDATA%\Programs\Claude\Claude.exe`）与 Antigravity（`%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe`、`%LOCALAPPDATA%\Antigravity\Antigravity.exe`）。macOS 与 Linux 只按 `PATH` 检测。
- 已安装的卡片排在前两列，显示可执行文件路径；未安装的显示安装命令或提示，点右上角「重新检测」刷新。

默认工作目录：

- 启动时在数据目录（Windows / Linux 打包版为 exe 所在目录，macOS 为 `~/Library/Application Support/AgentBell`，源码模式为仓库根目录）自动创建 `chat/`，Agent 启动页把「项目目录」预填为该路径。macOS 的终端启动不可用，页面只保留桌面应用与手动打开方式。
- `chat/` 与更新用的 `updates/` 都只在本机创建，已加入 `.gitignore`；删除后下次启动会重新创建。若目录不可写，页面回落到安装目录本身并允许手动选择其他路径。
- 想换项目直接点「浏览…」，或从「最近项目」里切换；最近 6 个项目保存在 `agent_launcher.recent_projects`。
- 选中任意 Agent 后点右上角「项目主页」，会用系统浏览器打开它的官网或 GitHub 仓库（见下表），方便查安装命令与版本说明。

| Agent | 说明 | 参考链接 |
| --- | --- | --- |
| Claude Code | Anthropic 官方终端编码 Agent | [anthropics/claude-code](https://github.com/anthropics/claude-code) |
| Claude Desktop | Anthropic 桌面客户端 | [claude.ai/download](https://claude.ai/download) |
| Codex | OpenAI 终端编码 Agent | [openai/codex](https://github.com/openai/codex) |
| Gemini CLI | Google 开源终端 Agent | [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) |
| Grok Build | xAI 终端编码 Agent（开源） | [xai-org/grok-build](https://github.com/xai-org/grok-build) |
| OpenCode | 开源终端编码 Agent | [anomalyco/opencode](https://github.com/anomalyco/opencode) |
| OpenClaw | 开源 Agent 客户端 | [openclaw/openclaw](https://github.com/openclaw/openclaw) |
| Hermes | Nous Research 终端 Agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) |
| Pi | Earendil Works 终端编码 Agent | [earendil-works/pi](https://github.com/earendil-works/pi) |
| MiniMax Code | MiniMax 编码 Agent | [MiniMax-AI/minimax-code](https://github.com/MiniMax-AI/minimax-code) |
| Antigravity | Google 的 Agent 开发环境 | [antigravity.google](https://antigravity.google/) |

界面与会话阅读的参考项目：[farion1231/cc-switch](https://github.com/farion1231/cc-switch)（通知中心与会话页的交互参考）、[GitHub Actions](https://docs.github.com/actions)（构建与发布工作流）。

启动行为：

- 终端类 Agent（Windows）：在所选项目目录打开一个独立 PowerShell 新窗口，设置窗口标题为 `AgentBell · Agent 名 · 项目名`，再启动 Agent；提示词作为 Agent 的第一个参数传入，通过 `AGENTBELL_PROMPT` 环境变量交给 PowerShell，不拼接进命令行文本。
- 终端类 Agent（Linux）：依次查找 `kgx`、`gnome-terminal`、`konsole`、`xfce4-terminal`、`mate-terminal`、`tilix`、`kitty`、`alacritty`、`wezterm`、`xterm`、`urxvt`、`st`、`x-terminal-emulator`，用登录 shell 打开新窗口并启动 Agent。窗口标题、项目目录、可执行文件与提示词都通过 `AGENTBELL_*` 环境变量传入，脚本文本不做插值；找不到终端时提示安装 gnome-terminal / konsole / xterm。
- 桌面应用（Claude Desktop / Antigravity）：只打开应用并设置工作目录；如果填写了提示词，会先提示桌面应用不支持自动预填，确认后才继续。
- 提示词上限 8000 字符；项目目录必须存在；启动失败会在按钮右侧显示原因，不弹额外对话框。
- 从 AgentBell 打开的终端会记录 PID，「本次打开的终端」里可点「回到终端 / 回到窗口」精确切回；关闭终端后按钮会失效。

### 运行环境

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `toolchain.npm_registry` | 字符串 | `https://registry.npmjs.org` | npm 下载源；可切换为 `https://registry.npmmirror.com`，必须是 HTTPS 地址 |
| `toolchain.deepseek_key` | 字符串 | `""` | DeepSeek API Key；Windows 用 DPAPI 保存为 `dpapi:`，Linux 优先写入 Secret Service（`secret:`），没有 `secret-tool` 时退化为 `plain:` base64（仅编码，不加密）；留空表示未配置 |

目录布局（`runtime/` 位于 exe 或仓库根目录旁，已加入 `.gitignore`）：

```text
runtime/
├─ node/        官方 Node LTS 便携包（Windows 为 node.exe；Linux 为 bin/node 与自带 npm）
├─ agents/      npm 全局前缀：7 个 Agent CLI 与其 bin 启动器
├─ cache/       npm 缓存
├─ npmrc        AgentBell 专用的 npm 配置（不读写用户 .npmrc）
└─ tools.json   组件版本、来源、SHA-256 与安装时间
```

安装源与校验：

- Node：读 `https://nodejs.org/dist/index.json`，取最新的 LTS 版本；Windows 下载 `win-x64` / `win-arm64` zip，Linux 下载 `linux-x64` / `linux-arm64` tar.xz。下载后按官方 `SHASUMS256.txt` 校验 SHA-256，解压出的唯一根目录整体移动到 `runtime/node`。
- Agent CLI：全部是官方 npm 包，使用便携 Node 自带的 npm（Windows 为 `runtime/node/node.exe`，Linux 为 `runtime/node/bin/node` 加 `npm-cli.js`），`--prefix runtime/agents`，不写系统全局目录。
- 外部工具（如 cc-switch）：AgentBell 不代下载、不代解压，页面上只提供「打开下载页」按钮跳转 GitHub Releases，由用户自行安装。
- 所有下载只允许 HTTPS 与白名单域名（nodejs.org、npm 官方源 / 镜像），并限制大小（单文件 200 MB、解压 900 MB）；重定向后重新校验域名。

行为：

- 「一键安装全部」按 Node → 7 个 CLI 顺序执行，页面显示阶段与进度；也可单独安装、卸载或重新检测。
- 列表状态来自 `tools.json` 与磁盘实际文件，两者不一致时以磁盘为准。
- 安装、卸载与探测都在后台线程执行，不阻塞窗口；失败会在底部状态区显示原因（含 npm 退出码）。
- 检测与启动 Agent 时，会把便携运行时临时加入子进程 `PATH`：Windows 为 `runtime/node` 与 `runtime/agents`，Linux 为 `runtime/node/bin` 与 `runtime/agents/bin`。不修改系统或用户环境变量。
- 便携 Node 支持 Windows（zip）、macOS 与 Linux x64 / arm64（tar.xz），安装与 PATH 注入方式一致。
- DeepSeek 没有官方 CLI：在页面底部保存 API Key 后，「用 DeepSeek 启动 Claude Code」会把 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_MODEL=deepseek-chat` 注入 Claude Code 的启动环境；「复制 Codex 配置片段」给出对应的 TOML。

### 程序更新

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `update.enabled` | 布尔 | `true` | 是否允许检查与下载 AgentBell 自身更新；关闭后完全离线 |
| `update.repo` | 字符串 | `"1wu-davy-2/AgentBell"` | GitHub 仓库，格式 `owner/repo`；也可填完整仓库 URL，读取时会自动归一化。代码、安装包与示例配置默认填入 `1wu-davy-2/AgentBell`；清空表示不联网 |
| `update.check_on_start` | 布尔 | `true` | 启动约 9 秒后自动检查；Windows / macOS / Linux 打包版发现新版本会自动下载并在退出时替换重启 |

行为：

- 仓库为空时不会发出任何网络请求；首次运行默认填入 `1wu-davy-2/AgentBell`，清空后手动点「检查更新」会提示去「偏好设置 → 常规 → 程序更新」填写。
- 只更新 AgentBell 自身，不会执行 npm / pip 等 Agent 安装或升级命令。
- 版本来自 `GET https://api.github.com/repos/{owner}/{repo}/releases/latest` 的 `tag_name`，去掉 `v` 后按数字比较；`2.8.0-beta` 低于 `2.8.0`。
- 资产按平台与架构选择：Windows x64 优先稳定命名 `AgentBell.exe`，排除名称含 `arm64` 的资产；Windows ARM64 只接受 `AgentBell-arm64.exe` 或名称含 `arm64` 的 `.exe`，没有匹配项时提示打开 Release 页面，绝不下载 x64 包；Linux 优先 `AgentBell-linux-<arch>.tar.gz`（`x64` / `arm64`），否则选名称同时包含 `agentbell` 与 `linux-<arch>` 的 `.tar.gz`；macOS 只接受 `AgentBell-macos-<arch>.zip`，不选 dmg。Release 中的 AppImage / deb / rpm / dmg 不参与自动更新选择。
- 下载只接受 `github.com` 与 GitHub 发布资源域名（`objects.githubusercontent.com`、`release-assets.githubusercontent.com`、`github-releases.githubusercontent.com`），并要求 HTTPS；下载上限 300 MB，完成后校验 API 给出的 `size` 与 `digest`（`sha256:`）后才算成功。
- 打包版（Windows）：下载到 `updates/` 后启动独立 PowerShell 更新脚本，等待当前进程退出，把旧 exe 备份为 `AgentBell.exe.bak`，再替换并按原命令行参数重启；替换失败会回滚并重新打开旧版。脚本只读取环境变量，不把路径或参数拼进脚本文本。
- 打包版（Linux）：下载 tar.gz 后只提取其中的 `AgentBell`，暂存到 `updates/staged-<版本>/`；启动独立的 `/bin/sh` 脚本等待 PID 退出，把旧文件备份为 `AgentBell.bak`，`mv` 替换并恢复可执行权限，再用 `exec` 以原参数重启。脚本路径、参数与日志路径全从环境变量读取，不使用 `shell=True`，重启命令用 `shlex.join` 安全拼接；失败时自动回滚。替换前会检查安装方式：`APPIMAGE` 环境变量存在时提示下载新的 AppImage，目标文件或目录不可写时提示使用 apt/dnf；这两种情况都不会解压或启动替换脚本。
- 打包版（macOS）：下载 `AgentBell-macos-<arch>.zip` 后校验大小与 SHA-256，解压暂存到 `updates/staged-<版本>/`；退出后由独立 `/bin/sh` 脚本等待 PID 结束，把旧 `.app` 备份到 `updates/`，用 `ditto` 替换应用包并重启，失败时回滚到旧版。应用包只读，配置与数据位于 `~/Library/Application Support/AgentBell`，替换不影响。收到 dmg 时提示从 Release 页面手动安装。
- 源码模式：只下载安装包并提示文件位置，不会替换、不会退出；避免误改开发环境。
- 托盘菜单「检查更新…」和「Agent 启动」页右上角「检查更新」都可手动触发；自动检查在启动过渡和首次介绍结束后才进行，避免打断首次使用。

发布约定：

- Release 资产包含 `AgentBell.exe`、`AgentBell-arm64.exe`、每种架构的 `AgentBell-macos-<arch>.dmg` / `.zip` 与 `AgentBell-linux-<arch>.tar.gz`、`.AppImage`、`.deb`、`.rpm`，并合并各平台校验文件为一个 `SHA256SUMS.txt`。Windows 工作流自动选用编号最大的 `AgentBell<数字>.spec`（忽略 Linux / macOS spec）：x64 产物复制为 `AgentBell.exe`，arm64 产物复制为 `AgentBell-arm64.exe`；macOS 使用 `AgentBell-macos.spec`，由 `scripts/build_macos_packages.py` 生成 dmg 与 zip；Linux 使用 `AgentBell-linux.spec`，产物名固定为 `AgentBell` 后交给 `scripts/build_linux_packages.py` 生成四种格式。
- 打 tag 前先把 `agentbell/__init__.py` 的 `__version__` 改成同一版本；工作流会校验 `v2.20.0` 与 `2.20.0` 一致，不一致时拒绝发布。
- 发布使用 GitHub Actions 的 `contents: write` 权限；fork 或 PR 构建只上传 artifact，不会发 Release。

### 历史

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `history.enabled` | 布尔 | `true` | 开启 SQLite 历史；关闭后仅保留内存记录 |
| `history.limit` | 整数 | `1000` | 最多保留条数，启动时自动裁剪 |
| `history.path` | 字符串 | `""` | 数据库路径；空则使用 `config.json` 同目录的 `agentbell.db`，相对路径按配置目录解析 |

同库另建只追加表 `run_events`，用于运行时间线：

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

- `kind` 仅允许 `started` / `progress` / `waiting_input` / `resumed` / `finished` / `note`；未知值读取时降级为 `note`。
- 只追加、不更新；同一 `run_id` 的同一 `kind` 在 5 秒内重复上报时直接跳过。
- 不单独建 `runs` 表；运行状态由首尾事件推导，统计时按 `run_id` 分组。
- 通知被删除或裁剪后，若没有其他通知引用该 `run_id`，对应事件一并清理；清空历史时全部删除。旧数据库启动时自动建表，无需手动迁移。

### 提示声音与模板

- `sounds`：键为 `succeeded` / `failed` / `canceled` / `running` / `critical`，值为 WAV 绝对路径，空表示静音；紧急通知优先使用 `critical`。Windows 通过 `winsound` 异步播放，macOS 调用 `afplay`，Linux 依次查找 `paplay` / `aplay`；找不到播放器时只记日志，不影响提醒。
- `templates`：四种状态的弹窗标题模板，必须包含 `{title}` 占位符，例如 `"上一轮【{title}】已完成，请查看"`。

### 规则 `rules`

规则按顺序全部匹配、后面的规则覆盖前面的标量设置，`channels` 会累加。最多 50 条。同一条规则内，`source` / `title_contains` / `status` / `needs_input` / `wait_reason` / `project` / 时长条件是「且」关系；`project` 取 `origin.working_dir` 的目录名或本地会话项目名，支持通配符且不区分大小写；带时长条件的规则只匹配能解析出 `duration` 的通知。设置保存后规则立即对新通知生效，无需重启。

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
      "name": "权限等待高优",
      "needs_input": true,
      "wait_reason": "permission",
      "priority": "critical"
    },
    {
      "name": "演示项目仅失败时确认",
      "project": "demo-*",
      "status": "failed",
      "require_ack": true
    },
    {
      "name": "长任务完成后转投",
      "min_duration_seconds": 600,
      "channels": ["wecom"]
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
| `needs_input` | 仅匹配是否处于等待输入（`true` / `false`） |
| `wait_reason` | 仅匹配指定等待原因（`permission` / `question` / `rate_limit` / `context_limit` / `other`） |
| `project` | 项目名匹配，支持 `*`、`?` 通配符，不区分大小写；取 `origin.working_dir` 目录名或会话项目名 |
| `min_duration_seconds` | 最短任务时长（秒），含边界；无 `duration` 或无法解析时不匹配 |
| `max_duration_seconds` | 最长任务时长（秒），含边界；不能小于 `min_duration_seconds` |
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
{"ok":true,"app":"AgentBell","version":"2.7.0","auth":true}
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
| `source` | 字符串 | `""` | 来源标识（Agent 名、任务类型），最长 100 字符，参与规则匹配与搜索；留空时按发送进程自动识别 |
| `dedupe_key` | 字符串 | `null` | 去重键，最长 200 字符；相同键会更新已有卡片并累加次数 |
| `needs_input` | 布尔 | `false` | 标记 `running` 通知正在等待用户；仅允许与 `status=running` 一起使用，否则返回 422 |
| `wait_reason` | 字符串 | `other` | 等待原因：`permission` / `question` / `rate_limit` / `context_limit` / `other`；未知值回落到 `other`；`needs_input=false` 时会被清空 |
| `wait_source` | 字符串 | `explicit` | `explicit` / `inferred`；未知值回落到 `explicit`；`needs_input=false` 时会被清空 |
| `session_id` | 字符串 | `null` | Agent 会话标识，最长 120 字符；用于关联活跃会话并结束同一会话的旧等待 |
| `run_id` | 字符串 | 按规则生成 | 运行标识，最长 120 字符；不传时依次回落为 `session:<session_id>`、`notify:<dedupe_key>`、`single:<通知 id>` |
| `phase` | 字符串 | `null` | 时间线阶段：`started` / `progress` / `waiting_input` / `resumed` / `finished` / `note`；显式传入时只追加该阶段，不再自动推断 |
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
| `origin` | 对象 | `null` | 来源位置，用于生成「回到终端」按钮，见下表 |

`origin` 每项：

| 字段 | 说明 |
| --- | --- |
| `pid` | 发送方进程 PID，推荐填写；AgentBell 沿父进程链向上找宿主终端 / 编辑器窗口 |
| `window_title` | 可选，窗口标题；用于在候选窗口中精确或模糊匹配，最长 200 字符 |
| `working_dir` | 可选，项目目录；聚焦失败时复制到剪贴板，最长 1024 字符 |

`pid` 与 `window_title` 至少填一个，否则忽略。服务端自动把 `origin` 转成 `focus` 动作并放在按钮首位；外部直接提交的 `focus` 动作会被忽略，以免伪造路径。窗口匹配优先使用进程血缘，其次才是标题；标题匹配会限制在可见、非工具窗口范围内。

`actions` 每项：

| 字段 | 说明 |
| --- | --- |
| `kind` | `open` / `copy` / `retry` / `path` / `center` / `session` / `timeline`；`focus` 由 `origin` 自动生成，不接受外部提交 |
| `label` | 按钮文字，最长 40 字符；为空时用默认文案 |
| `value` | `open` 为 http(s) 链接（为空时用通知的 `link`）；`copy` 为文本；`retry` 仅接受本机 http 回调地址（`127.0.0.1` / `localhost` / `::1`）；`path` 为本地绝对路径，且需 `allow_local_paths=true`；`session` / `timeline` 忽略此字段 |

`session` 打开 AgentBell 内置会话记录，必须同时填写 `session_id`；`timeline` 打开本次运行时间线，需要 `run_id`，或至少提供 `session_id` / `dedupe_key` 以便回落到 `session:` / `notify:` 运行编号。两者只按通知自身记录的标识查找本地数据，不读取 `value`，不执行外部命令；找不到会话或运行、或缺少标识时，按钮不会出现或被忽略并写入日志。它们不提供“批准权限”“自动继续”或“发送提示词”的能力。

`origin` 生成的 `focus` 动作占用第一个按钮位；其余动作按 `focus` → `session` → `timeline` → 原有顺序排列，总数仍以 4 个为上限。

等待输入：`needs_input=true` 未填 `priority` 时默认 `high`；`wait_reason` / `wait_source` 留空分别补 `other` / `explicit`。显式 `needs_input=false` 会清除该通知的等待标记；同一 `session_id` 的新事件也会结束之前的等待卡片。

运行事件：未传 `phase` 时，首次出现的 `running` 追加 `started`，终态追加 `finished`，并自动补出 `waiting_input` / `resumed`；显式传 `phase` 时只追加这一条。同一 `run_id`、同一阶段在 5 秒内重复上报会跳过，避免进度刷屏。事件只追加，不更新已有行。

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
  "needs_input": true,
  "wait_reason": "permission",
  "wait_source": "explicit",
  "run_id": "session:abc123",
  "phase": "waiting_input",
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

### 回到终端（origin）

推荐所有 Agent 都带上当前进程信息：

```json
{
  "title": "生成竞品分析报告",
  "status": "succeeded",
  "summary": "已完成 12 页报告",
  "origin": {"pid": 12345, "window_title": "Qoder", "working_dir": "E:\\proj\\report"}
}
```

- 服务端生成「回到终端」按钮，放在所有动作之前；请求里的 `actions` 按 `session` → `timeline` → 原有顺序追加。
- 请求未带 `origin` 时，服务端通过本机 TCP 连接（客户端端口 ↔ 发送进程）反查 PID，再快照宿主窗口；这是尽力而为的兜底，显式 `origin.pid` 仍然最准确。
- 只填 `working_dir` 也能生成按钮：服务端会取目录名作为窗口标题线索，适合无法拿到终端 PID 的 Agent；同时填 `pid` 仍是最准确的方式。
- `source` 留空时，服务端会沿发送进程的父进程链识别 Agent 名（Qoder、Claude Code、Cursor、VS Code 等），显示在弹窗元信息与通知中心；显式 `source` 优先。
- 通知中心里的 Agent 会话卡片、会话详情、以及「Agent 启动」页的本次终端记录都提供「回到终端」入口，不依赖通知是否带 `origin`。
- 多个终端窗口标题同时匹配时，会弹出一个选择菜单而不是随便挑一个。
- 点击后沿 `pid` 的父进程链查找可见窗口，也会识别 conhost / OpenConsole 子进程；找不到血缘窗口时再用 `window_title` 兜底。
- 只做窗口级聚焦：还原最小化、置前并尝试获取前台焦点；前台锁拒绝时会附加输入队列并重试，再用 `SwitchToThisWindow` 和一次短暂 Alt 输入兜底。仍无法取得焦点时退化为仅置前，并提示「已置前，但系统未授予键盘焦点」。
- 不会选中具体标签页，也不会执行命令或打开新终端。
- 找不到窗口时提示「未找到对应的终端窗口」，并把 `working_dir` 复制到剪贴板，便于手动定位；仅“置前未获焦点”时不覆盖剪贴板。
- Windows、macOS 与 Linux X11 可用：Windows 走 Win32 前台锁兜底，Linux 通过 X11 `_NET_ACTIVE_WINDOW` / `_NET_CLIENT_LIST` 定位窗口并请求激活，macOS 通过 `osascript` + 辅助功能权限激活宿主应用；Wayland 会说明系统不允许应用主动切换焦点。

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
- `overlay`：真正铺满每块显示器（含任务栏）的不透明遮挡层，多显示器时默认逐屏显示同一卡片，按 `overlay_area` 摆放（默认居中）；启用 `overlay_area.card_on_primary_only` 后只在主屏绘制卡片，副屏只保留背景与遮罩。使用自定义背景图时逐屏等比裁剪铺满并叠加压暗层，未设置或加载失败时使用皮肤渐变。任意屏幕点击遮罩空白处（副屏无卡片时点击任意位置）即关闭全部屏幕，若该通知必须确认则改为脉冲提示，仍需点「知道了」。
- 同一条通知更新（`dedupe_key`）时不会切换已显示的皮肤/模式；新推送可用 `popup_mode` / `popup_skin` 覆盖全局设置，规则命中时以规则为准。
- 四套皮肤同时作用于通知卡片与通知中心，可在「偏好设置 → 弹窗外观」中选择。

### 锁屏与息屏

- `hold_when_locked=true`（默认）时，Windows 锁屏、息屏、屏保或切换输入桌面都视为锁定：已显示的倒计时暂停，新通知进入延时队列（日志记为「通知延后提醒：locked」）。
- 解锁后恢复所有卡片倒计时，并按原队列补发延期通知；多条同样会合并成摘要。
- Windows 使用 WTS 会话状态、屏保与显示器状态；Linux 通过 systemd-logind 的 `LockedHint` 判断；Wayland 或其他检测不到的场景按未锁定处理。
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

- 全屏检测基于前台窗口矩形是否覆盖所在显示器，桌面、任务栏、壁纸窗口不算全屏；Windows、macOS 与 Linux X11 可用，Wayland 下无法读取前台窗口，按非全屏处理。
- 前台进程命中 `meeting_processes` 时同样延后；默认包含 Zoom、Teams、腾讯会议、Webex。Windows / macOS 读取前台应用名，Linux X11 通过 `_NET_WM_PID` 与 `/proc` 解析进程名。
- 延时队列每 30 秒复查一次，退出全屏、会议结束或解锁后立即补发；免打扰时段在结束时刻补发。
- `away_idle_seconds` 只影响外部渠道的 `when_away` 判断，不影响本地弹窗。

## 通知中心与统计

- 左侧筛选：全部 / 成功 / 失败 / 已取消 / 进行中；顶栏显示当前筛选数量与未读数。
- Agent 来源筛选：状态标签右侧下拉列出当前历史中的来源 Agent 及条数，选择后状态计数、总条数和卡片同步收窄；可与搜索、状态筛选叠加，「全部 Agent」或清除筛选恢复。
- 搜索：默认匹配标题、摘要、错误与来源；支持字段过滤 `status:` / `source:` / `priority:` / `session:` / `run:` / `ack:`，中文字段名（状态 / 来源 / 优先级 / 会话 / 运行 / 确认）等价，多个值用空格分隔取并集，无效值退回全文搜索；输入后 260ms 自动搜索，搜索状态下可一键清除。
- 归档与分组：列表默认只显示未归档通知，可切换已归档或全部；进入「批量管理」后多选并批量归档 / 取消归档；分组方式支持按日期、按来源或不分组。归档只改变列表可见性，不删除历史。
- 卡片：标题行显示状态、优先级、来源 Agent、`更新 ×N`、`待确认/已确认`、时间，摘要下方显示进度条、耗时、错误与动作按钮、重新弹出、确认、稍后提醒；已归档卡片带「已归档」标记。
- 数据统计：总通知数、成功率（成功 / 已结束）、平均耗时（可解析的 `duration`）、待确认数，以及 7 / 30 / 90 天区间内的每日总量/失败量柱状图；「运行时间线」卡片按 `run_id` 统计运行数、运行成功率、P50/P90 运行时长与累计等待时长，等待中未结束的区段计入当前时刻。「导出 CSV」把当前统计区间的通知导出为 UTF-8 CSV，包含接收/更新时间、标题、状态、优先级、来源、摘要、耗时、错误、会话/运行 ID 与确认状态。
- 运行时间线：有 `run_id` 的卡片右侧显示「时间线」按钮，弹窗按时间顺序列出阶段、相对耗时、绝对时间、状态、来源与关联会话；一次包含等待的运行会显示开始 → 等待输入 → 已继续 → 完成。会话详情页顶部显示最近一次运行的摘要，可直接打开同一时间线。
- 偏好设置：端口、token、自启、启动打开通知中心、自动关闭、冷却、成功弹窗、默认确认、快捷键、免打扰、全屏抑制、锁屏保留、弹窗模式与皮肤、全屏背景图与显示区域（含全屏拖拽定位与仅主屏卡片）、Agent 会话扫描、会议进程、离开判定、聚合、升级、模板、声音、规则与渠道 JSON，以及「关于」入口。所有标签页均可滚动，小窗口下不会裁切内容。保存后立即应用可热更新的项（含规则）并写回 `config.json`；端口、token 等监听相关配置需重启。
- 全屏拖拽定位：点「全屏拖拽定位…」进入与真实弹窗一致的全屏预览，卡片可自由拖动，顶部实时显示坐标、尺寸、最近锚点和偏移；点「保存位置」自动写回设置并保存配置，点「取消」不改动原值。
- 效果预览：设置对话框底部「测试」按钮按当前选择的模式、皮肤和背景图弹出一条预览。预览使用临时通知，不写入 SQLite 历史；`overlay` 预览会实际铺满屏幕，点「知道了」即可返回设置。
- Agent 会话页：左侧侧栏切换到「Agent 会话」，按项目分组显示本机会话；点「查看记录」进入阅读视图，支持轮次折叠、工具过程、大纲跳转、会话内搜索、复制全文和导出 Markdown；数据只读，不进入通知历史。
- 进行中活跃会话：扫描结果中最近 2 个扫描周期（至少 120 秒）内仍有写入的会话，会以「活跃会话」卡片出现在「进行中」页，显示 Agent、项目路径、记录数与最近活动时间；可查看记录或回到终端。它属于只读推断，不写入 SQLite，也不计入「全部」通知数，但会计入「进行中」标签，并随来源筛选与搜索收窄。扫描关闭或会话停止写入超过窗口后自动消失。
- 关闭窗口只是隐藏到托盘，程序继续接收通知；`Ctrl+Alt+A` 可随时唤出。

## 托盘与弹窗行为

- 左键/右键托盘图标：菜单显示监听地址、鉴权状态、未读数、「打开通知中心」、「显示最近通知」、「勿扰模式」、「关于 AgentBell…」与「退出」。勿扰模式可暂停 30 分钟、1 小时或到明早，也可一键关闭；暂停期间恢复普通弹窗策略，与配置的安静时段叠加。
- 最近通知保留本次运行的最后 20 条，菜单展示最新 10 条；点击某条会重新弹出该通知。
- 再次启动 AgentBell 时，新进程会通知已有实例打开通知中心，然后自行退出，不会启动第二份 HTTP 服务。
- 双击启动后先显示约 2.2 秒启动卡片；首次启动随后播放四步介绍，完成或跳过后不再出现；再次打开只显示「正在打开通知中心」。
- 双击启动后默认自动打开通知中心（`open_center_on_start=true`），窗口以 260ms 淡入 + 上浮动画出现；可在「偏好设置 → 通用」关闭。
- 「关于 AgentBell…」展示标志尺寸与单色变体，可重响启动铃声并导出 SVG；关闭对话框不影响托盘与服务。
- `corner` 模式弹窗显示在主屏右侧，逐条向下堆叠，最多 5 条，其余 FIFO 排队；`center` / `overlay` 为单张独占显示。
- 鼠标悬停在卡片上时倒计时暂停，移开后继续；锁屏期间所有倒计时都会暂停。
- 弹窗使用 `WS_EX_NOACTIVATE`（Windows）/ `WA_ShowWithoutActivating`（Linux），显示时不会抢走当前输入焦点。

## 日志

- 位置：源码运行在项目根目录 `logs/agentbell.log`；Windows / Linux 打包后位于 exe 同目录 `logs/agentbell.log`；macOS 位于 `~/Library/Application Support/AgentBell/logs/agentbell.log`。
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

### 中文与编码

所有字段都必须是 UTF-8。最常见的乱码来源不是 AgentBell，而是发送端已经把中文转成了 `?`，这种文本无法还原。

- **PowerShell 5.1**：`Invoke-RestMethod -Body $json` 会把字符串按系统 ANSI 代码页转换，中文会变成 `?`。必须先转成 UTF-8 字节：

```powershell
$payload = @{ title = "生成竞品分析报告"; status = "succeeded"; summary = "已完成 12 页报告" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8765/notify" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Headers @{ "X-Token" = "your-token" } `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
```

- **curl**：不要把中文写在 `-d '...'` 里；先保存成无 BOM 的 UTF-8 `payload.json`，再用 `--data-binary` 发送：

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Token: your-token" \
  --data-binary @payload.json
```

Python 的 `requests.post(..., json=...)` 会自动按 UTF-8 编码，是最省心的方式。2.2.1 起，若 title / summary 等字段出现连续三个以上问号，日志会记录「疑似编码丢失」告警，提示发送端检查编码。

## 让 Agent 每轮自动推送（推荐）

1. 右键托盘图标，选择「打开通知中心」。
2. 点击窗口右上角的「复制 Agent 接入指令」按钮，按钮会变为「已复制接入指令」。
3. 把剪贴板内容直接粘贴给 Agent（Claude Code、Codex、Qoder 等），发送一次即可。

复制内容包含当前端口、当前 `X-Token`、请求头、全部字段说明、**UTF-8 编码要求与 PowerShell 5.1 注意事项**、Python / PowerShell / curl 三种示例，以及规则：**每一轮任务结束都必须推送一次通知，无论成功、失败还是取消**。同时说明了 `dedupe_key`、`progress`、`require_ack`、`actions` 与 `origin` 的推荐用法。示例默认带上 `origin.pid`，Agent 粘贴后即可生成「回到终端」按钮。

> 修改 `config.json` 的端口或 token 后需要重启 AgentBell，并重新点击复制。复制动作会把 token 写入系统剪贴板，请勿在不受信任的环境粘贴。

## 一键接入 Agent Hook（2.14.0，2.16.0 起支持 Linux，2.18.0 起支持 macOS）

「运行环境 → 提醒接入」提供内置安装器，不用手写脚本。支持级别与写入位置：

| Agent | 支持级别 | 配置文件 | 事件 |
| --- | --- | --- | --- |
| Claude Code | 完整：等待 + 结束 | `~/.claude/settings.json` | `UserPromptSubmit` / `Notification` / `Stop` |
| Gemini CLI | 完整：等待 + 结束 | `~/.gemini/settings.json` | `BeforeAgent` / `Notification` / `AfterAgent` |
| Grok | 完整：等待 + 结束 | `~/.grok/hooks/agentbell.json` | `UserPromptSubmit` / `Notification` / `Stop` / `StopFailure` / `StopCancelled` |
| Codex | 部分：仅结束 | `~/.codex/config.toml` | 顶层 `notify` |

写入规则：

- JSON 配置只追加 `hooks.<Event>` 数组中的 command handler，带 `timeout: 10`；已有 handler 原样保留。Windows 的命令指向安装目录的 `hooks/agentbell-hook.ps1`；macOS / Linux 指向应用可执行文件的 `--hook --agent <id>` 子命令（macOS 为 `AgentBell.app/Contents/MacOS/AgentBell`），源码模式使用 `python run.py --hook --agent <id>`，参数经 shell 转义。
- Codex 在第一个 `[table]` 之前写入带 `# agentbell-hook` 注释的 `notify = [...]`；若已存在其他 `notify`，接入页显示「需处理」，不会覆盖。
- 接入和撤销共用标记检测：command 包含 `agentbell-hook.ps1`，或同时包含 `--hook` 与 `--agent` 且指向 AgentBell / `run.py` 的 handler 会被删除；Grok 的独立文件撤销后为空时删除该文件。
- 每次实际修改前创建同目录备份 `<文件名>.agentbell-backup-<时间戳>`；配置锁 `<文件名>.agentbell.lock` 超时 2 秒，30 秒视为陈旧，写入使用临时文件加 `os.replace`。重复接入不会重复写，也不会产生备份。
- JSON 配置写回时统一为 2 空格缩进，键顺序保留；原有缩进、空行等排版会变化。备份是原文件的原样拷贝，可能包含 MCP / API 密钥，请按敏感文件处理。

Hook 上报行为（Windows 为 PowerShell 脚本，macOS / Linux 为 `AgentBell --hook`）：

- 从数据目录的 `config.json` 读取 `port` / `token`（Windows / Linux 为安装目录，macOS 为 `~/Library/Application Support/AgentBell`），也支持 `AGENTBELL_PORT` / `AGENTBELL_TOKEN` 环境变量覆盖；只 POST 到 `http://127.0.0.1:<port>/notify`。非法 `AGENTBELL_PORT` 会被忽略；配置文件缺失且没有有效端口时直接以 0 退出，不会回退到默认 8765 误发到其他实例。
- 每次新轮次生成随机 `turn`，状态保存在同一数据目录的 `hooks/state/<agent>-<session>.json`，只含 `turn` / `waiting` / `updated`；不上传、不写会话文件。macOS 应用包保持只读。
- `UserPromptSubmit` / `BeforeAgent`：`running` + `phase=started`，静默写入时间线；`Notification`：`needs_input=true` + `waiting_input`，按提示文字归类 permission / question / rate_limit / context_limit；`Stop` / `AfterAgent`：`succeeded` + `finished`；Grok 的 `StopFailure` / `StopCancelled` 分别为 failed / canceled；Codex `agent-turn-complete` 为 succeeded。
- 通知带 `source`、`origin.pid` / `origin.working_dir`、`session_id`、`dedupe_key=agentbell-hook:<agent>:<session>:<turn>`、`run_id=hook:<agent>:<session>:<turn>`，并声明只读 `session` / `timeline` 动作。等待与结束时卡片原地更新，时间线可回看同一轮。
- 所有网络错误、配置解析错误与状态写入错误都被吞掉并以 0 退出，不会阻塞 Agent；`-DryRun`（PowerShell）/ `--dry-run`（macOS / Linux）只输出目标地址与 payload，不发送、不打印 token。

排查：

```powershell
# Windows：手工模拟一次等待事件（不会发送）
'{"hook_event_name":"Notification","session_id":"test","message":"需要允许执行 npm test"}' |
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<安装目录>\hooks\agentbell-hook.ps1" -Agent claude -DryRun
```

```bash
# Linux：手工模拟一次等待事件（不会发送）
printf '%s' '{"hook_event_name":"Notification","session_id":"test","message":"需要允许执行 npm test"}' |
  "<安装目录>/AgentBell" --hook --agent claude --dry-run
```

若服务端没有记录：确认 AgentBell 正在运行、`config.json` 的端口与 token 一致、Hook 配置中的脚本路径存在。Codex 的自定义 `notify` 冲突需要手动移除旧配置后再接入。移动 AgentBell 安装目录后，已有 Hook 仍指向旧路径，请撤销后重新接入或手动更新配置中的脚本路径。

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

PyInstaller 不能跨平台交叉编译，请在目标系统上分别打包。Windows x64 / arm64 各自在对应架构的 Windows 上构建，macOS 与 Linux 的 x64 / arm64 也需在对应架构的机器上原生构建。

### Windows

```bash
pip install -r requirements-dev.txt

# 产物：dist\AgentBell-34.exe（在原生 Arm64 Python 上构建即为 arm64 产物）
python -m PyInstaller --noconfirm --clean AgentBell34.spec
```

Windows ARM64 构建要求原生 Arm64 Python 3.12、提供 `win_arm64` 轮子的 PySide6 与支持 win_arm64 的 PyInstaller；CI 使用 `windows-11-arm` runner 与 `actions/setup-python` 的 `architecture: arm64`。x64 与 arm64 不共用产物，工作流分别上传后命名为 `AgentBell.exe` 与 `AgentBell-arm64.exe`。

把 `config.json` 复制到 exe 旁边再运行：

```bash
copy config.json dist\config.json
dist\AgentBell-34.exe
```

> 新旧版本默认共用单实例锁：若托盘中已有 AgentBell 在运行，双击 AgentBell-34 只会唤醒旧实例。切换版本前先从托盘退出旧版，再启动新 exe。工作流会自动选用编号最大的 `AgentBell<数字>.spec`，旧 spec 不需要手工维护。

打包后 `config.json`、`logs/`、`agentbell.db`、`chat/` 与 `updates/` 都位于 exe 所在目录。单文件模式首次启动需要解压到临时目录，通常会有 1–3 秒延迟。

### Linux x64 / arm64

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 产物：dist/AgentBell
python -m PyInstaller --noconfirm --clean AgentBell-linux.spec

# 四种格式（x64 机器；不传 AppImage 工具时只生成 tar.gz + deb + rpm）
python scripts/build_linux_packages.py \
  --binary dist/AgentBell \
  --version 2.20.0 \
  --arch x64 \
  --appimagetool ./appimagetool \
  --appimage-runtime ./runtime-x86_64
```

arm64 机器上重复构建，`--arch` 改为 `arm64`，并使用对应的 appimagetool / runtime。脚本输出 `AgentBell-linux-<arch>.tar.gz`、`.AppImage`、`.deb`、`.rpm` 与 `SHA256SUMS-linux-<arch>.txt`。Linux 单文件包没有 `.exe` 后缀，更新器按 `AgentBell-linux-<架构>.tar.gz` 选择资产，并且只从压缩包中提取名为 `AgentBell` 的可执行文件；压缩包内多余文件会被忽略。

AppImage 使用 `appimagetool --appimage-extract-and-run --no-appstream --runtime-file` 打包，`ARCH` 按 x86_64 / aarch64 设置；deb 用 `dpkg-deb --root-owner-group -Zxz` 构建；rpm 用 `rpmbuild -bb` 构建，spec 中关闭 strip、debuginfo 与 build-id，且不自动推导依赖。AppImage 与系统包安装不参与原地自动更新。

运行 Qt 需要 xcb 相关系统库，Debian / Ubuntu 可安装：

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
  libdbus-1-3 libfontconfig1
```

Linux 包解压后直接运行 `./AgentBell`；`config.json`、`logs/`、`agentbell.db`、`chat/` 与 `updates/` 都在可执行文件旁边。deb/rpm 安装后配置写入用户目录，程序本体位于 `/opt/agentbell/`。全局快捷键与窗口聚焦需要 X11 会话；Wayland 下通过 XDG GlobalShortcuts portal 注册快捷键，但系统不允许应用主动切换窗口焦点，相关能力会提示不可用。

### macOS x64 / arm64

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 从 SVG 生成 assets/agentbell.icns
python scripts/make_macos_icon.py

# 产物：dist/AgentBell.app
python -m PyInstaller --noconfirm --clean AgentBell-macos.spec

# ad-hoc 签名 + dmg / zip + SHA256SUMS-macos-<arch>.txt
python scripts/build_macos_packages.py \
  --app dist/AgentBell.app \
  --version 2.20.0 \
  --arch arm64

# 本地有 Developer ID 与公证凭据时（推荐发布用）
python scripts/build_macos_packages.py \
  --app dist/AgentBell.app \
  --version 2.20.0 \
  --arch arm64 \
  --identity "Developer ID Application: Example (TEAMID)" \
  --entitlements assets/macos_entitlements.plist \
  --notarize \
  --notary-key /path/AuthKey_XXXX.p8 \
  --notary-key-id XXXX \
  --notary-issuer "00000000-0000-0000-0000-000000000000"
```

`AgentBell-macos.spec` 用 `EXE` + `COLLECT` + `BUNDLE` 生成应用包，`Info.plist` 写入 `CFBundleIdentifier=com.agentbell.app`、`CFBundleShortVersionString` / `CFBundleVersion`、`LSMinimumSystemVersion=14.0`（当前依赖的 PySide6 要求 macOS 14）与 `LSUIElement=true`。图标由 `scripts/make_macos_icon.py` 通过 QSvgRenderer 渲染 16–512 像素（含 @2x）iconset，再调用系统 `iconutil` 生成 `.icns`。

`scripts/build_macos_packages.py` 校验 `.app` 存在且 `Info.plist` 版本与 `--version` 一致，然后用 `codesign --force --deep` 签应用：`--identity` 为 `-` 时做 ad-hoc 签名；传入 Developer ID 时附加 `--options runtime --timestamp` 与 `--entitlements assets/macos_entitlements.plist`。entitlements 包含 PyInstaller / Python 所需的 `allow-jit`、`allow-unsigned-executable-memory`、`disable-library-validation`，以及与 macOS 窗口聚焦（`osascript` 访问 System Events）对应的 `com.apple.security.automation.apple-events`。随后用 `ditto -c -k --sequesterRsrc --keepParent` 生成 zip，用 `hdiutil create -volname AgentBell -srcfolder ... -format UDZO` 生成 dmg，对 dmg 再做一次 Developer ID 签名，并输出 `AgentBell-macos-<arch>.dmg`、`.zip` 与 `SHA256SUMS-macos-<arch>.txt`。

传入 `--notarize` 时，脚本先用 `ditto` 把已签名应用打成临时 zip，调用 `xcrun notarytool submit --wait --output-format json`（支持 App Store Connect API Key 的 `--notary-key` / `--notary-key-id` / `--notary-issuer`，或 Apple ID 的 `--apple-id` / `--apple-password` / `--team-id`），状态必须是 `Accepted`，再用 `xcrun stapler staple` 与 `xcrun stapler validate` 把公证票据钉到 `.app`。公证完成后的 `.app` 才用于生成最终的 dmg 与 zip，因此两个资产都带票据。凭据也可以通过 `APPLE_API_KEY` / `APPLE_API_KEY_ID` / `APPLE_API_ISSUER` / `APPLE_ID` / `APPLE_APP_PASSWORD` / `APPLE_TEAM_ID` 环境变量提供；Apple ID 密码只建议用环境变量传入，避免出现在进程列表。没有证书时脚本继续输出 ad-hoc 签名包，适合本地验证。

冻结后的 macOS 应用通过 `paths.app_dir()` 把 `config.json`、`logs/`、`agentbell.db`、`chat/` 与 Hook 状态写入 `~/Library/Application Support/AgentBell`，不写入只读的 `.app`。自启写入 `~/Library/LaunchAgents/com.agentbell.app.plist`。更新使用 Release 中的 `AgentBell-macos-<arch>.zip`：下载并校验后退出程序，把旧 `.app` 备份到 `updates/`，解压并替换应用包，再重启；dmg 只用于首次安装或手动覆盖。macOS 的全局快捷键使用 Carbon `RegisterEventHotKey`，回到终端通过 `osascript` + 辅助功能权限激活窗口，空闲 / 全屏 / 锁屏分别读取 CoreGraphics、System Events 与 `CGSession` 状态，终端启动与便携 Node 安装与其他平台一致。

打包时必须保留 `uvicorn` 的 loop / HTTP 协议 / lifespan 隐藏导入，否则启动 HTTP 服务会报模块找不到。

### GitHub Actions

`.github/workflows/build.yml` 包含七个 job：

1. **Tests (Windows)**（矩阵 `windows-latest` x64 / `windows-11-arm` arm64）：用 `actions/setup-python` 的原生架构 Python 安装依赖，以 `QT_QPA_PLATFORM=offscreen` 跑完整 pytest。
2. **Tests (Linux)**（矩阵 `ubuntu-22.04` / `ubuntu-22.04-arm`）：安装 Qt 运行库后跑同一套 pytest。
3. **Tests (macOS)**（矩阵 `macos-15-intel` x64 / `macos-15` arm64）：安装依赖后跑同一套 pytest；依赖操作系统的 PowerShell 测试只在 Windows 执行。
4. **Package AgentBell.exe**（Windows 双架构）：依赖对应架构测试通过，自动选用编号最大的 `AgentBell<数字>.spec` 打包；如果配置了 `WINDOWS_CERT_PFX_BASE64`，先用 `scripts/sign_windows.py` 对产物做 SHA-256 + RFC 3161 时间戳的 Authenticode 签名与验证，再复制为 `AgentBell.exe` / `AgentBell-arm64.exe`，生成 `SHA256SUMS-windows-<arch>.txt`，上传 `AgentBell-windows-<arch>` artifact；未配置证书时输出警告并跳过签名。
5. **Package AgentBell (Linux)**（双架构矩阵）：用 `AgentBell-linux.spec` 打包；下载固定版本的 appimagetool 1.9.1 与 type2-runtime 20251108（均校验 SHA-256），调用构建脚本生成 tar.gz、AppImage、deb、rpm 与 `SHA256SUMS-linux-<arch>.txt`，上传对应 artifact。
6. **Package AgentBell.app (macOS)**（双架构矩阵）：生成 `.icns`，用 `AgentBell-macos.spec` 打包 `.app`；配置 `MACOS_CERT_P12_BASE64` 时导入临时钥匙串并解析出 Developer ID Application 身份，同时可从 `APPLE_API_KEY_BASE64` / `APPLE_API_KEY_ID` / `APPLE_API_ISSUER` 生成公证密钥；随后调用 `scripts/build_macos_packages.py` 做 Hardened Runtime 签名、公证与 staple，生成 dmg、zip 与校验文件并清理临时钥匙串。未配置证书时回退为 ad-hoc 签名，证书不完整时跳过公证并给出警告。
7. **Release**：仅当推送 `v*` 标签时运行，先校验标签与 `__version__` 一致，再用 `pattern: AgentBell-*` 下载全部 artifact 并合并为一份 `release/SHA256SUMS.txt`，用 `softprops/action-gh-release` 发布 Windows 双架构 exe、macOS 双架构 dmg / zip、Linux 双架构四种包与合并后的校验文件。

签名相关的 GitHub Secrets：

| Secret | 用途 |
| --- | --- |
| `WINDOWS_CERT_PFX_BASE64` | Windows Authenticode PFX 的 base64；配置后启用 Windows 签名 |
| `WINDOWS_CERT_PASSWORD` | PFX 密码；只在签名步骤作为环境变量传给 `signtool /p` |
| `MACOS_CERT_P12_BASE64` | Developer ID Application 证书 `.p12` 的 base64；配置后启用 macOS 签名 |
| `MACOS_CERT_PASSWORD` | `.p12` 密码 |
| `APPLE_API_KEY_BASE64` | App Store Connect API Key `.p8` 的 base64 |
| `APPLE_API_KEY_ID` / `APPLE_API_ISSUER` | API Key ID 与 Issuer ID |
| `WINDOWS_TIMESTAMP_URL`（可选） | 覆盖默认 RFC 3161 时间戳地址，脚本默认 `http://timestamp.digicert.com` |

本地签名 Windows 产物：

```powershell
$env:WINDOWS_CERT_PFX_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))
$env:WINDOWS_CERT_PASSWORD = "pfx-password"
python scripts/sign_windows.py --target dist/AgentBell-34.exe
```

也可以直接传 `--pfx cert.pfx`，或用 `--thumbprint` 使用证书存储中的证书；密码只从 `WINDOWS_CERT_PASSWORD` 读取，签名命令输出会把密码替换为 `******`。`signtool` 默认从 PATH 或 Windows SDK 目录发现，也可用 `--signtool` 指定。

发布新版本：

```bash
# 1. 修改 agentbell/__init__.py 的 __version__，例如 2.20.0
# 2. 提交并打同版本 tag（tag 去掉 v 后必须与 __version__ 完全一致）
git add -A
git commit -m "feat: 托盘点击打开通知中心并发布 2.20.0"
git tag v2.20.0
git push origin develop --tags
```

PR 和普通分支只跑测试与打包，不会发布。更新器依赖稳定的资产名（`AgentBell.exe`、`AgentBell-arm64.exe`、`AgentBell-linux-<arch>.tar.gz`），不要随意改名。

## 测试

```bash
pip install -r requirements-dev.txt

# Windows PowerShell
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest -q

# macOS / Linux / Git Bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

覆盖：鉴权与 401、字段默认值/空值/长度、非法状态、危险链接、GB18030 请求体、疑似编码丢失告警、`origin` 动作生成与上限、仅 `working_dir` 的目录名兜底、`focus` 参数校验、窗口选择排序与去重、`FocusRequest` 往返、`overlay_area` 配置校验与卡片摆放、全屏拖拽编辑器的锚点换算与保存、空/坏 JSON、超大请求体、队列满、去重合并、待确认与动作、规则匹配、等待原因/`needs_input`/时长/项目条件、规则实时配置、规则字段往返与非法时长、免打扰/全屏/会议/锁屏决策、优先级弹窗策略、弹窗模式与皮肤、全屏自定义背景图与失效回落、渠道选择、配置校验、Agent 启动的检测排序、CLI 参数与环境变量、提示词不进入命令行、桌面应用不支持提示词、启动失败与项目校验、最近项目持久化、启动记录与回到终端、SQLite 存取/搜索/统计/裁剪、通知中心筛选/搜索/统计/设置、通知来源筛选与计数联动、Agent 会话扫描与标题提取、会话记录解析/搜索/大纲/复制与导出/缺失文件兜底、设置效果预览与清理、弹窗文案/按钮/去重更新/聚合、居中与全屏弹窗互斥、锁屏暂停、单实例唤醒、自动关闭与悬停暂停、启动自动打开与会话动画收尾、标志 SVG/像素/单色与图标尺寸、启动三行时间线与收起、首次介绍的四步导航/键盘/暂停/跳过与 `onboarding_seen` 持久化、关于窗口的尺寸变体与 SVG 导出、更新仓库归一化与版本比较、Release 解析与稳定资产选择、404/网络错误映射、下载域名白名单/大小/SHA-256 校验与残留清理、源码模式拒绝替换、更新脚本环境变量与不插值路径、`chat/` 自动创建与默认项目回落、Agent 项目主页按钮、Agent 卡片双击启动、`run_events` 追加与同阶段 5 秒合并、`run_id` 生成优先级、阶段推断（开始/等待/继续/完成）、旧库迁移与孤儿事件清理、会话运行时间线读取、时间线弹窗与卡片入口、会话详情「本次运行」摘要、运行次数/成功率/P50/P90/累计等待统计、`session` / `timeline` 动作的标识校验与排序、只读动作忽略 `value`、未知动作类型 422、存储往返、通知中心按会话 ID / 运行 ID 打开成功与失败、弹窗只读动作按钮、Hook 检测与 JSON 合并/撤销、Grok 独立文件、Codex `notify` 插入与精确撤销、备份与幂等、坏 JSON 不覆盖、PowerShell 脚本的权限/问题/完成分类与轮次状态、Codex 参数式 JSON 输入、真实环回 POST 的 token 与请求体、运行环境页的接入/撤销/批量接入与 Codex 冲突提示、Linux X11 热键掩码解析与无显示环境降级、`/proc` 进程表与端口反查、Linux 终端选择与提示词不插值、跨平台 Hook 命令生成与撤销、Linux tar.gz 更新资产选择/解压/替换脚本、Linux `tar.xz` Node 安装与 `runtime` PATH 布局。

## 常见问题

**端口被占用，弹窗提示启动失败**

程序启动时会同步绑定端口，占用时直接弹窗并退出。按提示执行：

```bash
# Windows
netstat -ano | findstr :8765
# Linux
ss -ltnp | grep :8765
```

关闭占用进程，或修改 `config.json` 的 `port` 后重启。不要改成 `0.0.0.0`：AgentBell 代码内固定只绑定 `127.0.0.1`。

**`401 {"ok":false,"error":"invalid token"}`**

`X-Token` 缺失或与 `config.json` 的 `token` 不一致。若不需要鉴权，把 `token` 设为空字符串并重启；本机使用仍建议保留随机 token。

**通知里的中文变成问号 / 乱码**

这是发送端编码丢失，不是 AgentBell 显示问题。Windows PowerShell 5.1 的 `Invoke-RestMethod -Body "JSON 字符串"` 会把中文按 ANSI 代码页转成 `?`，请求到达时已经无法还原。改用：

```powershell
-Body ([System.Text.Encoding]::UTF8.GetBytes($json)) -ContentType "application/json; charset=utf-8"
```

或在 Python 里用 `requests.post(..., json=...)`；curl 则把 JSON 保存为 UTF-8 文件后 `--data-binary @payload.json`。升级到 2.2.1 后，在通知中心重新点击「复制 Agent 接入指令」并粘贴给 Agent，替换旧指令。日志里的「疑似编码丢失」告警会标出具体字段。

**Windows 下 curl 中文报 400**

优先使用 UTF-8 文件 + `--data-binary @payload.json`。AgentBell 对 GB18030 有兼容解码，但无法恢复已经变成 `?` 的文本。

**没有托盘图标**

确认桌面环境支持系统托盘（部分精简 Linux 桌面默认没有）。托盘不可用时程序会弹窗提示并以退出码 3 退出。

**弹窗没有出现**

1. 访问 `GET /health` 确认服务在运行；
2. 查看 `logs/agentbell.log` 是否有「拒绝通知」「字段校验失败」「通知延后提醒」「通知进入聚合摘要」；
3. 检查是否开启免打扰、前台是否全屏、是否命中会议进程、是否正在锁屏或息屏（锁屏消息会等到解锁后补发）；
4. 检查通知中心：`silent=true` 或 `success_popup=false` 的成功通知只进中心；
5. 已达 5 条可见上限时新通知在排队；独占全屏游戏可能覆盖任何置顶窗口。

**双击启动后没看到页面？**

2.6 起会先显示约 2.2 秒启动卡片，再打开通知中心；如果只看到托盘图标而没有窗口，检查 `open_center_on_start` 是否被改为 `false`；若托盘里已有实例，再次双击会唤醒已有实例并打开通知中心。

**首次启动的四步介绍怎么再看 / 跳过？**

四步介绍只在 `onboarding_seen=false` 时出现；点「跳过介绍」、按 `Esc` 或走到最后一步都会立即写入 `onboarding_seen=true`。想重看时把它改回 `false` 再启动；自动播放可随时点「暂停」，方向键 `←` / `→` 可前后切换。系统开启「减少动画」时仍会显示介绍，但不会播放铃声动画。

**全屏提醒没有铺满屏幕 / 背景图没显示？**

确认 `popup_mode` 为 `overlay`（或单条通知指定了 `popup_mode=overlay`）。全屏模式会在每块显示器上各铺一层，默认每块屏幕显示同一张卡片；勾选「仅在主屏显示提醒卡片」后副屏只显示背景，任意屏幕关闭后全部关闭。全屏独占游戏可能盖住任何置顶窗口。自定义背景图支持 PNG / JPG / BMP / WebP，路径失效时自动回落为皮肤渐变，可在「偏好设置 → 弹窗外观」里选择图片并点「测试」预览。卡片位置和宽度可在同一页「全屏显示区域」手动调整，或点「全屏拖拽定位…」在真实全屏预览里拖动卡片后点「保存位置」；若看起来仍在中央，确认保存后重新测试。

**待确认通知为什么一直不消失？**

`require_ack=true`、`require_ack_by_default=true` 或 `priority=critical` 的弹窗不自动关闭，必须点「知道了」；也可以在通知中心卡片上确认，或先「稍后提醒」。

**通知中心记录为什么重启后还在？**

2.0 起默认启用 SQLite 历史（`history.enabled=true`）。想恢复「退出即清空」，把该项设为 `false`，或删除 `agentbell.db`。

**Agent 会话页是空的？**

确认 `agent_sessions.enabled=true`，且本机存在 `~/.claude/projects` 或 `~/.qoder/projects`（Windows 为用户目录下的 `.claude` / `.qoder`）。扫描只读取会话元数据用于列表；没有对应目录或没有会话记录时显示空状态属于正常。可点「查看记录」阅读单个会话，内容只在本机解析，不会上传。若旧版 Qoder 会话只有 `state.json` 而没有 JSONL 记录，列表仍会显示，但可能没有可阅读的正文。可在页面右上角手动刷新，或在偏好设置里调整扫描间隔与最大条数。

**全屏拖拽定位保存后位置不对？**

拖动时顶部会显示实际坐标和尺寸；点「保存位置」后会自动换算成最近的九宫格锚点加偏移，因此手动微调后的坐标仍会精确保留。若显示器缩放或分辨率改变，位置会按新屏幕重新限制在可见范围内。卡片高度随内容变化，实际弹窗可能比预览卡片高或矮，但左上角位置保持一致。

**锁屏后通知为什么没弹出来？**

默认 `hold_when_locked=true`：锁屏、息屏、屏保期间通知会延后，解锁后再补发，避免解锁时消息已经自动消失。想恢复旧行为，在「偏好设置 → 提醒策略」关闭「锁屏时保留通知」。

**外部渠道没有收到消息？**

1. 检查渠道 `enabled`、`min_priority` 是否匹配；
2. `when_away=true` 需要先离开电脑达到 `away_idle_seconds`；
3. 查看日志中「外部渠道发送失败」的具体原因；
4. 渠道配置在设置对话框保存后立即生效，无需重启。

**全局快捷键没反应？**

可能被其他程序或桌面环境占用，日志会记录「注册全局快捷键失败」。在设置里换一个组合，或把 `hotkey` 设为空字符串关闭。Linux 只有 X11 会话支持全局快捷键，Wayland 会直接提示不支持；X11 下 `Super` / `Meta` 也可用。

**点「回到终端」没有反应 / 提示未找到窗口**

1. 确认通知是由支持该功能的版本接收：2.3.0 起支持显式 `origin`，2.9.6 起未带 `origin` 时也会按本机连接自动识别发送进程；
2. 宿主终端必须仍在运行，窗口被关闭后无法定位；
3. 只支持窗口级跳转，不会选中具体标签页；多标签请手动切换；
4. Windows 可能禁止后台程序强抢焦点，此时窗口会置前但键盘焦点仍在原处，点一下窗口即可；
5. Linux 只有 X11 会话支持窗口聚焦，Wayland 会提示需要 X11；部分窗口管理器可能只置前不授予焦点；
6. 失败时 `working_dir` 会自动复制到剪贴板，可直接粘贴到终端；
7. 历史通知无法回溯补出「回到终端」；升级后新产生的通知才会使用自动识别。也可以到「Agent 会话」卡片右侧的终端图标、会话详情右上角「回到终端」，或「Agent 启动 → 本次打开的终端」里点按钮，按项目名或 PID 匹配窗口。多个候选窗口会弹出选择菜单。

**Agent 启动页显示未安装 / 启动后没有输入提示词**

「重新检测」只检查当前进程的 `PATH` 和固定桌面安装路径；刚安装完 Agent 需要重开 AgentBell 或确认安装目录已加入 `PATH`。桌面应用（Claude Desktop / Antigravity）无法自动预填提示词，只负责打开；终端类 Agent 会把提示词作为第一个参数传入，若 Agent 本身不支持位置参数，提示词可能被忽略，可留空后进入交互界面再粘贴。提示词只通过环境变量传递，不会拼接进 shell 命令。

**双击 Agent 卡片会怎样？**

双击已安装的卡片会用当前项目目录（默认 `chat/`）和初始提示词立即启动，等同于选中后点「打开终端并开始」；双击未安装的卡片只选中并显示安装提示，不会发起启动。只想切换选择时单击即可；项目目录不存在时会停在页面提示，不会打开终端。

**重复双击会启动多个 AgentBell 吗？**

不会。第一个实例在系统临时目录持有单实例锁（`AgentBell-single-<用户摘要>.lock`）并监听同名本地通道；后续启动会让已有实例打开通知中心，然后以退出码 `0` 结束。若提示「已有实例持有单实例锁，但无法连接」，先确认托盘里是否已有 AgentBell；确认没有后，可删除提示中的锁文件再启动。

**杀毒软件误报 / 首次启动慢**

PyInstaller 单文件包常见现象。可将 exe 加入信任目录，或改用 `--onedir` 打包。请从本机源码自行构建，不要运行来路不明的同名程序。

**点「检查更新」提示没有配置仓库 / 一直检查不到新版本**

2.8.0 起更新依赖公开的 GitHub Release：安装包默认填写 `1wu-davy-2/AgentBell`，也可在「偏好设置 → 常规 → 程序更新」改成其他 `owner/repo`（粘贴 `https://github.com/owner/repo` 会自动归一化）。若清空了仓库，保存后再检查会提示填写。首次发布可参考 `.github/workflows/build.yml`：推送 `v*` 标签后自动生成带 `AgentBell.exe` 与 Linux tar.gz 的 Release。若仓库是私有的，API 需要令牌，当前版本未做私有仓库鉴权，请使用公开仓库；GitHub 接口受限时日志会记录 403/429。

**自动更新下载成功但没有替换 / 重启后还是旧版**

自动替换只在打包版（`sys.frozen`）生效，源码模式只下载到 `updates/`。打包版替换前会等待当前 PID 退出，需要 `updates/` 与安装目录可写；若安装在 `Program Files` 等受保护目录，普通权限无法覆盖 exe，请安装到可写目录或手动替换。替换失败会在 `updates/update.log` 记录原因，并把旧版 `AgentBell.exe.bak` 回滚。更新脚本由当前程序启动，若杀毒软件拦截 PowerShell 脚本，需要放行。Linux 使用 `/bin/sh` 替换脚本，确认下载的是与当前架构一致的 `AgentBell-linux-<arch>.tar.gz`；失败时同样从 `AgentBell.bak` 回滚。

**chat 目录在哪里 / 能不用吗？**

默认位于安装目录（源码模式为仓库根目录）下的 `chat/`，启动时自动创建，Agent 启动页默认选中。它只是普通文件夹，不参与 git；可随时改名、删除（下次启动重建）或在页面上改选其他项目。若安装目录不可写，启动日志会记录「无法创建 chat 目录」，此时项目目录回落到安装目录本身，仍可手动浏览其他路径。

**「项目主页」打开的是哪里？**

打开当前选中 Agent 的官方页面：CLI Agent 多为 GitHub 仓库，Claude Desktop 与 Antigravity 为官网下载页，表格见上文「Agent 启动」。只作为普通 https 链接交给系统浏览器，不会自动下载或安装。

## 安全说明

- HTTP 服务只绑定环回地址，不对局域网开放；仍建议设置随机 `X-Token`，防止本机其他程序随意弹窗。
- 通知内容只在本机进程内显示；SQLite 历史保存在本地文件，不会上传。请不要在 `summary`、`error`、`title` 中放入 token、密码等敏感信息。
- Agent 会话扫描与阅读只访问本机 Claude Code / Qoder 的会话文件：列表阶段读取元数据，点「查看记录」后才在本地解析对话正文；数据不会发送到任何外部服务，可在偏好设置中完全关闭。会话文件可能包含敏感内容，导出 Markdown 前请确认保存位置。
- 「复制 Agent 接入指令」会把当前 `X-Token` 写入系统剪贴板；剪贴板可能被本机其他程序读取，请在可信环境中使用。
- 通知动作有白名单：链接仅 `http/https`；`retry` 只允许回环地址；`path` 默认关闭，开启后也只打开指定文件；`copy` 只写入剪贴板，不执行命令；`focus` 只校验参数并置前窗口，不执行命令、不打开新终端。
- 外部渠道由你自己配置 URL/token，通知内容会发送到对应服务；启用前请确认接收方可信。
- Hook 接入只写用户级 Agent 配置，写入前展示预览并创建同目录备份，撤销只移除带 `agentbell-hook.ps1` 标记或 `--hook` / `--agent` 特征的 handler；不会执行配置中的其他命令。备份文件可能包含原有 MCP / API 密钥，请按敏感文件处理。Hook 读取本机 `config.json` 获取端口与 token（Linux 由二进制 / `run.py` 的 `--hook` 子命令处理），只向环回地址发送通知，不输出 token，状态文件只保存轮次、等待标记与更新时间。
- 单实例通道只接受「打开通知中心」请求，不执行任意命令；通道使用当前用户的本地套接字 / 命名管道。
- 更新下载只接受 HTTPS 的 GitHub 域名与 GitHub 发布资源域名，拒绝非 GitHub 重定向；安装包受 300 MB 上限、Release 记录的 `size` 与 `sha256:` digest 校验。Windows 替换脚本从环境变量读取路径与参数，不把外部文本拼接进 PowerShell 代码；Linux 由 `/bin/sh` 脚本从环境变量读取路径，重启命令用 `shlex.join` 拼接且不使用 `shell=True`，只从 tar.gz 中提取 `AgentBell`。旧版都会备份，替换失败自动回滚。
- 更新仓库默认指向本项目公开仓库，可改为其他仓库或清空；程序不会下载或执行 Release 中的任何脚本，也不会执行 npm / pip 安装命令；源码模式不自动替换。
- 请求体限制 1 MB，字段有长度上限，队列和历史都有界，避免异常调用拖垮程序。
- 本项目没有远程访问、文件上传、命令执行等能力。

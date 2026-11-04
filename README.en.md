# AgentBell

<p align="center">
  <sub>One ring per agent round, right on your desktop.</sub><br>
  <a href="README.md">简体中文</a> · <strong>English</strong> ·
  <a href="https://1wu-davy-2.github.io/agentbell-site/">Website</a>
</p>

<p align="center">
  <a href="https://github.com/1wu-davy-2/AgentBell/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/1wu-davy-2/AgentBell?label=release&color=2f6bff"></a>
  <a href="https://github.com/1wu-davy-2/AgentBell/actions/workflows/build.yml"><img alt="Build" src="https://github.com/1wu-davy-2/AgentBell/actions/workflows/build.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2f6bff"></a>
  <img alt="Platform: Windows 10/11" src="https://img.shields.io/badge/platform-Windows%2010%2F11-2f6bff">
</p>

---

AgentBell is a local-first Windows notification desk for AI agents. When an agent finishes a round, it sends one message to a loopback-only HTTP endpoint; AgentBell immediately shows a top-most card in the corner of your desktop, keeps a searchable history, and stays in the system tray after you close the window.

It does not orchestrate agents, proxy model requests, upload data, or ship a web console. The HTTP server binds to `127.0.0.1` only, and every screen is a native PySide6 window. The UI is currently Chinese-first; the HTTP API and configuration are language-neutral.

## Why AgentBell

The starting point was concrete: when Claude Code, Codex, or another agent runs a long task, you keep switching back to check whether it has finished. System notifications are too easy to miss, while a full task dashboard demands constant attention.

AgentBell does one thing well: **tell you the moment a round ends, and let you get back to the scene immediately.**

- **Notice the wait**: when an agent stalls on a permission prompt, question, rate limit, or context limit, cards show the reason; a **Waiting** sub-filter sits under Running.
- **Replay the run**: events sharing one `run_id` (start, wait, resume, finish) form an append-only timeline; cards open a timeline dialog, and statistics break down run success, P50/P90 duration, and total waiting time.
- **Walk away**: do something else while the agent works. One ring and one card when it finishes.
- **Close the loop**: a notification can focus the terminal (`origin.pid`), open the local session record or run timeline, retry a failed task, or remind you later. Read-only actions never approve permissions or continue an agent.
- **Stay quiet**: quiet hours, fullscreen/meeting suppression, lock-screen holding, digest, and success-only-in-center are all configurable.
- **Route by rules**: match on wait reason, `needs_input`, run duration, and project glob, then override priority, silence, acknowledgement, auto-close, popup, and extra channels. Later matching rules win on scalar fields, and changes apply as soon as settings are saved.
- **Local first**: loopback-only HTTP, on-device SQLite history, read-only session parsing, no cloud.
- **Stay small**: no agent orchestration, no workflow changes, no web UI. It waits in the tray and rings when it should.

## Recent updates

- **v2.13.0**: Fine-grained rules. `rules` gain `wait_reason`, `needs_input`, `min_duration_seconds` / `max_duration_seconds`, and `project` conditions, so permission waits, test projects, or runs longer than 10 minutes can be routed to different priorities and channels. Projects match the last segment of the working directory case-insensitively; durations come from `duration` with inclusive bounds, and a rule with duration bounds does not match when it is missing. Rule changes take effect on save, and locally inferred waiting notifications participate too. Hover tips are now shown only for truncated text, wrap at 32 characters, and use the light UI style instead of a full-card tooltip covering the next row.
- **v2.12.0**: Read-only actions. A notification can declare `session` / `timeline` actions, giving the popup and notification center **View record** and **Timeline** buttons that open local session data or the current run. Both read only the notification's own `session_id` / `run_id`, ignore `value`, and never run external commands. There is deliberately no approve-permission, auto-continue, or send-prompt action.
- **v2.11.0**: Run timelines. Events sharing one `run_id` are appended to `run_events`; a **Timeline** button on each card replays start, waiting, resume, and finish with relative timings. Session detail shows the latest run, and statistics add run count, run success rate, P50/P90 duration, and total waiting time. Pass an explicit `/notify` `phase`, or let AgentBell infer transitions from status changes.
- **v2.10.0**: Waiting-input reminders. When an agent stalls on a permission prompt, question, rate limit, or context limit, cards show the wait reason and Running gains a **Waiting** sub-filter. Use explicit `/notify` reports, or opt into local read-only inference from Claude Code / Qoder transcript tails; inferred cards carry an **Inferred** badge.
- **v2.9.10**: The first-run `config.json` now defaults to `1wu-davy-2/AgentBell` with the startup check enabled, so a fresh download checks Releases about 9 seconds after launch.
- **v2.9.9**: Running now auto-collects recently active agent sessions as read-only cards showing agent, project, last activity, and record count; they follow source filters and search.
- **v2.9.8**: The agent-source filter stacks with status and search; program updates can check for new versions about 9 seconds after launch.
- **v2.9.7**: **Back to terminal** now falls back to attaching the input queue and `SwitchToThisWindow` when Windows foreground lock refuses a plain raise, so keyboard focus actually lands.
- **v2.9.5–2.9.6**: Fixed a ~10-second freeze when switching status filters; missing `origin` / `source` is now resolved by tracing the local connection to the sender process.

## Screenshots

> Screenshots use demo data. The default port is `127.0.0.1:8765` and can be changed in Preferences.

| Notification center | Statistics |
| --- | --- |
| ![Notification center](docs/screenshots/notification-center.png) | ![Statistics](docs/screenshots/statistics.png) |
| **Agent launcher** | **Program update settings** |
| ![Agent launcher](docs/screenshots/agent-launcher.png) | ![Settings](docs/screenshots/settings-update.png) |

**Runtime**: install portable Node and the official agent CLIs into the program directory with one click; external tools such as cc-switch link straight to their download pages.

![Runtime](docs/screenshots/toolchain.png)

## Install

**Requirements**: Windows 10/11 for the full feature set (tray, hotkey, fullscreen/meeting detection, focus-terminal). macOS/Linux can run the basic popup and notification center from source.

### Download (recommended)

1. Open [Releases](https://github.com/1wu-davy-2/AgentBell/releases/latest) and download `AgentBell.exe`.
2. Put it in a **writable directory**, such as `D:\Tools\AgentBell`, and double-click it.
3. On first launch, `config.json`, `logs/`, `agentbell.db`, and `chat/` are created in the same directory; installing components from the **Runtime** page creates `runtime/`.
4. If SmartScreen warns about an unknown publisher, choose **More info → Run anyway**. The build is not code-signed.
5. Closing the window hides it to the tray. Use the tray menu or **退出 AgentBell** in the sidebar to quit.

The release ships `AgentBell.exe` and `SHA256SUMS.txt`. The updater only uses `AgentBell.exe`, so do not rename it. A build-numbered `AgentBell-*.exe` is a byte-identical copy; downloading `AgentBell.exe` is enough.

**Enable self-update**: the first-run `config.json` defaults to `1wu-davy-2/AgentBell` with the startup check enabled. AgentBell checks Releases about 9 seconds after launch; the tray menu and the Agent launcher page can also trigger a manual check. Packaged builds download, verify, back up, replace, and restart automatically after exit. Source mode only downloads the installer and never replaces the running Python process. If you upgraded from an older version with an empty repo, fill it in under **Preferences → General → Program update**.

### From source

Python 3.10+ is required.

```powershell
git clone git@github.com:1wu-davy-2/AgentBell.git
cd AgentBell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

On macOS / Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, then the same `pip install` and `python run.py`.

## Usage

### 1. Send your first notification

Set a `token` in `config.json` (empty disables authentication), then:

```bash
curl -X POST http://127.0.0.1:8765/notify \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Token: your-token" \
  -d '{"title":"Weekly report","status":"succeeded","summary":"12 pages generated","duration":"8m30s","source":"Claude Code"}'
```

A successful call returns HTTP 202 and a card appears in the top-right corner. Chinese text must be sent as UTF-8; on Windows PowerShell 5.1, convert the body to UTF-8 bytes first (the Chinese README has a working example). See [system-architecture.md](system-architecture.md) for curl, Python, and all fields.

### 2. Use the notification center

Filter by status and agent source in the toolbar, search by title, summary, or source; the running tab also surfaces recently active agent sessions detected by the local session scanner. Double-click the title bar to maximize or restore. Closing the window keeps the service in the tray; press `Ctrl+Alt+A` or use the tray menu to reopen it. History keeps 1,000 entries by default and powers the statistics page.

### 3. Let agents notify you automatically

1. Click **复制 Agent 接入指令** (Copy agent integration instructions) in the top-right corner.
2. Paste it into your agent (Claude Code, Codex, Qoder, etc.) once.
3. The instructions include the current port, `X-Token`, field reference, and the rule to notify **after every round**, including failures and cancellations.

Ask the agent to include `origin.pid` so notification cards can offer a **back to terminal** button. To add **View record** or **Timeline**, declare the read-only actions described in section 5.

### 4. Report a waiting agent (optional)

When an agent stops and waits for you, send a `status="running"` notification with `needs_input`:

```json
{
  "title": "Claude Code is waiting for permission",
  "status": "running",
  "needs_input": true,
  "wait_reason": "permission",
  "wait_source": "explicit",
  "session_id": "abc123",
  "summary": "Needs approval to run npm test",
  "source": "Claude Code"
}
```

`wait_reason` accepts `permission` / `question` / `rate_limit` / `context_limit` / `other` (defaults to `other`), and `needs_input=true` is only valid with `running`. Cards show the wait reason, and Running gains a **Waiting** sub-filter. A later event for the same session, or an explicit `needs_input=false`, ends the wait.

If you prefer not to report explicitly, enable local inference under **Preferences → Agent**. It only reads the tail of recent Claude Code / Qoder transcripts, requires two consecutive scans plus an idle threshold, and labels inferred cards with **Inferred**. It never writes to session files and never logs transcript content; disable it to keep explicit reporting only.

### 5. Replay a run (optional)

Events sharing one `run_id` form one run. AgentBell derives the id in this order: request `run_id` → `session:<session_id>` → `notify:<dedupe_key>` → `single:<notification id>`. Without a `phase`, the first `running` becomes **Started**, a terminal status becomes **Finished**, and wait/resume transitions are inferred automatically:

```json
{
  "title": "Weekly report",
  "status": "running",
  "session_id": "abc123",
  "summary": "Generating page 3",
  "phase": "progress"
}
```

`phase` accepts `started` / `progress` / `waiting_input` / `resumed` / `finished` / `note`. An explicit phase appends exactly one event without inference. Repeating the same phase for the same run within five seconds is merged, so progress updates do not flood the timeline. A **Timeline** button appears on cards when a run exists; session detail shows the latest run summary, and statistics expose run-level metrics. See [system-architecture.md](system-architecture.md) for all fields.

To put **View record** and **Timeline** buttons on the popup and in the notification center, ask the agent to declare read-only actions:

```json
{
  "title": "Waiting for permission",
  "status": "running",
  "session_id": "abc123",
  "run_id": "run-001",
  "actions": [
    {"kind": "session", "label": "View record"},
    {"kind": "timeline", "label": "Timeline"}
  ]
}
```

`session` requires `session_id`; `timeline` requires `run_id` (or falls back to `session_id` / `dedupe_key`). Both ignore `value` and only open read-only records inside AgentBell. A missing session or run produces a non-blocking notice and never runs an external command. AgentBell deliberately offers no approve-permission, auto-continue, or send-prompt action; approve in the terminal.

### 6. Install the agent runtime

Open the **Runtime** page and click **Install all**, or install only what you need:

- **Node**: the official LTS portable zip is verified against the official `SHASUMS256.txt` and extracted to `runtime/node`.
- **Agent CLIs**: Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw, Hermes, and Pi from their official npm packages, installed under `runtime/agents`, never into the system global directory.
- **External tools** such as cc-switch are not installed by AgentBell; their row opens the GitHub Releases download page instead.

No administrator rights are required, and the system `PATH` is left untouched; AgentBell only prepends these folders for agent detection and spawned terminals. Afterwards, click **Refresh** on the launcher page to pick up the new CLIs. DeepSeek has no official CLI, so save an API key at the bottom of the page and use **Launch Claude Code with DeepSeek** to start it with that provider.

### 7. Launch agents (optional)

The **Agent 启动** page detects Claude Code, Claude Desktop, Codex, Gemini CLI, Grok Build, OpenCode, OpenClaw, Hermes, Pi, MiniMax Code, and Antigravity.

- A `chat/` workspace is created inside the install directory and selected by default.
- Pick an agent and project, enter an optional prompt, and click **打开终端并开始**; double-clicking an installed card also launches it.
- Prompts are passed through an environment variable, never concatenated into a shell command. Desktop apps can only be opened, not pre-filled.
- **项目主页** opens the agent's official site or GitHub repository.

### 8. Return to the terminal

Include the source process in the request:

```json
{
  "title": "Weekly report",
  "status": "succeeded",
  "origin": { "pid": 12345, "window_title": "Qoder", "working_dir": "E:\\proj\\report" }
}
```

The card gets a **回到终端** button that brings the host terminal or editor window to the foreground. It focuses the window only — no tab selection, no command execution. If no window is found, the working directory is copied to the clipboard.

### 9. Tune appearance and interruptions

Preferences cover skins, popup modes, fullscreen background and card placement, quiet hours, fullscreen/meeting suppression, lock-screen holding, digest, acknowledgements, and snooze. The **测试** button previews the current configuration without writing history.

### 10. Build and release

```powershell
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean AgentBell22.spec
# Output: dist\AgentBell-22.exe
```

Pushing to `develop` runs tests and packaging. Pushing a `v*` tag verifies that the tag matches `__version__` in `agentbell/__init__.py`, then publishes a GitHub Release automatically. The workflow picks the highest-numbered `AgentBell*.spec` and copies its output to the stable `AgentBell.exe` name.

```bash
git tag v2.9.10
git push origin develop --tags
```

## License

AgentBell is released under the **MIT License**. See [LICENSE](LICENSE) for the full text.

You may use, copy, modify, merge, publish, distribute, sublicense, and sell the software, including for commercial projects, provided that the copyright and permission notice are retained. The software is provided **as is**, without warranty of any kind; you assume all risk of use.

The MIT license covers this repository's source code and documentation. Third-party dependencies (PySide6, FastAPI, uvicorn, Pydantic, and others) keep their own licenses. The AgentBell name and logo identify this project; the MIT license does not grant trademark rights.

## More docs

- [README.md](README.md): the Chinese main document — design rationale, screenshots, install and usage tutorial.
- [system-architecture.md](system-architecture.md): architecture, full configuration, HTTP API, packaging and security notes.
- [config.example.json](config.example.json): every configuration key with example values.
- [Releases](https://github.com/1wu-davy-2/AgentBell/releases): installers and checksums.

# AgentBell

<p align="center">
  <sub>One ring per agent round, right on your desktop.</sub><br>
  <a href="README.md">简体中文</a> · <strong>English</strong>
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

- **Walk away**: do something else while the agent works. One ring and one card when it finishes.
- **Close the loop**: a notification can focus the terminal (`origin.pid`), retry a failed task, or remind you later.
- **Stay quiet**: quiet hours, fullscreen/meeting suppression, lock-screen holding, digest, and success-only-in-center are all configurable.
- **Local first**: loopback-only HTTP, on-device SQLite history, read-only session parsing, no cloud.
- **Stay small**: no agent orchestration, no workflow changes, no web UI. It waits in the tray and rings when it should.

## Screenshots

> Screenshots use a separate debug port (`18776`). The default production port is `127.0.0.1:8765`.

| Notification center | Statistics |
| --- | --- |
| ![Notification center](docs/screenshots/notification-center.png) | ![Statistics](docs/screenshots/statistics.png) |
| **Agent launcher** | **Program update settings** |
| ![Agent launcher](docs/screenshots/agent-launcher.png) | ![Settings](docs/screenshots/settings-update.png) |

## Install

**Requirements**: Windows 10/11 for the full feature set (tray, hotkey, fullscreen/meeting detection, focus-terminal). macOS/Linux can run the basic popup and notification center from source.

### Download (recommended)

1. Open [Releases](https://github.com/1wu-davy-2/AgentBell/releases/latest) and download `AgentBell.exe`.
2. Put it in a **writable directory**, such as `D:\Tools\AgentBell`, and double-click it.
3. On first launch, `config.json`, `logs/`, `agentbell.db`, and `chat/` are created in the same directory.
4. If SmartScreen warns about an unknown publisher, choose **More info → Run anyway**. The build is not code-signed.
5. Closing the window hides it to the tray. Use the tray menu or **退出 AgentBell** in the sidebar to quit.

The release also includes a versioned `AgentBell-12.exe` and `SHA256SUMS.txt`. The updater only consumes the stable `AgentBell.exe` asset, so do not rename it.

**Enable self-update**: open **Preferences → General → Program update**, enter `1wu-davy-2/AgentBell`, and enable the startup check. Packaged builds download, verify, back up, replace, and restart automatically after exit. Source mode only downloads the installer and never replaces the running Python process.

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

Filter by status in the sidebar, search by title, summary, or source, and double-click the title bar to maximize or restore. Closing the window keeps the service in the tray; press `Ctrl+Alt+A` or use the tray menu to reopen it. History keeps 1,000 entries by default and powers the statistics page.

### 3. Let agents notify you automatically

1. Click **复制 Agent 接入指令** (Copy agent integration instructions) in the top-right corner.
2. Paste it into your agent (Claude Code, Codex, Qoder, etc.) once.
3. The instructions include the current port, `X-Token`, field reference, and the rule to notify **after every round**, including failures and cancellations.

Ask the agent to include `origin.pid` so notification cards can offer a **back to terminal** button.

### 4. Launch agents (optional)

The **Agent 启动** page detects Claude Code, Claude Desktop, Codex, Gemini CLI, Grok Build, OpenCode, OpenClaw, Hermes, Pi, MiniMax Code, and Antigravity.

- A `chat/` workspace is created inside the install directory and selected by default.
- Pick an agent and project, enter an optional prompt, and click **打开终端并开始**; double-clicking an installed card also launches it.
- Prompts are passed through an environment variable, never concatenated into a shell command. Desktop apps can only be opened, not pre-filled.
- **项目主页** opens the agent's official site or GitHub repository.

### 5. Return to the terminal

Include the source process in the request:

```json
{
  "title": "Weekly report",
  "status": "succeeded",
  "origin": { "pid": 12345, "window_title": "Qoder", "working_dir": "E:\\proj\\report" }
}
```

The card gets a **回到终端** button that brings the host terminal or editor window to the foreground. It focuses the window only — no tab selection, no command execution. If no window is found, the working directory is copied to the clipboard.

### 6. Tune appearance and interruptions

Preferences cover skins, popup modes, fullscreen background and card placement, quiet hours, fullscreen/meeting suppression, lock-screen holding, digest, acknowledgements, and snooze. The **测试** button previews the current configuration without writing history.

### 7. Build and release

```powershell
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean AgentBell12.spec
# Output: dist\AgentBell-12.exe
```

Pushing to `develop` runs tests and packaging. Pushing a `v*` tag verifies that the tag matches `__version__` in `agentbell/__init__.py`, then publishes a GitHub Release automatically.

```bash
git tag v2.8.2
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

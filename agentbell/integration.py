from __future__ import annotations

from .models import INTEGRATION_MODES, IntegrationMode

DEFAULT_INTEGRATION_MODE: IntegrationMode = "start_finish"

INTEGRATION_MODE_LABELS: dict[str, str] = {
    "full": "最全",
    "start_finish": "开始+结束",
    "finish_only": "仅结束",
}

INTEGRATION_MODE_SUMMARIES: dict[str, str] = {
    "full": "开始 + 关键进度 + 等待输入 + 结束",
    "start_finish": "静默开始 + 结束两条，串成时间线",
    "finish_only": "每轮只推一条结束通知，最省 token",
}

INTEGRATION_MODE_HINTS: dict[str, str] = {
    "full": "开始时静默记录，只在 30% / 60% / 90% 更新进度，等待输入单独提醒，结束收尾。",
    "start_finish": "默认推荐：开始静默记录 + 结束原地更新，时间线完整，token 开销小。",
    "finish_only": "每轮只推一条结束通知，最省 token；适合短任务或已安装 Hook 的场景。",
}


def normalize_integration_mode(value: str | None) -> IntegrationMode:
    text = (value or "").strip().lower()
    if text in INTEGRATION_MODES:
        return text  # type: ignore[return-value]
    return DEFAULT_INTEGRATION_MODE


def _headers_kwarg(token: str) -> str:
    return f'    headers={{"X-Token": "{token}"}},\n' if token else ""


def _python_example(base: str, token: str) -> str:
    return (
        "import os\n"
        "import requests\n\n"
        "requests.post(\n"
        f'    "{base}",\n'
        f"{_headers_kwarg(token)}"
        '    json={"title": "生成竞品分析报告", "status": "succeeded",\n'
        '          "summary": "已完成 12 页报告", "duration": "8m30s",\n'
        '          "source": "Qoder",\n'
        '          "origin": {"pid": os.getpid(), "working_dir": os.getcwd()}},\n'
        "    timeout=3,\n"
        ")"
    )


def _python_start_example(base: str, token: str) -> str:
    return (
        "import os\n"
        "import requests\n\n"
        'run_id = "round-20261112-1"\n'
        "requests.post(\n"
        f'    "{base}",\n'
        f"{_headers_kwarg(token)}"
        '    json={"title": "生成竞品分析报告", "status": "running",\n'
        '          "phase": "started", "silent": True,\n'
        '          "run_id": run_id, "dedupe_key": run_id,\n'
        '          "source": "Qoder",\n'
        '          "origin": {"pid": os.getpid()}},\n'
        "    timeout=3,\n"
        ")"
    )


def _python_progress_example(base: str, token: str) -> str:
    return (
        "import requests\n\n"
        'run_id = "round-20261112-1"\n'
        "requests.post(\n"
        f'    "{base}",\n'
        f"{_headers_kwarg(token)}"
        '    json={"title": "生成竞品分析报告", "status": "running",\n'
        '          "progress": 60, "run_id": run_id, "dedupe_key": run_id,\n'
        '          "source": "Qoder"},\n'
        "    timeout=3,\n"
        ")"
    )


def _powershell_example(base: str, token: str) -> str:
    headers = f'  -Headers @{{ "X-Token" = "{token}" }} `\n' if token else ""
    return (
        "$payload = @{\n"
        '  title = "生成竞品分析报告"; status = "succeeded"\n'
        '  summary = "已完成 12 页报告"; duration = "8m30s"\n'
        '  source = "Qoder"\n'
        '  origin = @{ pid = $PID; working_dir = (Get-Location).Path }\n'
        "} | ConvertTo-Json -Depth 4\n"
        f'Invoke-RestMethod -Uri "{base}" -Method Post `\n'
        '  -ContentType "application/json; charset=utf-8" `\n'
        f"{headers}"
        "  -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))"
    )


def _curl_example(base: str, token: str) -> str:
    headers = ['  -H "Content-Type: application/json; charset=utf-8"']
    if token:
        headers.append(f'  -H "X-Token: {token}"')
    return (
        f'curl -s -X POST "{base}" \\\n'
        + " \\\n".join(headers)
        + ' \\\n  --data-binary "@payload.json"'
    )


def _registration_example(
    register_base: str, token: str, mode: IntegrationMode
) -> str:
    return (
        "import requests\n\n"
        "requests.post(\n"
        f'    "{register_base}",\n'
        f"{_headers_kwarg(token)}"
        f'    json={{"agent": "Claude Code", "mode": "{mode}", "source": "manual"}},\n'
        "    timeout=3,\n"
        ")"
    )


def _auth_note(token: str) -> str:
    lines = ["  Content-Type: application/json; charset=utf-8"]
    if token:
        lines.append(f"  X-Token: {token}")
    note = "请求头：\n" + "\n".join(lines)
    if not token:
        note += "\n（当前未开启 X-Token，无需鉴权请求头）"
    return note


def _encoding_note() -> str:
    return (
        "【编码要求（重要）】所有字段必须按 UTF-8 发送。中文一旦在发送端丢掉编码，"
        "AgentBell 收到时已经是问号，无法还原。\n"
        "  - 最稳妥：用 Python requests.post(..., json=...)，库会自动按 UTF-8 编码。\n"
        "  - PowerShell 5.1：直接把 JSON 字符串传给 -Body 会按系统 ANSI 代码页转换，"
        "中文会变成 ?。必须先用 [System.Text.Encoding]::UTF8.GetBytes() 转成字节（见下方示例）。\n"
        "  - curl：不要把中文写在 -d '...' 里；先把 JSON 保存为 UTF-8 文件 payload.json，"
        '再用 --data-binary "@payload.json"。\n'
        "  - 发送前自查：标题或摘要里出现连续问号（如 ???），说明编码已经丢失，请改用上面三种方式重发。"
    )


def _mode_guidance(mode: IntegrationMode) -> str:
    if mode == "finish_only":
        return (
            "【通知规则（仅结束）】每一轮对话或任务结束时，只推送一条最终通知，然后给出最终回复。"
            "无论成功、失败还是取消都要推送；不要只在用户明确要求时推送。\n"
            '  - 不发送开始通知，不发送 status="running"，不发送进度：每轮只有这一条通知，最省 token。\n'
            "  - 这条通知就是本轮唯一的用户可见提醒：title 写本轮需求名称，summary 写一句话结论；失败时填 error。\n"
            "  - 能交给 AgentBell Hook 的结束提醒就不要自己推送，Hook 与手动推送二选一，避免一轮弹两次。\n"
            "  - 不需要 run_id、phase、progress、dedupe_key、silent；不要为了通知额外读取文件或生成过程日志。"
        )
    if mode == "start_finish":
        return (
            "【通知规则（开始+结束）】每一轮对话或任务结束时，都要向 AgentBell 推送通知，然后给出最终回复。"
            "无论成功、失败还是取消都要推送；不要只在用户明确要求时推送。\n"
            '  - 开始时：预计超过约 1 分钟的任务，先推送 status="running"、phase="started"、silent=true '
            "的通知，不弹窗，只记录开始事件。\n"
            "  - 结束时：用同一个 run_id 与 dedupe_key 推送最终通知，"
            'phase="finished"，status 为 succeeded / failed / canceled，summary 一句话结论，可带 duration。\n'
            "  - 开始与结束共用同一个 dedupe_key / run_id，AgentBell 会原地更新同一张卡片，"
            "时间线显示开始 → 完成。\n"
            "  - 不需要中途进度；短任务可以只推结束这一条。每轮用户可见通知最多一条。"
        )
    return (
        "【通知规则（最全）】每一轮对话或任务结束时，都要向 AgentBell 推送通知，然后给出最终回复。"
        "无论成功、失败还是取消都要推送；不要只在用户明确要求时推送。\n"
        '  - 开始：status="running"、phase="started"、silent=true，不弹窗。\n'
        '  - 关键进度：只在 30% / 60% / 90% 等关键节点更新，status="running"，'
        "带 progress=30 / 60 / 90，使用同一个 dedupe_key 与 run_id；不要每条命令都推。\n"
        '  - 等待输入：需要用户确认或回答时，推送 status="running"、phase="waiting_input"、'
        'needs_input=true（可带 wait_reason）；用户回复后用 phase="resumed" 继续。\n'
        "  - 结束：用同一个 dedupe_key / run_id 推送最终通知，"
        'phase="finished"；时间线显示开始 → 进度 → 等待 → 完成。\n'
        "  - 开始、进度、等待都使用 silent=true 原地更新，每轮用户可见通知最多一条。"
    )


def _field_reference(mode: IntegrationMode) -> str:
    lines = [
        "  title     必填，本轮需求的简短名称，最多 100 字（不要包含“上一轮”）",
        '  status    必填，"succeeded" 成功 / "failed" 失败 / "canceled" 取消'
        + (
            "；仅结束模式只用这三种"
            if mode == "finish_only"
            else ' / "running" 进行中'
        ),
        "  summary   本轮结论，一句话即可，最多 200 字",
        '  duration  可选，本轮耗时，例如 "8m30s"',
        "  link      可选，仅支持 http/https 链接",
        "  error     仅失败时填写，简短错误原因",
        '  priority  可选，"low" / "normal" / "high" / "critical"；失败默认 high，critical 会一直保留直到用户确认',
        "  source    建议填写，来源标识（Agent 名或任务类型），显示在弹窗与通知中心；留空时自动识别发送进程",
        "  session_id 建议填写，当前 AI 会话的稳定 ID；同一会话的多轮通知共用一个 session_id，",
        "            通知中心会据此生成「会话历史流」；无法确定时宁可不填，不要编造",
        "  origin    强烈建议每轮都填，来源位置（Windows / Linux X11），用于生成「回到终端」按钮：",
        '            {"pid": 12345, "window_title": "可选，终端窗口标题", "working_dir": "可选，项目目录"}',
        "            推荐填当前进程 PID；AgentBell 会沿父进程链找到宿主终端窗口，只聚焦窗口，不会选中具体标签页",
        "            只填 working_dir 时，会用目录名匹配标题里含该名字的终端/编辑器窗口，准确度低于 pid",
        "  require_ack 可选，true 表示需要用户点击“知道了”才算完成，适合等你决策或失败需处理的场景",
        "  actions   可选，最多 4 个按钮，每项为 "
        '{"kind":"open|copy|retry|path|center|session|timeline","label":"按钮文字","value":"参数"}',
        "            open/link 用 http(s) 链接；copy 用要复制的文本；path 用本地绝对路径；retry 只能用本机 http 回调地址",
        "            session 打开内置会话记录（需填写 session_id）；timeline 打开本次运行时间线（需 run_id 或 session_id/dedupe_key）",
        "            这两类动作只读，不使用 value；AgentBell 不会批准权限、自动继续或发送提示词，审批必须回到终端完成",
        "  popup_mode / popup_skin / expires_in / channel_types / bypass_quiet_hours 可选，分别控制弹出方式、皮肤、过期时间和外部渠道",
    ]
    if mode == "finish_only":
        return "\n".join(lines)
    lines.extend(
        [
            "  dedupe_key 同一轮多次更新使用相同的去重键，AgentBell 会原地更新卡片而不是重复弹出",
            "  run_id    本轮运行的稳定标识；开始与结束使用同一个 run_id 才会串成一条时间线",
            '  phase     可选，"started" / "progress" / "waiting_input" / "resumed" / "finished" / "note" / "compaction"；显式传入时只记录该阶段',
            "  silent    可选，true 表示只记录到通知中心，不弹窗；开始与进度更新必须设为 true",
        ]
    )
    if mode == "full":
        lines.extend(
            [
                '  progress  可选，0-100，配合 status="running" 和 dedupe_key 展示任务进度；只在关键节点更新',
                '  needs_input 可选，仅与 status="running" 一起用；等待用户确认或回答时设为 true',
                '  wait_reason 可选，"permission" / "question" / "rate_limit" / "context_limit" / "other"',
                '  wait_source 可选，"explicit"（Agent 明确上报）/ "inferred"（本地推断）',
            ]
        )
    return "\n".join(lines)


def _session_note(mode: IntegrationMode) -> str:
    note = (
        "【会话关联】每轮请填写 session_id（Agent 当前会话的稳定 ID），"
        "通知中心会据此生成「会话历史流」，把整段会话的多轮通知与事件串成连续记录。"
        "未填写时，只有同一 Agent、同一项目目录且 30 分钟内有唯一活跃会话时才会自动关联，"
        "并标记为「自动关联」；无法唯一确定时宁可不关联，旧通知不会事后补关联。"
    )
    if mode == "finish_only":
        return note + "仅结束模式不需要 run_id / dedupe_key / phase / silent，也不要在中途更新。"
    return note


def build_agent_instructions(
    port: int, token: str = "", mode: str = DEFAULT_INTEGRATION_MODE
) -> str:
    """Text copied to the clipboard and handed to an AI agent."""
    selected = normalize_integration_mode(mode)
    label = INTEGRATION_MODE_LABELS[selected]
    summary = INTEGRATION_MODE_SUMMARIES[selected]
    base = f"http://127.0.0.1:{port}/notify"
    register_base = f"http://127.0.0.1:{port}/integration/report"

    guidance = _mode_guidance(selected)
    fields = _field_reference(selected)
    auth_note = _auth_note(token)
    encoding_note = _encoding_note()
    session_note = _session_note(selected)
    registration_example = _registration_example(register_base, token, selected)

    if selected == "finish_only":
        examples = (
            "每轮唯一的一条通知（任选一种写法）：\n\n"
            f"Python：\n{_python_example(base, token)}\n\n"
            f"PowerShell：\n{_powershell_example(base, token)}\n\n"
            f'curl（payload.json 必须是无 BOM 的 UTF-8 文件）：\n{_curl_example(base, token)}'
        )
    elif selected == "start_finish":
        examples = (
            "开始通知（同一轮先发，silent 不弹窗）：\n"
            f"{_python_start_example(base, token)}\n\n"
            "结束通知（与开始使用同一个 run_id / dedupe_key，原地更新同一张卡片）：\n"
            f"{_python_example(base, token)}\n\n"
            f"PowerShell（结束通知）：\n{_powershell_example(base, token)}\n\n"
            f'curl（结束通知，payload.json 必须是无 BOM 的 UTF-8 文件）：\n{_curl_example(base, token)}'
        )
    else:
        examples = (
            f"开始通知（silent 不弹窗）：\n{_python_start_example(base, token)}\n\n"
            f"关键进度（只在 30% / 60% / 90% 发）：\n{_python_progress_example(base, token)}\n\n"
            f"结束通知（与开始使用同一个 run_id / dedupe_key）：\n{_python_example(base, token)}\n\n"
            f"PowerShell（结束通知）：\n{_powershell_example(base, token)}\n\n"
            f'curl（结束通知，payload.json 必须是无 BOM 的 UTF-8 文件）：\n{_curl_example(base, token)}'
        )

    return f"""你正在接入 AgentBell，这是一个运行在本机的桌面通知工具。请在本轮对话中遵守下面的规则；不要把这些规则写入项目文件、CLAUDE.md、Agent 设置或 Hook 配置。

【当前接入模式】{label}（{selected}）— {summary}

{guidance}

{encoding_note}

接口：POST {base}
{auth_note}

请求体字段（JSON）：
{fields}

{session_note}

{examples}

【接入登记】第一次接入时，调用一次下面的接口登记模式（本次为「{label}」）：
POST {register_base}
鉴权与 /notify 相同。请求体：{{"agent": "你的 Agent 名称", "mode": "{selected}", "source": "manual"}}
  agent   必填，Agent 名称，例如 "Claude Code" / "Qoder" / "Codex"
  mode    必填，本次接入模式："full" / "start_finish" / "finish_only"
  source  可选，登记来源，例如 "manual" / "hook" / "plugin"

Python：
{registration_example}

登记失败可以忽略，不影响通知；同一 Agent 重新登记会覆盖旧模式，结果显示在 AgentBell「运行环境 → 提醒接入」。

【接入边界】
1. 不要把本规则写入项目文件、CLAUDE.md、Agent 设置或 Hook 配置；Hook 只能由我在 AgentBell 里预览并确认后安装。
2. 通知只用于桌面提醒；AgentBell 不会批准权限、自动继续或发送提示词，审批必须回到终端完成。
3. 推送失败不要中断主任务，也不要反复重试，只需在回复末尾提醒我“AgentBell 通知未送达”。
4. summary 只写结论，不要粘贴过程日志；不要把普通成功都设成 critical，也不要每轮使用 require_ack。
5. 如果 AgentBell Hook 已经负责结束提醒（0 token），就不要再手动推送结束通知；开始 / 进度仍按本模式执行。

完成后，AgentBell 会在桌面弹出提醒，并在“通知中心”保留记录；你可以在通知中心搜索、统计成功率和耗时。"""

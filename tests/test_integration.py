from __future__ import annotations

from agentbell.integration import build_agent_instructions


def test_instructions_include_endpoint_auth_and_per_round_rule():
    text = build_agent_instructions(8765, "secret-token")

    assert "http://127.0.0.1:8765/notify" in text
    assert "X-Token: secret-token" in text
    assert '"X-Token": "secret-token"' in text
    assert "每一轮" in text
    assert "不要只在用户明确要求时推送" in text
    assert '"succeeded"' in text
    assert '"failed"' in text
    assert '"canceled"' in text
    assert "UTF-8" in text
    assert "PowerShell 5.1" in text
    assert "[System.Text.Encoding]::UTF8.GetBytes($payload)" in text
    assert "requests.post(" in text
    assert '--data-binary "@payload.json"' in text
    assert "连续问号" in text
    assert '"origin"' in text
    assert "os.getpid()" in text
    assert "origin = @{ pid = $PID" in text
    assert '"source": "Qoder"' in text
    assert 'source = "Qoder"' in text
    assert "自动识别发送进程" in text
    assert "回到终端" in text
    assert "不会选中具体标签页" in text
    assert "summary" in text
    assert "AgentBell" in text
    assert "run_id" in text
    assert "phase" in text
    assert "phase=\"started\"" in text
    assert "phase=\"finished\"" in text
    assert "silent=true" in text
    assert "同一个 dedupe_key / run_id" in text
    assert "时间线显示开始 → 完成" in text


def test_instructions_follow_custom_port_and_omit_token_header_when_disabled():
    text = build_agent_instructions(9911, "")

    assert "http://127.0.0.1:9911/notify" in text
    assert "X-Token: " not in text
    assert '"X-Token"' not in text
    assert "-Headers @{" not in text
    assert "未开启 X-Token" in text
    assert "每一轮" in text


def test_finish_only_mode_keeps_only_one_final_notification():
    text = build_agent_instructions(8765, "", "finish_only")

    assert "【当前接入模式】仅结束（finish_only）" in text
    assert "只推送一条最终通知" in text
    assert 'phase="started"' not in text
    assert 'phase="finished"' not in text
    assert '"progress":' not in text
    assert "run_id = " not in text
    assert "开始通知（" not in text
    assert "http://127.0.0.1:8765/integration/report" in text
    assert '"mode": "finish_only"' in text


def test_start_finish_mode_uses_started_and_finished_pair():
    text = build_agent_instructions(9911, "tok", "start_finish")

    assert "【当前接入模式】开始+结束（start_finish）" in text
    assert 'phase="started"' in text
    assert 'phase="finished"' in text
    assert "不需要中途进度" in text
    assert '"mode": "start_finish"' in text
    assert 'phase="waiting_input"' not in text
    assert '"progress": 60' not in text


def test_full_mode_adds_progress_and_waiting_fields():
    text = build_agent_instructions(9911, "", "full")

    assert "【当前接入模式】最全（full）" in text
    assert "30% / 60% / 90%" in text
    assert '"progress": 60' in text
    assert "needs_input=true" in text
    assert "wait_reason" in text
    assert '"mode": "full"' in text


def test_unknown_mode_falls_back_to_start_finish():
    text = build_agent_instructions(8765, "", "bogus")

    assert "【当前接入模式】开始+结束（start_finish）" in text

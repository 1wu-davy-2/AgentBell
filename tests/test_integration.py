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
    assert "回到终端" in text
    assert "不会选中具体标签页" in text
    assert "summary" in text
    assert "AgentBell" in text


def test_instructions_follow_custom_port_and_omit_token_header_when_disabled():
    text = build_agent_instructions(9911, "")

    assert "http://127.0.0.1:9911/notify" in text
    assert "X-Token: " not in text
    assert '"X-Token"' not in text
    assert "-Headers @{" not in text
    assert "未开启 X-Token" in text
    assert "每一轮" in text

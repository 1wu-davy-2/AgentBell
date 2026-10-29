from __future__ import annotations

from agentbell.integration import build_agent_instructions


def test_instructions_include_endpoint_auth_and_per_round_rule():
    text = build_agent_instructions(8765, "secret-token")

    assert "http://127.0.0.1:8765/notify" in text
    assert "X-Token: secret-token" in text
    assert "每一轮" in text
    assert "不要只在用户明确要求时推送" in text
    assert '"succeeded"' in text
    assert '"failed"' in text
    assert '"canceled"' in text
    assert "curl" in text
    assert '  -H "Content-Type: application/json" \\\n' in text
    assert '  -H "X-Token: secret-token" \\\n' in text
    assert "summary" in text
    assert "AgentBell" in text


def test_instructions_follow_custom_port_and_omit_token_header_when_disabled():
    text = build_agent_instructions(9911, "")

    assert "http://127.0.0.1:9911/notify" in text
    assert "X-Token: " not in text
    assert "未开启 X-Token" in text
    assert '  -H "Content-Type: application/json" \\\n' in text
    assert "每一轮" in text

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from agentbell.attention import AttentionScanner, detect_wait
from agentbell.config import AttentionConfig


def assistant(content, uuid: str = "a1", **extra) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {"role": "assistant", "content": content},
        **extra,
    }


def user(content) -> dict:
    return {"type": "user", "message": {"role": "user", "content": content}}


def tool_use(name: str = "Bash", tool_id: str = "t1") -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": name,
        "input": {"command": "npm test"},
    }


def tool_result(tool_id: str = "t1") -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": "ok",
    }


def test_detects_pending_tool_use_as_permission_wait():
    signal = detect_wait(
        [user("跑一下测试"), assistant([tool_use()])]
    )
    assert signal is not None
    assert signal.reason == "permission"
    assert signal.fingerprint == "a1"


def test_tool_result_after_tool_use_is_not_waiting():
    assert (
        detect_wait(
            [
                user("跑一下测试"),
                assistant([tool_use()]),
                user([tool_result()]),
            ]
        )
        is None
    )


def test_detects_question_text():
    signal = detect_wait(
        [user("看看报告"), assistant([{"type": "text", "text": "需要我继续执行吗？"}])]
    )
    assert signal is not None
    assert signal.reason == "question"


def test_detects_rate_limit_and_context_limit():
    rate = detect_wait(
        [assistant([{"type": "text", "text": "API Error: 429 Too Many Requests"}])]
    )
    assert rate is not None and rate.reason == "rate_limit"

    context = detect_wait(
        [
            assistant(
                [
                    {
                        "type": "text",
                        "text": "API Error: maximum context length exceeded",
                    }
                ]
            )
        ]
    )
    assert context is not None and context.reason == "context_limit"


def test_normal_completion_is_not_waiting():
    assert (
        detect_wait(
            [assistant([{"type": "text", "text": "报告已写入 report.md。"}])]
        )
        is None
    )


def test_sidechain_entries_are_ignored():
    assert detect_wait([assistant([tool_use()], isSidechain=True)]) is None


def write_session(path: Path, entries: list[dict], age_seconds: float = 35) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))


def build_scanner(tmp_path: Path, **overrides) -> AttentionScanner:
    config = AttentionConfig(
        idle_seconds=10, poll_interval_seconds=5, **overrides
    )
    return AttentionScanner(
        config,
        logging.getLogger("agentbell.tests"),
        claude_root=tmp_path / "claude",
        qoder_root=tmp_path / "qoder",
        codex_root=tmp_path / "codex",
        gemini_root=tmp_path / "gemini",
        grok_root=tmp_path / "grok",
    )


def test_scanner_confirms_two_scans_then_resolves(tmp_path):
    path = tmp_path / "claude" / "E--work-demo" / "session-abc.jsonl"
    write_session(
        path,
        [user("跑一下测试"), assistant([tool_use()], uuid="assistant-1")],
    )
    scanner = build_scanner(tmp_path)

    first, first_resolved = scanner.scan_once(now_monotonic=1000.0)
    assert first == []
    assert first_resolved == []

    second, _ = scanner.scan_once(now_monotonic=1005.0)
    assert len(second) == 1
    detection = second[0]
    assert detection.agent == "claude"
    assert detection.reason == "permission"
    assert detection.dedupe_key.startswith("wait:claude:session-abc:")
    assert detection.title == "Claude Code 等待权限确认"
    assert detection.project == "demo"
    assert detection.idle_seconds >= 30

    third, _ = scanner.scan_once(now_monotonic=1010.0)
    assert third == []

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(user([tool_result()])) + "\n")
    fresh, resolved = scanner.scan_once(now_monotonic=1015.0)
    assert fresh == []
    assert len(resolved) == 1
    assert resolved[0].dedupe_key == detection.dedupe_key


def test_scanner_honours_idle_threshold(tmp_path):
    path = tmp_path / "claude" / "proj" / "session-fresh.jsonl"
    write_session(path, [assistant([tool_use()])], age_seconds=2)
    scanner = build_scanner(tmp_path)

    assert scanner.scan_once(now_monotonic=1000.0)[0] == []
    assert scanner.scan_once(now_monotonic=1005.0)[0] == []
    assert scanner.scan_once(now_monotonic=1010.0)[0] == []


def test_scanner_respects_agent_filter_and_disable(tmp_path):
    path = tmp_path / "claude" / "proj" / "session-off.jsonl"
    write_session(path, [assistant([tool_use()])])
    scanner = build_scanner(tmp_path, agents=("qoder",))
    assert scanner.scan_once(now_monotonic=1000.0)[0] == []
    assert scanner.scan_once(now_monotonic=1005.0)[0] == []

    disabled = build_scanner(tmp_path, enabled=False)
    assert disabled.scan_once(now_monotonic=1000.0) == ([], [])
    assert disabled.scan_once(now_monotonic=1005.0) == ([], [])


def test_scanner_reads_large_tail(tmp_path):
    path = tmp_path / "claude" / "proj" / "session-big.jsonl"
    filler = [user("x" * 1000) for _ in range(400)]
    write_session(
        path,
        filler + [assistant([tool_use()], uuid="last-entry")],
    )
    assert path.stat().st_size > 256 * 1024
    scanner = build_scanner(tmp_path)
    scanner.scan_once(now_monotonic=1000.0)
    detections, _ = scanner.scan_once(now_monotonic=1005.0)
    assert len(detections) == 1
    assert detections[0].fingerprint == "last-entry"


def test_scanner_ignores_stale_sessions(tmp_path):
    path = tmp_path / "claude" / "proj" / "session-old.jsonl"
    write_session(path, [assistant([tool_use()])], age_seconds=3600)
    scanner = build_scanner(tmp_path)
    assert scanner.scan_once(now_monotonic=1000.0)[0] == []
    assert scanner.scan_once(now_monotonic=1005.0)[0] == []


def write_jsonl(path: Path, entries: list[dict], age_seconds: float = 35) -> None:
    write_session(path, entries, age_seconds=age_seconds)


def test_scanner_infers_codex_gemini_and_grok_waits(tmp_path):
    codex_path = (
        tmp_path / "codex" / "2026" / "11" / "07" / "rollout-codex1.jsonl"
    )
    write_jsonl(
        codex_path,
        [
            {
                "type": "response_item",
                "ordinal": 1,
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "rules"}],
                },
            },
            {
                "type": "response_item",
                "ordinal": 2,
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>cwd</environment_context>",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "ordinal": 3,
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "看看报告"}],
                },
            },
            {
                "type": "response_item",
                "ordinal": 4,
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "需要我继续执行吗？"}
                    ],
                },
            },
        ],
    )

    gemini_path = tmp_path / "gemini" / "proj-alpha" / "chats" / "session-1.json"
    gemini_path.parent.mkdir(parents=True, exist_ok=True)
    gemini_path.write_text(
        json.dumps(
            {
                "sessionId": "gem-1",
                "messages": [
                    {"type": "user", "content": [{"text": "看看报告"}]},
                    {
                        "type": "gemini",
                        "content": [{"text": "需要我继续执行吗？"}],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stamp = time.time() - 35
    os.utime(gemini_path, (stamp, stamp))

    grok_path = (
        tmp_path
        / "grok"
        / "%2Fhome%2Fuser%2Fdemo"
        / "session-grok1"
        / "chat_history.jsonl"
    )
    write_jsonl(
        grok_path,
        [
            {"type": "user", "content": "看看报告", "prompt_index": 1},
            {
                "type": "assistant",
                "content": [{"type": "text", "text": "需要我继续执行吗？"}],
            },
            {
                "type": "reasoning",
                "summary": [{"text": "internal reasoning"}],
            },
        ],
    )

    scanner = build_scanner(tmp_path)
    assert scanner.scan_once(now_monotonic=1000.0)[0] == []
    detections, _ = scanner.scan_once(now_monotonic=1005.0)
    by_agent = {item.agent: item for item in detections}
    assert set(by_agent) == {"codex", "gemini", "grok"}

    assert by_agent["codex"].reason == "question"
    assert by_agent["codex"].dedupe_key.startswith("wait:codex:rollout-codex1:")
    assert by_agent["codex"].title == "Codex 等待回答"

    assert by_agent["gemini"].reason == "question"
    assert by_agent["gemini"].project == "proj-alpha"
    assert by_agent["gemini"].title == "Gemini 等待回答"

    assert by_agent["grok"].reason == "question"
    assert by_agent["grok"].dedupe_key.startswith("wait:grok:session-grok1:")
    assert by_agent["grok"].project == "demo"

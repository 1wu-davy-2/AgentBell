from __future__ import annotations

import json
import logging
from datetime import datetime

from agentbell.config import UsageConfig
from agentbell.usage import (
    UsageScanner,
    estimate_cost,
    format_tokens,
    match_pricing,
    parse_usage_line,
)


def _claude_line(
    message_id: str,
    model: str = "claude-sonnet-4-5",
    *,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read: int = 200,
    cache_write: int = 100,
    timestamp: str | None = None,
) -> str:
    body = {
        "type": "assistant",
        "timestamp": timestamp or datetime.now().astimezone().isoformat(),
        "message": {
            "id": message_id,
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }
    return json.dumps(body, ensure_ascii=False) + "\n"


def _codex_line(input_tokens: int = 300, output_tokens: int = 100) -> str:
    body = {
        "type": "event_msg",
        "timestamp": datetime.now().astimezone().isoformat(),
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 50,
                    "cache_write_input_tokens": 10,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": 40,
                },
                "total_token_usage": {
                    "input_tokens": 99999,
                    "output_tokens": 99999,
                },
            },
        },
    }
    return json.dumps(body) + "\n"


def _scanner(tmp_path, **config_kwargs) -> UsageScanner:
    claude = tmp_path / "claude-projects"
    codex = tmp_path / ".codex" / "sessions"
    qoder = tmp_path / ".qoder" / "projects"
    for root in (claude, codex, qoder):
        root.mkdir(parents=True, exist_ok=True)
    return UsageScanner(
        UsageConfig(**config_kwargs),
        logging.getLogger("agentbell.tests.usage"),
        claude_root=claude,
        qoder_root=qoder,
        codex_root=codex,
    )


def test_parse_claude_and_codex_lines():
    record = parse_usage_line(_claude_line("m1"), "claude")
    assert record is not None
    assert record.model == "claude-sonnet-4-5"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.cache_read_tokens == 200
    assert record.cache_write_tokens == 100
    assert record.total_tokens == 1800
    assert record.record_id == "m1"

    record = parse_usage_line(_codex_line(), "codex")
    assert record is not None
    assert record.input_tokens == 300
    assert record.output_tokens == 100
    assert record.cache_read_tokens == 50
    assert record.cache_write_tokens == 10
    assert record.total_tokens == 460

    assert parse_usage_line("{}", "claude") is None
    assert parse_usage_line("not json", "claude") is None


def test_pricing_matches_longest_prefix_and_formats():
    pricing = {
        "claude": {"input": 1.0},
        "claude-sonnet": {"input": 3.0, "output": 15.0},
    }
    assert match_pricing("claude-sonnet-4-5", pricing) == pricing["claude-sonnet"]
    assert match_pricing("claude-opus", pricing) == pricing["claude"]
    assert match_pricing("gpt-5", pricing) is None

    record = parse_usage_line(_claude_line("m1"), "claude")
    assert record is not None
    assert estimate_cost(record, pricing) == (1000 * 3.0 + 500 * 15.0) / 1_000_000

    assert format_tokens(999) == "999"
    assert format_tokens(12_345) == "12.3K"
    assert format_tokens(1_234_567) == "1.23M"


def test_scan_once_aggregates_and_dedupes(tmp_path):
    scanner = _scanner(
        tmp_path,
        daily_token_budget=2400,
        daily_cost_budget=1.0,
        pricing={
            "claude-sonnet": {
                "input": 3.0,
                "output": 15.0,
                "cache_read": 0.3,
                "cache_write": 3.75,
            },
            "codex": {"input": 1.0, "output": 2.0, "cache_read": 0.1},
        },
    )
    claude_file = scanner._claude_root / "demo" / "session.jsonl"
    claude_file.parent.mkdir(parents=True)
    claude_file.write_text(
        _claude_line("m1")
        + _claude_line("m1", input_tokens=9999, output_tokens=9999)
        + _claude_line("m2", input_tokens=100, output_tokens=50, cache_read=0, cache_write=0),
        encoding="utf-8",
    )
    codex_file = scanner._codex_root / "2026" / "rollout.jsonl"
    codex_file.parent.mkdir(parents=True)
    codex_file.write_text(_codex_line(), encoding="utf-8")

    summary = scanner.scan_once()
    assert summary.total_tokens == 2410
    assert summary.input_tokens == 1400
    assert summary.output_tokens == 650
    assert summary.cache_read_tokens == 250
    assert summary.cache_write_tokens == 110
    assert abs(summary.cost_usd - 0.01249) < 1e-9
    assert summary.unpriced_tokens == 0
    assert summary.alert_level == "exceeded"
    assert summary.alert_key.startswith("usage:")

    with open(claude_file, "a", encoding="utf-8") as handle:
        handle.write(_claude_line("m3", input_tokens=1000, output_tokens=0, cache_read=0, cache_write=0))
    summary = scanner.scan_once()
    assert summary.total_tokens == 3410
    assert summary.input_tokens == 2400

    claude_file.write_text(
        _claude_line("m4", input_tokens=5, output_tokens=5, cache_read=0, cache_write=0),
        encoding="utf-8",
    )
    summary = scanner.scan_once()
    assert summary.total_tokens == 470
    assert summary.input_tokens == 305


def test_unpriced_models_and_budgets(tmp_path):
    scanner = _scanner(tmp_path)
    claude_file = scanner._claude_root / "session.jsonl"
    claude_file.write_text(
        _claude_line("m1", model="unknown-model"), encoding="utf-8"
    )
    summary = scanner.scan_once()
    assert summary.total_tokens == 1800
    assert summary.cost_usd == 0.0
    assert summary.unpriced_tokens == 1800
    assert summary.token_percent is None
    assert summary.cost_percent is None
    assert summary.alert_level == ""

    scanner = _scanner(
        tmp_path,
        daily_token_budget=2000,
        alert_percent=80,
    )
    summary = scanner.scan_once()
    assert summary.alert_level == "warning"
    assert "预警" in summary.alert_message


def test_old_records_are_ignored(tmp_path):
    scanner = _scanner(tmp_path)
    old = datetime(2020, 1, 1, 12, 0, 0).astimezone().isoformat()
    claude_file = scanner._claude_root / "session.jsonl"
    claude_file.write_text(
        _claude_line("old", timestamp=old), encoding="utf-8"
    )
    summary = scanner.scan_once()
    assert summary.total_tokens == 0


def test_usage_ledger_persists_and_deduplicates(tmp_path):
    from agentbell.usage import UsageLedger, UsageReport

    path = tmp_path / "usage.sqlite3"
    ledger = UsageLedger(path, logging.getLogger("agentbell.tests.usage"))
    try:
        report = UsageReport(
            report_id="keep-1",
            source="deepseek",
            model="deepseek-chat",
            input_tokens=120,
            output_tokens=30,
        )
        assert ledger.add(report)[0] is True
        assert ledger.add(report)[0] is False
        assert ledger.version == 1
    finally:
        ledger.close()

    reopened = UsageLedger(path, logging.getLogger("agentbell.tests.usage"))
    try:
        assert reopened.records(datetime.now().astimezone().date())[0].total_tokens == 150
        assert reopened.add(report)[0] is False
    finally:
        reopened.close()


def test_usage_ledger_auto_id_matches_content():
    from agentbell.usage import default_report_id

    now = datetime.now().astimezone()
    first = default_report_id("deepseek", "m", now, 1, 2, 0, 0)
    second = default_report_id("deepseek", "m", now, 1, 2, 0, 0)
    assert first == second
    assert first.startswith("auto:")

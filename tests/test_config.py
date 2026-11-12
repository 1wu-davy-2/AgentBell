from __future__ import annotations

import json

import pytest

from agentbell.config import (
    AgentLauncherConfig,
    ConfigError,
    config_to_dict,
    load_config,
    save_config,
)


def test_missing_config_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    config, created = load_config(path)
    assert created is True
    assert config.port == 8765
    assert config.token == ""
    assert config.auto_close_seconds == 30
    assert config.autostart is False
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["port"] == 8765
    assert data["token"] == ""
    assert data["auto_close_seconds"] == 30
    assert data["autostart"] is False
    assert data["quiet_hours"] == {
        "enabled": False,
        "start": "22:00",
        "end": "08:00",
        "allow_critical": True,
    }
    assert data["onboarding_seen"] is False
    assert data["digest"] == {
        "enabled": True,
        "threshold": 4,
        "window_seconds": 60,
    }
    assert data["history"]["enabled"] is True
    assert data["history"]["retention_days"] == 0
    assert data["rules"] == []
    assert data["channels"] == []
    assert data["hotkey"] == "Ctrl+Alt+A"


def test_valid_config_is_loaded(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "port": 9001,
                "token": "s3cret",
                "auto_close_seconds": 0,
                "autostart": True,
            }
        ),
        encoding="utf-8",
    )
    config, created = load_config(path)
    assert created is False
    assert config.port == 9001
    assert config.token == "s3cret"
    assert config.auto_close_seconds == 0
    assert config.autostart is True
    assert config.auth_enabled is True


def test_history_retention_days_is_parsed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"history": {"retention_days": 30}}), encoding="utf-8"
    )
    config, _ = load_config(path)
    assert config.history.retention_days == 30

    path.write_text(
        json.dumps({"history": {"retention_days": -1}}), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="retention_days"):
        load_config(path)


def test_missing_fields_use_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"port": 8888}', encoding="utf-8")
    config, _ = load_config(path)
    assert config.port == 8888
    assert config.auto_close_seconds == 30
    assert config.token == ""


@pytest.mark.parametrize(
    "payload, message",
    [
        ("{oops", "格式错误"),
        ("[]", "JSON 对象"),
        ('{"port": 0}', "port"),
        ('{"port": 70000}', "port"),
        ('{"port": true}', "port"),
        ('{"port": "abc"}', "port"),
        ('{"auto_close_seconds": -1}', "auto_close_seconds"),
        ('{"autostart": "yes"}', "autostart"),
        ('{"onboarding_seen": "maybe"}', "onboarding_seen"),
        ('{"token": 123}', "token"),
    ],
)
def test_invalid_config_is_rejected(tmp_path, payload, message):
    path = tmp_path / "config.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_numeric_strings_are_normalized(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"port": "9100", "auto_close_seconds": "12", "autostart": "true"}',
        encoding="utf-8",
    )
    config, _ = load_config(path)
    assert config.port == 9100
    assert config.auto_close_seconds == 12
    assert config.autostart is True


def test_new_popup_and_session_defaults(tmp_path):
    path = tmp_path / "config.json"
    config, _ = load_config(path)
    assert config.popup_mode == "corner"
    assert config.popup_skin == "midnight"
    assert config.overlay_image == ""
    assert config.overlay_area.anchor == "center"
    assert config.overlay_area.width == 0
    assert config.overlay_area.offset_x == 0
    assert config.overlay_area.offset_y == 0
    assert config.overlay_area.margin == 32
    assert config.overlay_area.card_on_primary_only is False
    assert config.open_center_on_start is True
    assert config.hold_when_locked is True
    assert config.agent_sessions.enabled is True
    assert config.agent_sessions.scan_interval_seconds == 120
    assert config.agent_sessions.max_sessions == 80
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["popup_mode"] == "corner"
    assert data["popup_skin"] == "midnight"
    assert data["overlay_image"] == ""
    assert data["overlay_area"] == {
        "anchor": "center",
        "width": 0,
        "offset_x": 0,
        "offset_y": 0,
        "margin": 32,
        "card_on_primary_only": False,
    }
    assert data["open_center_on_start"] is True
    assert data["hold_when_locked"] is True
    assert data["agent_sessions"] == {
        "enabled": True,
        "scan_interval_seconds": 120,
        "max_sessions": 80,
    }


def test_popup_and_session_values_are_case_insensitive(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "popup_mode": "CENTER",
                "popup_skin": "Light",
                "overlay_image": r"C:\images\bg.png",
                "overlay_area": {
                    "anchor": "BOTTOM_RIGHT",
                    "width": 720,
                    "offset_x": -40,
                    "offset_y": "-24",
                    "margin": 48,
                    "card_on_primary_only": True,
                },
                "open_center_on_start": False,
                "hold_when_locked": False,
                "agent_sessions": {
                    "enabled": False,
                    "scan_interval_seconds": 45,
                    "max_sessions": 120,
                },
            }
        ),
        encoding="utf-8",
    )
    config, _ = load_config(path)
    assert config.popup_mode == "center"
    assert config.popup_skin == "light"
    assert config.overlay_image == r"C:\images\bg.png"
    assert config.overlay_area.anchor == "bottom_right"
    assert config.overlay_area.width == 720
    assert config.overlay_area.offset_x == -40
    assert config.overlay_area.offset_y == -24
    assert config.overlay_area.margin == 48
    assert config.overlay_area.card_on_primary_only is True
    assert config.open_center_on_start is False
    assert config.hold_when_locked is False
    assert config.agent_sessions.enabled is False
    assert config.agent_sessions.scan_interval_seconds == 45
    assert config.agent_sessions.max_sessions == 120


@pytest.mark.parametrize(
    "payload, message",
    [
        ('{"popup_mode": "bogus"}', "popup_mode"),
        ('{"popup_skin": "bogus"}', "popup_skin"),
        ('{"open_center_on_start": "sometimes"}', "open_center_on_start"),
        ('{"overlay_image": 12}', "overlay_image"),
        ('{"overlay_area": {"anchor": "bogus"}}', "overlay_area.anchor"),
        ('{"overlay_area": {"width": 100}}', "overlay_area.width"),
        ('{"overlay_area": {"width": 2000}}', "overlay_area.width"),
        ('{"overlay_area": {"margin": -1}}', "overlay_area.margin"),
        ('{"overlay_area": {"offset_x": 5000}}', "overlay_area.offset_x"),
        ('{"overlay_area": {"card_on_primary_only": "maybe"}}', "card_on_primary_only"),
        ('{"overlay_area": "center"}', "overlay_area"),
        ('{"agent_sessions": {"scan_interval_seconds": 5}}', "scan_interval_seconds"),
        ('{"agent_sessions": {"max_sessions": 0}}', "max_sessions"),
    ],
)
def test_invalid_popup_and_session_config_is_rejected(tmp_path, payload, message):
    path = tmp_path / "config.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_onboarding_seen_round_trip(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"onboarding_seen": "true"}', encoding="utf-8")
    config, _ = load_config(path)
    assert config.onboarding_seen is True

    save_config(path, config)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["onboarding_seen"] is True
    loaded, _ = load_config(path)
    assert loaded.onboarding_seen is True


def test_save_config_round_trip(tmp_path):
    path = tmp_path / "nested" / "config.json"
    from agentbell.config import AppConfig

    save_config(path, AppConfig(port=9000, token="abc", auto_close_seconds=10))
    loaded, created = load_config(path)
    assert created is False
    assert loaded.port == 9000
    assert loaded.token == "abc"
    assert loaded.auto_close_seconds == 10


def test_agent_launcher_defaults_and_round_trip(tmp_path):
    path = tmp_path / "config.json"
    config, _ = load_config(path)
    assert config.agent_launcher.recent_projects == ()
    assert config.agent_launcher.last_agent == ""

    from dataclasses import replace

    updated = replace(
        config,
        agent_launcher=AgentLauncherConfig(
            recent_projects=(r"E:\work\demo", r"E:\work\other"),
            last_agent="claude-code",
        ),
    )
    save_config(path, updated)

    loaded, _ = load_config(path)
    assert loaded.agent_launcher.recent_projects == (
        r"E:\work\demo",
        r"E:\work\other",
    )
    assert loaded.agent_launcher.last_agent == "claude-code"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["agent_launcher"] == {
        "recent_projects": [r"E:\work\demo", r"E:\work\other"],
        "last_agent": "claude-code",
    }


def test_agent_launcher_accepts_tuples_from_config_to_dict(tmp_path):
    from dataclasses import replace

    from agentbell.config import config_from_dict, config_to_dict

    path = tmp_path / "config.json"
    config, _ = load_config(path)
    config = replace(
        config,
        agent_launcher=AgentLauncherConfig(
            recent_projects=(r"E:\work\demo",), last_agent="codex"
        ),
    )

    restored = config_from_dict(config_to_dict(config))

    assert restored.agent_launcher.recent_projects == (r"E:\work\demo",)
    assert restored.agent_launcher.last_agent == "codex"


@pytest.mark.parametrize(
    "payload,message",
    [
        (
            json.dumps(
                {
                    "agent_launcher": {
                        "recent_projects": [
                            rf"E:\project{index}" for index in range(7)
                        ]
                    }
                }
            ),
            "recent_projects",
        ),
        (
            json.dumps({"agent_launcher": {"recent_projects": r"E:\x"}}),
            "recent_projects",
        ),
        (
            json.dumps(
                {"agent_launcher": {"recent_projects": ["x" * 261]}}
            ),
            "recent_projects",
        ),
        (json.dumps({"agent_launcher": {"last_agent": 5}}), "last_agent"),
    ],
)
def test_agent_launcher_config_is_validated(tmp_path, payload, message):
    path = tmp_path / "config.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_update_defaults_repo_normalization_and_round_trip(tmp_path):
    from dataclasses import replace

    from agentbell.config import UpdateConfig, config_from_dict, config_to_dict

    path = tmp_path / "config.json"
    config, _ = load_config(path)
    assert config.update.enabled is True
    assert config.update.repo == "1wu-davy-2/AgentBell"
    assert config.update.check_on_start is True

    updated = replace(
        config,
        update=UpdateConfig(
            enabled=False,
            repo="acme/AgentBell",
            check_on_start=False,
        ),
    )
    save_config(path, updated)
    loaded, _ = load_config(path)
    assert loaded.update.enabled is False
    assert loaded.update.repo == "acme/AgentBell"
    assert loaded.update.check_on_start is False
    assert json.loads(path.read_text(encoding="utf-8"))["update"] == {
        "enabled": False,
        "repo": "acme/AgentBell",
        "check_on_start": False,
    }

    payload = config_to_dict(config)
    payload["update"] = {
        "enabled": True,
        "repo": "https://github.com/acme/AgentBell.git",
        "check_on_start": True,
    }
    restored = config_from_dict(payload)
    assert restored.update.repo == "acme/AgentBell"

    payload["update"] = {
        "enabled": True,
        "repo": "",
        "check_on_start": True,
    }
    assert config_from_dict(payload).update.repo == ""


@pytest.mark.parametrize(
    "payload,message",
    [
        (json.dumps({"update": {"repo": "acme"}}), "update.repo"),
        (json.dumps({"update": {"repo": "acme/agent bell"}}), "update.repo"),
        (json.dumps({"update": {"enabled": "yes"}}), "enabled"),
        (json.dumps({"update": {"check_on_start": 1}}), "check_on_start"),
        (json.dumps({"update": "on"}), "update"),
    ],
)
def test_update_section_validation(tmp_path, payload, message):
    from agentbell.config import config_from_dict

    with pytest.raises(ConfigError, match=message):
        config_from_dict(json.loads(payload))


def test_rule_routing_fields_round_trip(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "name": "权限等待高优",
                        "needs_input": True,
                        "wait_reason": "permission",
                        "project": "demo-*",
                        "min_duration_seconds": 600,
                        "max_duration_seconds": 604800,
                        "priority": "critical",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config, _ = load_config(path)
    rule = config.rules[0]
    assert rule.needs_input is True
    assert rule.wait_reason == "permission"
    assert rule.project == "demo-*"
    assert rule.min_duration_seconds == 600
    assert rule.max_duration_seconds == 604800
    assert rule.priority == "critical"

    from agentbell.config import config_to_dict

    data = config_to_dict(config)["rules"][0]
    assert data["wait_reason"] == "permission"
    assert data["needs_input"] is True
    assert data["project"] == "demo-*"
    assert data["min_duration_seconds"] == 600
    assert data["max_duration_seconds"] == 604800

    save_config(path, config)
    reloaded, _ = load_config(path)
    assert reloaded.rules == config.rules


@pytest.mark.parametrize(
    "rule,message",
    [
        ({"wait_reason": "approval"}, "wait_reason"),
        ({"needs_input": "yes"}, "needs_input"),
        ({"min_duration_seconds": -1}, "min_duration_seconds"),
        ({"max_duration_seconds": 604801}, "max_duration_seconds"),
        ({"min_duration_seconds": 600, "max_duration_seconds": 60}, "不能大于"),
        ({"project": 123}, "project"),
    ],
)
def test_invalid_rule_routing_fields(tmp_path, rule, message):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_voice_and_usage_defaults(tmp_path):
    path = tmp_path / "config.json"
    config, created = load_config(path)
    assert created is True
    assert config.voice.enabled is False
    assert config.voice.min_priority == "normal"
    assert config.voice.rate == 0
    assert config.voice.max_chars == 120
    assert config.usage.enabled is True
    assert config.usage.scan_interval_seconds == 300
    assert config.usage.daily_token_budget == 0
    assert config.usage.daily_cost_budget == 0.0
    assert config.usage.alert_percent == 80
    assert config.usage.pricing == {}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["voice"]["template"] == "{title}，{status_label}"
    assert data["usage"]["pricing"] == {}


def test_voice_and_usage_values_are_parsed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "voice": {
                    "enabled": True,
                    "min_priority": "high",
                    "rate": -4,
                    "include_summary": False,
                    "max_chars": 200,
                    "template": "{title} {status_label} {duration}",
                },
                "usage": {
                    "enabled": False,
                    "scan_interval_seconds": 120,
                    "daily_token_budget": 2000000,
                    "daily_cost_budget": "5.5",
                    "alert_percent": 70,
                    "pricing": {
                        "claude-sonnet": {
                            "input": 3,
                            "output": 15.5,
                            "cache_read": 0.3,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    config, _ = load_config(path)
    assert config.voice.enabled is True
    assert config.voice.min_priority == "high"
    assert config.voice.rate == -4
    assert config.voice.include_summary is False
    assert config.voice.max_chars == 200
    assert config.usage.enabled is False
    assert config.usage.daily_cost_budget == 5.5
    assert config.usage.pricing["claude-sonnet"]["output"] == 15.5
    saved = json.loads(json.dumps(config_to_dict(config), ensure_ascii=False))
    assert saved["voice"]["rate"] == -4
    assert saved["usage"]["pricing"]["claude-sonnet"]["cache_read"] == 0.3


@pytest.mark.parametrize(
    "section,message",
    [
        ({"voice": {"rate": 20}}, "voice.rate"),
        ({"voice": {"min_priority": "urgent"}}, "min_priority"),
        ({"voice": {"template": "{unknown}"}}, "voice.template"),
        ({"usage": {"daily_token_budget": -1}}, "daily_token_budget"),
        ({"usage": {"daily_cost_budget": -0.1}}, "daily_cost_budget"),
        ({"usage": {"alert_percent": 0}}, "alert_percent"),
        ({"usage": {"scan_interval_seconds": 10}}, "scan_interval_seconds"),
        ({"usage": {"pricing": {"demo": {"input": -1}}}}, "usage.pricing.demo.input"),
        ({"usage": {"pricing": []}}, "usage.pricing"),
    ],
)
def test_invalid_voice_and_usage_values(tmp_path, section, message):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(section), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)

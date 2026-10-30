from __future__ import annotations

import json

import pytest

from agentbell.config import ConfigError, load_config, save_config


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
    assert data["digest"] == {
        "enabled": True,
        "threshold": 4,
        "window_seconds": 60,
    }
    assert data["history"]["enabled"] is True
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
    assert config.hold_when_locked is True
    assert config.agent_sessions.enabled is True
    assert config.agent_sessions.scan_interval_seconds == 120
    assert config.agent_sessions.max_sessions == 80
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["popup_mode"] == "corner"
    assert data["popup_skin"] == "midnight"
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
    assert config.hold_when_locked is False
    assert config.agent_sessions.enabled is False
    assert config.agent_sessions.scan_interval_seconds == 45
    assert config.agent_sessions.max_sessions == 120


@pytest.mark.parametrize(
    "payload, message",
    [
        ('{"popup_mode": "bogus"}', "popup_mode"),
        ('{"popup_skin": "bogus"}', "popup_skin"),
        ('{"agent_sessions": {"scan_interval_seconds": 5}}', "scan_interval_seconds"),
        ('{"agent_sessions": {"max_sessions": 0}}', "max_sessions"),
    ],
)
def test_invalid_popup_and_session_config_is_rejected(tmp_path, payload, message):
    path = tmp_path / "config.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_save_config_round_trip(tmp_path):
    path = tmp_path / "nested" / "config.json"
    from agentbell.config import AppConfig

    save_config(path, AppConfig(port=9000, token="abc", auto_close_seconds=10))
    loaded, created = load_config(path)
    assert created is False
    assert loaded.port == 9000
    assert loaded.token == "abc"
    assert loaded.auto_close_seconds == 10

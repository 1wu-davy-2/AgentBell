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
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "port": 8765,
        "token": "",
        "auto_close_seconds": 30,
        "autostart": False,
    }


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


def test_save_config_round_trip(tmp_path):
    path = tmp_path / "nested" / "config.json"
    from agentbell.config import AppConfig

    save_config(path, AppConfig(port=9000, token="abc", auto_close_seconds=10))
    loaded, created = load_config(path)
    assert created is False
    assert loaded.port == 9000
    assert loaded.token == "abc"
    assert loaded.auto_close_seconds == 10

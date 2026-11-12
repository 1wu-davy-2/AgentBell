from __future__ import annotations

import logging
import threading
import time

import pytest

from agentbell import voice
from agentbell.models import Notification

LOGGER = logging.getLogger("test-voice")


def _notification(**overrides) -> Notification:
    data = {
        "id": "n1",
        "title": "构建任务",
        "status": "succeeded",
    }
    data.update(overrides)
    return Notification(**data)


def _which(*available: str):
    found = set(available)
    return lambda name: name if name in found else None


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _FakeProcess:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.terminated = False
        self._done = threading.Event()

    def wait(self, timeout: float | None = None) -> int:
        self._done.wait(timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self._done.set()


class _FakePopen:
    def __init__(self) -> None:
        self.processes: list[_FakeProcess] = []

    def __call__(self, command, **_kwargs) -> _FakeProcess:
        process = _FakeProcess(command)
        self.processes.append(process)
        return process


# ---------- command construction ----------


def test_windows_command_and_rate():
    settings = voice.VoiceSettings(rate=3)
    result = voice.build_command(
        "测试文本", settings, platform_name="windows", which=_which("powershell")
    )
    assert result is not None
    command, path = result
    try:
        assert command[:6] == [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
        ]
        script = command[6]
        assert script.startswith("Add-Type -AssemblyName System.Speech;")
        assert "System.Speech.Synthesis.SpeechSynthesizer" in script
        assert "$s.Rate=3;" in script
        assert script.endswith("$s.Speak([IO.File]::ReadAllText($args[0]))")
        assert command[7] == str(path)
        assert path.read_text(encoding="utf-8") == "测试文本"
    finally:
        path.unlink(missing_ok=True)


def test_windows_rate_is_clamped_and_pwsh_fallback():
    settings = voice.VoiceSettings(rate=25)
    result = voice.build_command(
        "测试", settings, platform_name="windows", which=_which("pwsh")
    )
    assert result is not None
    command, path = result
    try:
        assert command[0] == "pwsh"
        assert "$s.Rate=10;" in command[6]
    finally:
        path.unlink(missing_ok=True)


def test_macos_command_and_rate():
    settings = voice.VoiceSettings(rate=2)
    result = voice.build_command(
        "测试文本", settings, platform_name="macos", which=_which("say")
    )
    assert result is not None
    command, path = result
    try:
        assert command[:4] == ["say", "-r", "230", "-f"]
        assert command[4] == str(path)
    finally:
        path.unlink(missing_ok=True)


def test_linux_spd_say_command():
    settings = voice.VoiceSettings(rate=-3)
    result = voice.build_command(
        "测试文本", settings, platform_name="linux", which=_which("spd-say")
    )
    assert result is not None
    command, path = result
    try:
        assert command[:4] == ["spd-say", "-r", "-30", "-f"]
        assert command[4] == str(path)
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("engine", "expected"),
    [("espeak-ng", "185"), ("espeak", "185")],
)
def test_linux_espeak_fallbacks(engine, expected):
    settings = voice.VoiceSettings(rate=1)
    result = voice.build_command(
        "测试文本", settings, platform_name="linux", which=_which(engine)
    )
    assert result is not None
    command, path = result
    try:
        assert command[:4] == [engine, "-s", expected, "-f"]
        assert command[4] == str(path)
    finally:
        path.unlink(missing_ok=True)


def test_linux_espeak_rate_mapping():
    settings = voice.VoiceSettings(rate=0)
    result = voice.build_command(
        "测试文本", settings, platform_name="linux", which=_which("espeak-ng")
    )
    assert result is not None
    command, path = result
    try:
        assert command[1:4] == ["-s", "175", "-f"]
    finally:
        path.unlink(missing_ok=True)


def test_build_command_missing_engine_returns_none():
    settings = voice.VoiceSettings()
    for platform in ("windows", "macos", "linux"):
        assert (
            voice.build_command(
                "测试", settings, platform_name=platform, which=lambda name: None
            )
            is None
        )


def test_build_command_empty_text_returns_none():
    assert (
        voice.build_command(
            "   ", voice.VoiceSettings(), platform_name="linux", which=_which("spd-say")
        )
        is None
    )


# ---------- text formatting ----------


def test_temp_file_contains_full_text():
    settings = voice.VoiceSettings(
        template="{title}，{status_label}，耗时{duration}，来自{source}"
    )
    notification = _notification(
        duration="3m20s",
        source="codex",
        summary="单元测试全部通过",
    )
    text = voice.format_voice_text(notification, settings)
    assert text == "构建任务，已完成，耗时3m20s，来自codex。单元测试全部通过"

    result = voice.build_command(
        text, settings, platform_name="linux", which=_which("spd-say")
    )
    assert result is not None
    _, path = result
    try:
        assert path.read_text(encoding="utf-8") == text
    finally:
        path.unlink(missing_ok=True)


def test_include_summary_toggle():
    notification = _notification(summary="修复了登录问题")
    with_summary = voice.format_voice_text(notification, voice.VoiceSettings())
    assert with_summary == "构建任务，已完成。修复了登录问题"

    without = voice.format_voice_text(
        notification, voice.VoiceSettings(include_summary=False)
    )
    assert without == "构建任务，已完成"


def test_max_chars_truncation():
    notification = _notification(title="非常长的任务标题" * 10)
    text = voice.format_voice_text(
        notification, voice.VoiceSettings(max_chars=12)
    )
    assert len(text) == 12
    assert text.endswith("…")


def test_invalid_template_falls_back():
    notification = _notification()
    for template in ("{title} {unknown}", "{", "{0}"):
        assert (
            voice.format_voice_text(
                notification, voice.VoiceSettings(template=template)
            )
            == "构建任务，已完成"
        )


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("succeeded", "已完成"),
        ("failed", "失败"),
        ("canceled", "已取消"),
        ("running", "进行中"),
    ],
)
def test_status_labels(status, label):
    notification = _notification(status=status)
    text = voice.format_voice_text(
        notification, voice.VoiceSettings(include_summary=False)
    )
    assert text == f"构建任务，{label}"


# ---------- skip rules ----------


@pytest.mark.parametrize(
    ("settings", "notification"),
    [
        (voice.VoiceSettings(enabled=False), _notification()),
        (
            voice.VoiceSettings(enabled=True),
            _notification(silent=True, require_ack=False),
        ),
        (
            voice.VoiceSettings(enabled=True, min_priority="normal"),
            _notification(priority="low"),
        ),
        (
            voice.VoiceSettings(enabled=True),
            _notification(status="running", needs_input=False),
        ),
    ],
)
def test_skip_rules(monkeypatch, settings, notification):
    monkeypatch.setattr(
        voice, "build_command", lambda *args, **kwargs: pytest.fail("不应构造命令")
    )
    player = voice.VoicePlayer(lambda: settings, LOGGER, popen=_FakePopen())

    assert player.speak(notification) is False


def test_silent_with_ack_still_speaks(monkeypatch, tmp_path):
    path = tmp_path / "voice.txt"
    path.write_text("测试", encoding="utf-8")
    popen = _FakePopen()
    monkeypatch.setattr(
        voice, "build_command", lambda *args, **kwargs: (["tts", str(path)], path)
    )
    player = voice.VoicePlayer(
        lambda: voice.VoiceSettings(enabled=True), LOGGER, popen=popen
    )

    notification = _notification(silent=True, require_ack=True)
    assert player.speak(notification) is True
    assert len(popen.processes) == 1
    player.stop()
    assert _wait_until(lambda: not path.exists())


# ---------- VoicePlayer ----------


def test_player_starts_terminates_previous_and_cleans(monkeypatch, tmp_path):
    paths = [tmp_path / "voice-1.txt", tmp_path / "voice-2.txt"]
    for path in paths:
        path.write_text("测试", encoding="utf-8")
    builds = iter(
        [(["tts", str(paths[0])], paths[0]), (["tts", str(paths[1])], paths[1])]
    )
    monkeypatch.setattr(voice, "build_command", lambda *args, **kwargs: next(builds))
    popen = _FakePopen()
    player = voice.VoicePlayer(
        lambda: voice.VoiceSettings(enabled=True), LOGGER, popen=popen
    )

    assert player.speak(_notification()) is True
    assert len(popen.processes) == 1
    assert popen.processes[0].terminated is False

    assert player.speak(_notification(id="n2")) is True
    assert len(popen.processes) == 2
    assert popen.processes[0].terminated is True

    assert _wait_until(lambda: not paths[0].exists())
    assert not paths[0].exists()

    player.stop()
    assert popen.processes[1].terminated is True
    assert _wait_until(lambda: not paths[1].exists())
    assert not paths[1].exists()


def test_player_cleans_temp_when_spawn_fails(monkeypatch, tmp_path):
    path = tmp_path / "voice.txt"
    path.write_text("测试", encoding="utf-8")
    monkeypatch.setattr(
        voice, "build_command", lambda *args, **kwargs: (["tts", str(path)], path)
    )

    def boom(*args, **kwargs):
        raise OSError("没有可用的音频设备")

    player = voice.VoicePlayer(
        lambda: voice.VoiceSettings(enabled=True), LOGGER, popen=boom
    )

    assert player.speak(_notification()) is False
    assert not path.exists()


def test_player_missing_engine_returns_false():
    player = voice.VoicePlayer(
        lambda: voice.VoiceSettings(enabled=True),
        LOGGER,
        platform_name="linux",
        which=lambda name: None,
    )

    assert player.speak(_notification()) is False
    player.stop()


def test_player_settings_provider_failure_returns_false():
    def boom() -> voice.VoiceSettings:
        raise RuntimeError("配置损坏")

    player = voice.VoicePlayer(boom, LOGGER, popen=_FakePopen())

    assert player.speak(_notification()) is False

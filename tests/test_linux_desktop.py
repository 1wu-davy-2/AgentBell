from __future__ import annotations

import os
import sys

import pytest

from agentbell import linux_desktop as ld


def test_modifier_masks_parses_common_hotkeys():
    assert ld.modifier_masks("Ctrl+Alt+A") == (
        ld._CONTROL_MASK | ld._MOD1_MASK,
        "A",
    )
    assert ld.modifier_masks("Super+space") == (ld._MOD4_MASK, "space")
    assert ld.modifier_masks("Ctrl+Shift+F12") == (
        ld._CONTROL_MASK | ld._SHIFT_MASK,
        "F12",
    )
    assert ld.modifier_masks("ctrl+alt+enter") == (
        ld._CONTROL_MASK | ld._MOD1_MASK,
        "Return",
    )


def test_modifier_masks_rejects_invalid_specs():
    assert ld.modifier_masks("") is None
    assert ld.modifier_masks("A") is None
    assert ld.modifier_masks("Ctrl+") is None
    assert ld.modifier_masks("Ctrl+Alt+A+B") is None
    assert ld.modifier_masks("Ctrl+Alt+F25") is None
    assert ld.modifier_masks("Hyper+A") is None


def test_session_detection_is_safe_without_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert ld.is_wayland() is False
    assert ld.x11_available() is False
    assert ld.session_type() in {"x11", "wayland", "tty", "unknown", ""}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc")
def test_process_table_contains_current_process():
    table = ld.process_table()
    assert os.getpid() in table
    parent, name = table[os.getpid()]
    assert parent > 0
    assert name


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc")
def test_client_pid_rejects_invalid_ports():
    assert ld.client_pid_for_port(0) is None
    assert ld.client_pid_for_port(-1, 8765) is None
    assert ld.client_pid_for_port(65000, 65001) is None

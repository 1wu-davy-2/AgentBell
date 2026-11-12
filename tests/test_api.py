from __future__ import annotations

import json
import logging
import queue
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import agentbell.api as api_module
from agentbell import window_focus
from agentbell.agent_sessions import AgentSession, SessionReportRegistry
from agentbell.api import MAX_BODY_BYTES, create_app
from agentbell.config import AppConfig, ConfigRef, RuleConfig
from agentbell.models import Notification
from agentbell.session_link import SessionLinker
from agentbell.storage import NotificationStorage
from agentbell.store import NotificationStore
from agentbell.usage import UsageLedger

TOKEN = "test-secret"


@pytest.fixture(autouse=True)
def _stub_window_snapshot(monkeypatch):
    monkeypatch.setattr(api_module.window_focus, "snapshot_focus", lambda pid: None)
    monkeypatch.setattr(api_module.window_focus, "client_pid", lambda *args: None)
    monkeypatch.setattr(api_module.window_focus, "sender_label", lambda pid: "")


def build(
    maxsize: int = 20,
    store: NotificationStore | None = None,
    config: AppConfig | None = None,
    config_source=None,
    ledger=None,
    sessions=None,
    session_linker=None,
):
    inbox: queue.Queue[Notification] = queue.Queue(maxsize=maxsize)
    source = config_source
    if source is None:
        source = config if config is not None else AppConfig(
            port=8765, token=TOKEN, auto_close_seconds=30, autostart=False
        )
    app = create_app(
        source,
        inbox,
        logging.getLogger("agentbell.tests"),
        store=store,
        ledger=ledger,
        sessions=sessions,
        session_linker=session_linker,
    )
    return TestClient(app), inbox


def auth_headers() -> dict[str, str]:
    return {"X-Token": TOKEN, "Content-Type": "application/json"}


def test_health_is_public():
    client, _ = build()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["auth"] is True


def test_rejects_missing_or_wrong_token_before_parsing_body():
    client, inbox = build()
    response = client.post(
        "/notify", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "invalid token"}
    assert inbox.empty()

    response = client.post(
        "/notify",
        json={"title": "x"},
        headers={"X-Token": "wrong", "Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert inbox.empty()


def test_accepts_full_payload():
    client, inbox = build()
    payload = {
        "title": "生成竞品分析报告",
        "status": "succeeded",
        "summary": "已完成 12 页报告，包含 5 个竞品对比。",
        "duration": "8m30s",
        "link": "https://example.com/report",
        "error": None,
    }
    response = client.post("/notify", json=payload, headers=auth_headers())
    assert response.status_code == 202
    body = response.json()
    assert body["ok"] is True
    assert body["queued"] is True
    assert len(body["id"]) == 12

    notification = inbox.get_nowait()
    assert notification.id == body["id"]
    assert notification.title == payload["title"]
    assert notification.status == "succeeded"
    assert notification.summary == payload["summary"]
    assert notification.duration == "8m30s"
    assert notification.link == "https://example.com/report"
    assert notification.headline == "上一轮【生成竞品分析报告】已完成，请查看"


def test_origin_adds_focus_action():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "带来源的任务",
            "status": "succeeded",
            "origin": {
                "pid": 4321,
                "window_title": "Windows Terminal",
                "working_dir": "E:\\work\\demo",
            },
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.actions[0].kind == "focus"
    assert notification.actions[0].label == "回到终端"
    assert json.loads(notification.actions[0].value) == {
        "pid": 4321,
        "window_title": "Windows Terminal",
        "working_dir": "E:\\work\\demo",
    }


def test_origin_snapshots_host_window(monkeypatch):
    client, inbox = build()
    monkeypatch.setattr(
        api_module.window_focus,
        "snapshot_focus",
        lambda pid: window_focus.FocusChoice(
            pid=2468, title="Qoder", executable="qoder.exe", value=""
        ),
    )
    response = client.post(
        "/notify",
        json={
            "title": "清理完成",
            "status": "succeeded",
            "origin": {"pid": 13012, "working_dir": "E:\\code_repo\\argus"},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert json.loads(notification.actions[0].value) == {
        "pid": 2468,
        "window_title": "Qoder",
        "working_dir": "E:\\code_repo\\argus",
    }


def test_origin_working_dir_only_uses_folder_name(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={
                "title": "只有目录",
                "origin": {"working_dir": "E:\\work\\demo"},
            },
            headers=auth_headers(),
        )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.actions[0].kind == "focus"
    assert json.loads(notification.actions[0].value) == {
        "pid": None,
        "window_title": "demo",
        "working_dir": "E:\\work\\demo",
    }
    assert "origin 缺少 pid 和 window_title" not in caplog.text


def test_empty_origin_is_ignored(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={"title": "空来源", "origin": {}},
            headers=auth_headers(),
        )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert all(action.kind != "focus" for action in notification.actions)
    assert "origin 缺少 pid 和 window_title" in caplog.text


def test_missing_origin_autodetects_sender(monkeypatch, caplog):
    client, inbox = build()
    monkeypatch.setattr(
        api_module.window_focus, "client_pid", lambda port, server_port=None: 13012
    )
    monkeypatch.setattr(
        api_module.window_focus,
        "snapshot_focus",
        lambda pid: window_focus.FocusChoice(
            pid=12304, title="Qoder", executable="qoder.exe", value=""
        ),
    )
    monkeypatch.setattr(api_module.window_focus, "sender_label", lambda pid: "Qoder")
    with caplog.at_level(logging.INFO):
        response = client.post(
            "/notify",
            json={"title": "自动识别来源", "status": "succeeded"},
            headers=auth_headers(),
        )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.source == "Qoder"
    assert notification.actions[0].kind == "focus"
    assert notification.actions[0].label == "回到终端"
    assert json.loads(notification.actions[0].value) == {
        "pid": 12304,
        "window_title": "Qoder",
        "working_dir": "",
    }
    assert "已自动识别发送进程 pid=13012" in caplog.text


def test_autodetect_fills_pid_for_working_dir_only_origin(monkeypatch):
    client, inbox = build()
    monkeypatch.setattr(
        api_module.window_focus, "client_pid", lambda port, server_port=None: 13012
    )
    monkeypatch.setattr(
        api_module.window_focus,
        "snapshot_focus",
        lambda pid: window_focus.FocusChoice(
            pid=12304, title="Qoder", executable="qoder.exe", value=""
        ),
    )
    monkeypatch.setattr(api_module.window_focus, "sender_label", lambda pid: "Qoder")
    response = client.post(
        "/notify",
        json={
            "title": "只有目录",
            "origin": {"working_dir": "E:\\work\\demo"},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.source == "Qoder"
    assert json.loads(notification.actions[0].value) == {
        "pid": 12304,
        "window_title": "Qoder",
        "working_dir": "E:\\work\\demo",
    }


def test_explicit_source_and_origin_are_not_overridden(monkeypatch):
    client, inbox = build()
    monkeypatch.setattr(
        api_module.window_focus, "client_pid", lambda port, server_port=None: 13012
    )
    monkeypatch.setattr(api_module.window_focus, "sender_label", lambda pid: "Qoder")
    response = client.post(
        "/notify",
        json={
            "title": "显式来源",
            "status": "succeeded",
            "source": "deploy-bot",
            "origin": {"pid": 4321},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.source == "deploy-bot"
    assert json.loads(notification.actions[0].value)["pid"] == 4321


def test_notify_auto_links_unique_recent_session(tmp_path):
    project = tmp_path / "proj"
    linker = SessionLinker()
    linker.update(
        [
            AgentSession(
                agent="qoder",
                session_id="s-auto",
                project="proj",
                project_path=str(project),
                path="",
                updated_at=datetime.now().astimezone(),
            )
        ]
    )
    client, inbox = build(session_linker=linker)
    response = client.post(
        "/notify",
        json={
            "title": "自动关联",
            "status": "succeeded",
            "source": "Qoder",
            "origin": {"working_dir": str(project / "agentbell")},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.session_id == "s-auto"
    assert notification.metadata["session_link"] == "auto"


def test_explicit_session_id_wins_over_auto_link(tmp_path):
    project = tmp_path / "proj"
    linker = SessionLinker()
    linker.update(
        [
            AgentSession(
                agent="qoder",
                session_id="s-auto",
                project="proj",
                project_path=str(project),
                path="",
                updated_at=datetime.now().astimezone(),
            )
        ]
    )
    client, inbox = build(session_linker=linker)
    response = client.post(
        "/notify",
        json={
            "title": "显式会话",
            "status": "succeeded",
            "source": "Qoder",
            "session_id": "s-explicit",
            "origin": {"working_dir": str(project)},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.session_id == "s-explicit"
    assert "session_link" not in notification.metadata


def test_notify_does_not_guess_between_multiple_sessions(tmp_path):
    project = tmp_path / "proj"
    now = datetime.now().astimezone()
    linker = SessionLinker()
    linker.update(
        [
            AgentSession(
                agent="qoder",
                session_id="s-1",
                project="proj",
                project_path=str(project),
                path="",
                updated_at=now,
            ),
            AgentSession(
                agent="qoder",
                session_id="s-2",
                project="proj",
                project_path=str(project),
                path="",
                updated_at=now,
            ),
        ]
    )
    client, inbox = build(session_linker=linker)
    response = client.post(
        "/notify",
        json={
            "title": "无法唯一关联",
            "status": "succeeded",
            "source": "Qoder",
            "origin": {"working_dir": str(project)},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.session_id is None
    assert "session_link" not in notification.metadata


def test_origin_keeps_focus_action_first_and_limits_total_actions():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "动作上限",
            "origin": {"pid": 4321},
            "actions": [
                {"kind": "copy", "label": "一", "value": "1"},
                {"kind": "copy", "label": "二", "value": "2"},
                {"kind": "copy", "label": "三", "value": "3"},
                {"kind": "copy", "label": "四", "value": "4"},
            ],
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert [action.kind for action in notification.actions] == [
        "focus",
        "copy",
        "copy",
        "copy",
    ]


def test_session_and_timeline_actions_are_ordered_and_ignore_values():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "查看记录",
            "status": "running",
            "session_id": "s-1",
            "run_id": "r-1",
            "actions": [
                {"kind": "copy", "label": "复制", "value": "echo hi"},
                {
                    "kind": "timeline",
                    "value": "C:\\Windows\\System32\\cmd.exe",
                },
                {"kind": "session", "value": "../../secret.jsonl"},
            ],
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert [action.kind for action in notification.actions] == [
        "session",
        "timeline",
        "copy",
    ]
    assert [action.label for action in notification.actions] == [
        "查看记录",
        "时间线",
        "复制",
    ]
    assert notification.actions[0].value == ""
    assert notification.actions[1].value == ""


def test_session_and_timeline_actions_require_identifiers(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={
                "title": "缺少标识",
                "actions": [{"kind": "session"}, {"kind": "timeline"}],
            },
            headers=auth_headers(),
        )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.actions == ()
    assert "缺少 session_id" in caplog.text
    assert "无法确定 run_id" in caplog.text


def test_origin_focus_precedes_session_and_timeline_actions():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "主按钮顺序",
            "origin": {"pid": 4321, "window_title": "Qoder"},
            "actions": [
                {"kind": "timeline"},
                {"kind": "copy", "value": "echo hi"},
                {"kind": "session"},
            ],
            "session_id": "s-1",
            "run_id": "r-1",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert [action.kind for action in notification.actions] == [
        "focus",
        "session",
        "timeline",
        "copy",
    ]


def test_unknown_action_kind_is_rejected():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "未知动作",
            "actions": [{"kind": "approve", "label": "批准"}],
        },
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert inbox.empty()


def test_sender_supplied_focus_action_is_ignored(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={
                "title": "伪造动作",
                "actions": [{"kind": "focus", "label": "伪造", "value": "{}"}],
            },
            headers=auth_headers(),
        )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert all(action.kind != "focus" for action in notification.actions)
    assert "忽略外部 focus 动作" in caplog.text


def test_lossy_question_marks_trigger_encoding_warning(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={
                "title": "??????????????",
                "status": "succeeded",
                "summary": "?? HTTPS ????????? ip:???/???",
            },
            headers=auth_headers(),
        )
    assert response.status_code == 202
    inbox.get_nowait()
    assert "疑似编码丢失" in caplog.text
    assert "fields=title,summary" in caplog.text


def test_normal_question_marks_do_not_trigger_encoding_warning(caplog):
    client, inbox = build()
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/notify",
            json={"title": "这样吗??", "summary": "正常的中文与 ? 标点"},
            headers=auth_headers(),
        )
    assert response.status_code == 202
    inbox.get_nowait()
    assert "疑似编码丢失" not in caplog.text


def test_missing_and_null_fields_get_defaults():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={"title": None, "status": None, "summary": None, "duration": None},
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.title == "未命名任务"
    assert notification.status == "succeeded"
    assert notification.summary == ""
    assert notification.duration == ""
    assert notification.link is None
    assert notification.error is None

    response = client.post("/notify", json={}, headers=auth_headers())
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.title == "未命名任务"


def test_failed_and_canceled_status():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "抓取竞品网页",
            "status": "failed",
            "summary": "抓取失败",
            "error": "HTTP 403 Forbidden",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    failed = inbox.get_nowait()
    assert failed.error == "HTTP 403 Forbidden"
    assert failed.headline == "上一轮【抓取竞品网页】执行失败"

    response = client.post(
        "/notify",
        json={"title": "批量整理素材", "status": "canceled"},
        headers=auth_headers(),
    )
    assert response.status_code == 202
    canceled = inbox.get_nowait()
    assert canceled.headline == "上一轮【批量整理素材】已取消"


def test_error_is_ignored_for_non_failed_status():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={"title": "ok", "status": "succeeded", "error": "leaked internal detail"},
        headers=auth_headers(),
    )
    assert response.status_code == 202
    assert inbox.get_nowait().error is None


def test_popup_mode_and_skin_are_accepted_and_validated():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "部署完成",
            "status": "failed",
            "popup_mode": "CENTER",
            "popup_skin": "Amber",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["popup_mode"] == "center"
    assert body["popup_skin"] == "amber"
    notification = inbox.get_nowait()
    assert notification.popup_mode == "center"
    assert notification.popup_skin == "amber"

    response = client.post(
        "/notify",
        json={"title": "x", "popup_mode": "fullscreen"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert inbox.empty()


def test_rejects_invalid_status_and_oversized_fields():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={"title": "x", "status": "paused"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert inbox.empty()

    response = client.post(
        "/notify", json={"title": "a" * 201}, headers=auth_headers()
    )
    assert response.status_code == 422
    assert inbox.empty()


def test_running_progress_notification_is_accepted():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "生成长报告",
            "status": "running",
            "progress": 45,
            "summary": "正在整理第 3 章",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.status == "running"
    assert notification.progress == 45
    assert notification.priority == "low"


def test_waiting_input_is_accepted_on_running():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "等待权限确认",
            "status": "running",
            "needs_input": True,
            "wait_reason": "Permission",
            "session_id": " session-1 ",
            "run_id": "run-1",
            "summary": "Agent 请求写入工作区",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["needs_input"] is True
    assert body["wait_reason"] == "permission"
    assert body["wait_source"] == "explicit"

    notification = inbox.get_nowait()
    assert notification.status == "running"
    assert notification.priority == "high"
    assert notification.wait_reason_label == "等待权限确认"
    assert notification.session_id == "session-1"
    assert notification.run_id == "run-1"
    assert notification.is_waiting_input is True


def test_waiting_input_defaults_and_clearing():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "等待回答",
            "status": "running",
            "needs_input": True,
            "wait_reason": "unknown-reason",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    assert response.json()["wait_reason"] == "other"
    assert inbox.get_nowait().wait_reason_label == "等待输入"

    response = client.post(
        "/notify",
        json={
            "title": "继续执行",
            "status": "running",
            "needs_input": False,
            "wait_reason": "permission",
            "wait_source": "inferred",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.needs_input is False
    assert notification.wait_reason is None
    assert notification.wait_source is None
    assert notification.priority == "low"


def test_waiting_input_rejects_non_running_status():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={"title": "完成", "status": "succeeded", "needs_input": True},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert inbox.empty()


def test_unsafe_links_are_dropped():
    client, inbox = build()
    for link in ("file:///C:/Windows/System32/calc.exe", "javascript:alert(1)", "ftp://x.test/a"):
        response = client.post(
            "/notify",
            json={"title": "link", "status": "succeeded", "link": link},
            headers=auth_headers(),
        )
        assert response.status_code == 202
        assert inbox.get_nowait().link is None


def test_windows_gbk_curl_payload_is_accepted():
    client, inbox = build()
    body = json.dumps(
        {"title": "生成竞品分析报告", "status": "succeeded", "summary": "中文摘要"},
        ensure_ascii=False,
    ).encode("gb18030")
    response = client.post(
        "/notify",
        content=body,
        headers={"X-Token": TOKEN, "Content-Type": "application/json"},
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.title == "生成竞品分析报告"
    assert notification.summary == "中文摘要"


def test_bad_json_and_empty_body():
    client, inbox = build()
    response = client.post(
        "/notify",
        content=b'{"title": ',
        headers={"X-Token": TOKEN, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert inbox.empty()

    response = client.post("/notify", content=b"", headers={"X-Token": TOKEN})
    assert response.status_code == 400


def test_oversized_body_is_rejected_before_validation():
    client, inbox = build()
    large = b'{"title":"' + b"a" * (MAX_BODY_BYTES + 1) + b'"}'
    response = client.post(
        "/notify", content=large, headers={"X-Token": TOKEN, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert inbox.empty()


def test_queue_full_returns_503():
    client, inbox = build(maxsize=1)
    first = client.post(
        "/notify", json={"title": "first"}, headers=auth_headers()
    )
    assert first.status_code == 202
    second = client.post(
        "/notify", json={"title": "second"}, headers=auth_headers()
    )
    assert second.status_code == 503
    assert inbox.qsize() == 1


def test_token_disabled_means_no_auth_required():
    inbox: queue.Queue[Notification] = queue.Queue(maxsize=2)
    app = create_app(
        AppConfig(port=8765, token="", auto_close_seconds=30, autostart=False),
        inbox,
        logging.getLogger("agentbell.tests"),
    )
    client = TestClient(app)
    response = client.post("/notify", json={"title": "open"}, headers={"Content-Type": "application/json"})
    assert response.status_code == 202
    assert response.json()["queued"] is True


def test_web_ui_and_json_history_routes_are_gone():
    client, _ = build()
    assert client.get("/").status_code == 404
    assert client.get("/api/notifications").status_code == 404


def test_shared_store_records_accepted_notifications():
    store = NotificationStore()
    client, inbox = build(store=store)
    response = client.post(
        "/notify",
        json={
            "title": "同步到通知中心",
            "status": "succeeded",
            "summary": "窗口应能读到这条记录。",
            "duration": "12s",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    assert inbox.qsize() == 1

    items = store.snapshot()
    assert len(items) == 1
    assert items[0].id == response.json()["id"]
    assert items[0].title == "同步到通知中心"
    assert items[0].summary == "窗口应能读到这条记录。"


def test_queue_full_still_records_history():
    store = NotificationStore()
    client, inbox = build(maxsize=1, store=store)
    first = client.post("/notify", json={"title": "one"}, headers=auth_headers())
    assert first.status_code == 202
    second = client.post("/notify", json={"title": "two"}, headers=auth_headers())
    assert second.status_code == 503

    assert [item.title for item in store.snapshot()] == ["two", "one"]
    assert inbox.qsize() == 1


def test_dedupe_key_updates_the_same_notification():
    store = NotificationStore()
    client, inbox = build(store=store)
    payload = {
        "title": "长任务",
        "status": "running",
        "dedupe_key": "long-task",
        "progress": 10,
    }
    first = client.post("/notify", json=payload, headers=auth_headers())
    assert first.status_code == 202
    assert first.json()["updated"] is False
    assert first.json()["occurrence"] == 1

    second = client.post(
        "/notify",
        json={**payload, "status": "succeeded", "progress": None},
        headers=auth_headers(),
    )
    assert second.status_code == 202
    body = second.json()
    assert body["updated"] is True
    assert body["id"] == first.json()["id"]
    assert body["occurrence"] == 2

    items = store.snapshot()
    assert len(items) == 1
    assert items[0].status == "succeeded"
    assert items[0].occurrence_count == 2
    assert inbox.qsize() == 2


def test_require_ack_and_actions_are_forwarded():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "部署失败",
            "status": "failed",
            "priority": "critical",
            "require_ack": True,
            "bypass_quiet_hours": True,
            "expires_in": 120,
            "source": "deploy-bot",
            "actions": [
                {"kind": "open", "value": "https://example.com/logs"},
                {"kind": "retry", "value": "http://127.0.0.1:9000/retry"},
                {"kind": "path", "value": "C:/secret.txt"},
                {"kind": "copy", "value": "curl http://127.0.0.1:9000/retry"},
            ],
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    assert response.json()["require_ack"] is True
    notification = inbox.get_nowait()
    assert notification.priority == "critical"
    assert notification.require_ack is True
    assert notification.bypass_quiet_hours is True
    assert notification.source == "deploy-bot"
    assert notification.expires_at is not None
    assert [action.kind for action in notification.actions] == [
        "open",
        "retry",
        "copy",
    ]


def build_persistent(tmp_path):
    storage = NotificationStorage(
        tmp_path / "history.db", logging.getLogger("agentbell.tests")
    )
    store = NotificationStore(storage=storage, limit=50)
    client, inbox = build(store=store)
    return client, inbox, store


def test_phase_is_lowercased_and_returned(tmp_path):
    client, _inbox, store = build_persistent(tmp_path)
    try:
        response = client.post(
            "/notify",
            json={
                "title": "进度汇报",
                "status": "running",
                "session_id": "s-1",
                "phase": "Progress",
            },
            headers=auth_headers(),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["run_id"] == "session:s-1"
        assert body["phase"] == "progress"
        events = store.run_events("session:s-1")
        assert [event.kind for event in events] == ["progress"]
    finally:
        store.close()


def test_unknown_phase_is_rejected(tmp_path):
    client, _inbox, store = build_persistent(tmp_path)
    try:
        response = client.post(
            "/notify",
            json={"title": "任务", "phase": "bogus"},
            headers=auth_headers(),
        )
        assert response.status_code == 422
    finally:
        store.close()


def test_notify_infers_run_transitions(tmp_path):
    client, _inbox, store = build_persistent(tmp_path)
    try:
        first = client.post(
            "/notify",
            json={
                "title": "任务",
                "status": "running",
                "session_id": "s-1",
            },
            headers=auth_headers(),
        )
        assert first.json()["run_id"] == "session:s-1"
        client.post(
            "/notify",
            json={
                "title": "任务",
                "status": "running",
                "session_id": "s-1",
                "needs_input": True,
                "wait_reason": "question",
            },
            headers=auth_headers(),
        )
        client.post(
            "/notify",
            json={
                "title": "任务",
                "status": "running",
                "session_id": "s-1",
                "needs_input": False,
            },
            headers=auth_headers(),
        )
        client.post(
            "/notify",
            json={"title": "任务", "status": "succeeded", "session_id": "s-1"},
            headers=auth_headers(),
        )
        events = store.run_events("session:s-1")
        assert [event.kind for event in events] == [
            "started",
            "waiting_input",
            "resumed",
            "finished",
        ]
        assert events[-1].status == "succeeded"
    finally:
        store.close()


def test_rules_match_project_wait_reason_and_duration():
    config = AppConfig(
        port=8765,
        token=TOKEN,
        auto_close_seconds=30,
        autostart=False,
        rules=(
            RuleConfig(
                name="演示项目权限等待",
                project="demo-*",
                wait_reason="permission",
                min_duration_seconds=600,
                priority="critical",
            ),
        ),
    )
    client, inbox = build(config=config)
    response = client.post(
        "/notify",
        json={
            "title": "等待权限",
            "status": "running",
            "needs_input": True,
            "wait_reason": "permission",
            "duration": "11m",
            "priority": "low",
            "origin": {"working_dir": "E:\\work\\demo-api"},
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    assert response.json()["priority"] == "critical"
    notification = inbox.get_nowait()
    assert notification.rule_name == "演示项目权限等待"
    assert notification.priority == "critical"

    response = client.post(
        "/notify",
        json={
            "title": "等待权限",
            "status": "running",
            "needs_input": True,
            "wait_reason": "permission",
            "duration": "5m",
            "priority": "low",
            "origin": {"working_dir": "E:\\work\\demo-api"},
        },
        headers=auth_headers(),
    )
    assert response.json()["priority"] == "low"
    assert inbox.get_nowait().rule_name == ""


def test_rules_use_live_config_after_settings_save():
    ref = ConfigRef(
        AppConfig(
            port=8765,
            token=TOKEN,
            auto_close_seconds=30,
            autostart=False,
        )
    )
    client, inbox = build(config_source=lambda: ref.current)
    payload = {
        "title": "等待权限",
        "status": "running",
        "needs_input": True,
        "wait_reason": "permission",
        "priority": "low",
    }
    first = client.post("/notify", json=payload, headers=auth_headers())
    assert first.json()["priority"] == "low"
    assert inbox.get_nowait().rule_name == ""

    ref.current = AppConfig(
        port=8765,
        token=TOKEN,
        auto_close_seconds=30,
        autostart=False,
        rules=(
            RuleConfig(
                name="权限等待高优",
                wait_reason="permission",
                priority="critical",
                silent=True,
            ),
        ),
    )
    second = client.post(
        "/notify",
        json={**payload, "title": "再次等待权限"},
        headers=auth_headers(),
    )
    assert second.json()["priority"] == "critical"
    notification = inbox.get_nowait()
    assert notification.rule_name == "权限等待高优"
    assert notification.silent is True


def test_notify_sanitizes_metadata():
    client, inbox = build()
    response = client.post(
        "/notify",
        json={
            "title": "带上下文的回合",
            "status": "succeeded",
            "metadata": {
                "model": "DeepSeek-V3.2",
                "turn": 3,
                "tools": ["read_file", "grep"],
                "files": ["a.py"],
                "context_percent": 82.5,
                "flag": True,
                "nested": {"a": 1},
                "blank": "   ",
                "long": "x" * 800,
            },
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    notification = inbox.get_nowait()
    assert notification.metadata["model"] == "DeepSeek-V3.2"
    assert notification.metadata["turn"] == "3"
    assert notification.metadata["tools"] == "2"
    assert notification.metadata["files"] == "1"
    assert notification.metadata["context_percent"] == "82.5"
    assert notification.metadata["flag"] == "true"
    assert notification.metadata["long"] == "x" * 512
    assert "nested" not in notification.metadata
    assert "blank" not in notification.metadata


def test_metadata_roundtrips_through_storage(tmp_path):
    client, inbox, store = build_persistent(tmp_path)
    try:
        response = client.post(
            "/notify",
            json={
                "title": "持久化上下文",
                "status": "succeeded",
                "dedupe_key": "meta-roundtrip",
                "metadata": {"model": "deepseek-chat", "turn": 7},
            },
            headers=auth_headers(),
        )
        assert response.status_code == 202
        inbox.get_nowait()
        stored = store.find_by_dedupe("meta-roundtrip")
        assert stored is not None
        assert stored.metadata == {"model": "deepseek-chat", "turn": "7"}
    finally:
        store.close()


def test_compaction_phase_records_run_event(tmp_path):
    client, _inbox, store = build_persistent(tmp_path)
    try:
        response = client.post(
            "/notify",
            json={
                "title": "上下文压缩",
                "status": "running",
                "session_id": "compact-1",
                "phase": "compaction",
            },
            headers=auth_headers(),
        )
        assert response.status_code == 202
        events = store.run_events("session:compact-1")
        assert [event.kind for event in events] == ["compaction"]
    finally:
        store.close()


def test_usage_report_endpoint_is_idempotent():
    ledger = UsageLedger(None, logging.getLogger("agentbell.tests.usage"))
    client, _inbox = build(ledger=ledger)
    payload = {
        "report_id": "r-1",
        "source": "deepseek",
        "model": "deepseek-chat",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.0004,
    }
    first = client.post("/usage/report", json=payload, headers=auth_headers())
    assert first.status_code == 202
    body = first.json()
    assert body["ok"] is True
    assert body["duplicate"] is False
    assert body["total_tokens"] == 150
    assert body["version"] == 1

    second = client.post("/usage/report", json=payload, headers=auth_headers())
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert second.json()["version"] == 1
    assert ledger.version == 1

    auto = client.post(
        "/usage/report",
        json={k: v for k, v in payload.items() if k != "report_id"},
        headers=auth_headers(),
    )
    assert auto.status_code == 202
    assert auto.json()["report_id"].startswith("auto:")
    assert auto.json()["duplicate"] is False


def test_usage_report_requires_token_and_valid_payload():
    ledger = UsageLedger(None, logging.getLogger("agentbell.tests.usage"))
    client, _inbox = build(ledger=ledger)
    unauthorized = client.post(
        "/usage/report", json={"model": "m", "input_tokens": 1}
    )
    assert unauthorized.status_code == 401

    invalid = client.post(
        "/usage/report",
        json={"model": "m", "input_tokens": -5},
        headers=auth_headers(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["ok"] is False


def test_usage_report_without_ledger_returns_503():
    client, _inbox = build()
    response = client.post(
        "/usage/report", json={"model": "m", "input_tokens": 1}, headers=auth_headers()
    )
    assert response.status_code == 503


def test_session_report_adds_and_ends_external_session(tmp_path):
    registry = SessionReportRegistry(logging.getLogger("agentbell.tests.sessions"))
    client, _inbox = build(sessions=registry)
    started = client.post(
        "/sessions/report",
        json={
            "session_id": "dsh-1",
            "agent": "DeepSeek",
            "title": "DeepSeek Harness 任务",
            "project": "demo",
            "project_path": str(tmp_path),
            "status": "running",
            "turn": 4,
            "needs_input": True,
            "wait_reason": "Permission",
        },
        headers=auth_headers(),
    )
    assert started.status_code == 202
    body = started.json()
    assert body["stored"] is True
    assert body["active"] is True
    assert body["sessions"] == 1

    sessions = registry.to_agent_sessions()
    assert len(sessions) == 1
    assert sessions[0].external is True
    assert sessions[0].agent == "deepseek"
    assert sessions[0].wait_reason == "permission"
    assert sessions[0].path == ""

    ended = client.post(
        "/sessions/report",
        json={"session_id": "dsh-1", "agent": "deepseek", "status": "ended"},
        headers=auth_headers(),
    )
    assert ended.status_code == 202
    assert ended.json()["active"] is False
    assert ended.json()["sessions"] == 0
    assert registry.count == 0


def test_session_report_validation_and_auth():
    registry = SessionReportRegistry(logging.getLogger("agentbell.tests.sessions"))
    client, _inbox = build(sessions=registry)
    unauthorized = client.post("/sessions/report", json={"session_id": "x"})
    assert unauthorized.status_code == 401

    missing_id = client.post("/sessions/report", json={}, headers=auth_headers())
    assert missing_id.status_code == 422
    assert missing_id.json()["ok"] is False

    bad_status = client.post(
        "/sessions/report",
        json={"session_id": "x", "status": "bogus"},
        headers=auth_headers(),
    )
    assert bad_status.status_code == 422


def test_session_report_without_registry_returns_503():
    client, _inbox = build()
    response = client.post(
        "/sessions/report", json={"session_id": "x"}, headers=auth_headers()
    )
    assert response.status_code == 503


def test_integration_report_requires_auth_and_valid_mode():
    client, _inbox = build()
    unauthorized = client.post(
        "/integration/report", json={"agent": "Qoder", "mode": "full"}
    )
    assert unauthorized.status_code == 401

    bad_mode = client.post(
        "/integration/report",
        json={"agent": "Qoder", "mode": "bogus"},
        headers=auth_headers(),
    )
    assert bad_mode.status_code == 422
    assert bad_mode.json()["ok"] is False

    missing_agent = client.post(
        "/integration/report",
        json={"mode": "full"},
        headers=auth_headers(),
    )
    assert missing_agent.status_code == 422


def test_integration_report_upserts_profile():
    store = NotificationStore()
    client, _inbox = build(store=store)
    response = client.post(
        "/integration/report",
        json={
            "agent": "  Claude   Code ",
            "mode": "Finish_Only",
            "source": "manual",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["agent"] == "Claude Code"
    assert body["mode"] == "finish_only"
    assert body["changed"] is True

    updated = client.post(
        "/integration/report",
        json={"agent": "Claude Code", "mode": "full"},
        headers=auth_headers(),
    )
    assert updated.status_code == 202
    assert updated.json()["mode"] == "full"
    assert updated.json()["changed"] is True

    repeated = client.post(
        "/integration/report",
        json={"agent": "Claude Code", "mode": "full"},
        headers=auth_headers(),
    )
    assert repeated.status_code == 202
    assert repeated.json()["changed"] is False

    profiles = store.integration_profiles()
    assert len(profiles) == 1
    assert profiles[0].agent == "Claude Code"
    assert profiles[0].mode == "full"

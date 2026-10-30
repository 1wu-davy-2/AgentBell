from __future__ import annotations

import json
import logging
import queue

import pytest
from fastapi.testclient import TestClient

from agentbell.api import MAX_BODY_BYTES, create_app
from agentbell.config import AppConfig
from agentbell.models import Notification
from agentbell.store import NotificationStore

TOKEN = "test-secret"


def build(maxsize: int = 20, store: NotificationStore | None = None):
    inbox: queue.Queue[Notification] = queue.Queue(maxsize=maxsize)
    app = create_app(
        AppConfig(port=8765, token=TOKEN, auto_close_seconds=30, autostart=False),
        inbox,
        logging.getLogger("agentbell.tests"),
        store=store,
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

from __future__ import annotations

from agentbell.models import Notification
from agentbell.search_query import parse_search


def test_parse_search_extracts_fields_and_free_text():
    query = parse_search(
        "status:failed 来源:Claude priority:高 session:abc run:r1 ack:no 部署"
    )

    assert query.status == ("failed",)
    assert query.source == ("claude",)
    assert query.priority == ("high",)
    assert query.session == ("abc",)
    assert query.run == ("r1",)
    assert query.acknowledged is False
    assert query.text == "部署"


def test_parse_search_supports_or_within_a_field():
    query = parse_search("status:失败 status:running priority:紧急")

    assert query.status == ("failed", "running")
    assert query.priority == ("critical",)


def test_parse_search_keeps_unknown_fields_as_text():
    query = parse_search("status:bogus http://example.com E:\\opt\\demo")

    assert query.status == ()
    assert query.text == "status:bogus http://example.com E:\\opt\\demo"


def test_parse_search_handles_quotes_and_empty_input():
    query = parse_search('session:"abc 123" "hello world"')

    assert query.session == ("abc 123",)
    assert query.text == "hello world"
    assert parse_search("   ").has_filters is False


def test_search_query_matches_notification_fields():
    query = parse_search("status:failed source:claude priority:high ack:no")
    matching = Notification(
        id="n1",
        title="部署失败",
        status="failed",
        source="Claude Code",
        priority="high",
    )
    wrong_status = Notification(
        id="n2",
        title="部署成功",
        status="succeeded",
        source="Claude Code",
        priority="high",
    )
    acknowledged = Notification(
        id="n3",
        title="部署失败",
        status="failed",
        source="Claude Code",
        priority="high",
        acknowledged=True,
    )

    assert query.matches(matching) is True
    assert query.matches(wrong_status) is False
    assert query.matches(acknowledged) is False
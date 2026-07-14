import httpx

from viking_forge.notifications import NotificationDispatcher, build_card
from viking_forge.store import Store


def make_store(tmp_path):
    store = Store(tmp_path / "forge.sqlite3")
    store.initialize()
    return store


def payload():
    return {
        "issue_number": 33,
        "issue_title": "Parser crash",
        "status": "pr_open",
        "summary": "Guard empty input",
        "validation": "pytest passed",
        "issue_url": "https://github.com/volcengine/OpenViking/issues/33",
        "workflow_url": "https://github.com/volcengine/OpenViking/actions/runs/1",
        "pr_url": "https://github.com/volcengine/OpenViking/pull/44",
    }


def test_outbox_enqueue_is_idempotent(tmp_path):
    store = make_store(tmp_path)

    assert store.enqueue_notification("run-1", "pr_open", payload()) is True
    assert store.enqueue_notification("run-1", "pr_open", payload()) is False


def test_card_contains_review_context_and_link():
    card = build_card("pr_open", payload())
    text = str(card)

    assert "#33 Parser crash" in text
    assert "Guard empty input" in text
    assert "pytest passed" in text
    assert "https://github.com/volcengine/OpenViking/pull/44" in text


def test_card_uses_readable_chinese_labels():
    card = build_card("pr_open", {"issue_number": 1, "issue_title": "标题"})
    content = card["card"]["elements"][0]["content"]
    button = card["card"]["elements"][1]["actions"][0]["text"]["content"]

    assert "状态：" in content
    assert "摘要：" in content
    assert "校验：" in content
    assert button == "查看详情"


def test_dispatch_marks_successful_notification_sent(tmp_path):
    store = make_store(tmp_path)
    store.enqueue_notification("run-1", "pr_open", payload(), now=100)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 0}))
    dispatcher = NotificationDispatcher(
        store,
        "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        http_client=httpx.Client(transport=transport),
    )

    assert dispatcher.dispatch_once(now=100) == 1

    row = store.get_notification("run-1", "pr_open")
    assert row["status"] == "sent"
    assert row["sent_at"] == 100


def test_dispatch_failure_is_retried_and_eventually_dead(tmp_path):
    store = make_store(tmp_path)
    store.enqueue_notification("run-2", "blocked", payload(), now=100)
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="failed"))
    dispatcher = NotificationDispatcher(
        store,
        "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        http_client=httpx.Client(transport=transport),
    )

    for attempt in range(24):
        dispatcher.dispatch_once(now=100 + attempt * 3600)

    row = store.get_notification("run-2", "blocked")
    assert row["status"] == "dead"
    assert row["attempts"] == 24

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from viking_forge.app import create_app
from viking_forge.config import Config
from viking_forge.security import compute_issue_revision
from viking_forge.store import Store


class FakeGitHub:
    def __init__(self):
        self.labels = []
        self.issue = {"state": "open", "title": "<script>alert(1)</script>", "body": "Body"}
        self.error = None

    def get_issue(self, issue_number):
        if self.error:
            raise self.error
        return self.issue

    def add_label(self, issue_number, label):
        if self.error:
            raise self.error
        self.labels.append((issue_number, label))


@pytest.fixture
def app_parts(tmp_path):
    config = Config(
        repository="volcengine/OpenViking",
        database_path=str(tmp_path / "forge.sqlite3"),
        dashboard_username="maintainer",
        dashboard_password="password",
        dashboard_csrf_secret="csrf-value",
        github_webhook_secret="webhook",
        callback_secret="callback",
        github_app_id="123",
        github_app_private_key="private-key",
        feishu_webhook_url="",
    )
    store = Store(config.database_path)
    store.initialize()
    github = FakeGitHub()
    app = create_app(config=config, store=store, github=github, start_background_tasks=False)
    yield TestClient(app), store, github
    store.close()


def auth():
    return ("maintainer", "password")


def add_issue(store, number=7):
    title = "<script>alert(1)</script>"
    body = "Body"
    store.upsert_issue(
        number,
        compute_issue_revision(title, body),
        title,
        f"https://github.com/volcengine/OpenViking/issues/{number}",
        "user",
        "open",
    )


def test_health_is_public(app_parts):
    client, _, _ = app_parts

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_requires_auth_and_escapes_issue_title(app_parts):
    client, store, _ = app_parts
    add_issue(store)

    assert client.get("/").status_code == 401
    response = client.get("/", auth=auth())

    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "忽略" in response.text
    assert "继续分析" in response.text


@pytest.mark.parametrize(
    ("decision", "label"),
    [("ignore", "agent:ignored"), ("analyze", "agent:analyze")],
)
def test_human_decision_writes_a_github_label(app_parts, decision, label):
    client, store, github = app_parts
    add_issue(store)

    response = client.post(
        "/issues/7/decision",
        auth=auth(),
        data={"decision": decision, "csrf_token": "csrf-value"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert github.labels == [(7, label)]
    assert store.get_issue(7)["bot_state"] == "awaiting_decision"


def test_decision_rejects_bad_csrf(app_parts):
    client, store, github = app_parts
    add_issue(store)

    response = client.post(
        "/issues/7/decision",
        auth=auth(),
        data={"decision": "analyze", "csrf_token": "wrong"},
    )

    assert response.status_code == 403
    assert github.labels == []


def test_decision_rejects_non_pending_issue(app_parts):
    client, store, github = app_parts
    add_issue(store)
    store.transition_issue(7, "ignored", event_type="ignored")

    response = client.post(
        "/issues/7/decision",
        auth=auth(),
        data={"decision": "analyze", "csrf_token": "csrf-value"},
    )

    assert response.status_code == 409
    assert github.labels == []


def test_decision_rejects_changed_issue_revision(app_parts):
    client, store, github = app_parts
    add_issue(store)
    github.issue["body"] = "Changed after dashboard snapshot"

    response = client.post(
        "/issues/7/decision",
        auth=auth(),
        data={"decision": "analyze", "csrf_token": "csrf-value"},
    )

    assert response.status_code == 409
    assert github.labels == []


def test_github_failure_does_not_change_local_state(app_parts):
    client, store, github = app_parts
    add_issue(store)
    github.error = RuntimeError("github unavailable")

    response = client.post(
        "/issues/7/decision",
        auth=auth(),
        data={"decision": "ignore", "csrf_token": "csrf-value"},
    )

    assert response.status_code == 502
    assert store.get_issue(7)["bot_state"] == "awaiting_decision"


def test_signed_github_webhook_adds_pending_issue(app_parts):
    client, store, _ = app_parts
    payload = {
        "action": "opened",
        "repository": {"full_name": "volcengine/OpenViking"},
        "issue": {
            "number": 21,
            "title": "New issue",
            "body": "Details",
            "html_url": "https://github.com/volcengine/OpenViking/issues/21",
            "state": "open",
            "user": {"login": "reporter"},
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"webhook", body, hashlib.sha256).hexdigest()

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-21",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "applied"}
    assert store.get_issue(21)["bot_state"] == "awaiting_decision"


def test_webhook_rejects_invalid_signature(app_parts):
    client, _, _ = app_parts

    response = client.post(
        "/webhooks/github",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )

    assert response.status_code == 403


def test_signed_workflow_callback_updates_state(app_parts):
    client, store, _ = app_parts
    add_issue(store, 22)
    store.transition_issue(22, "triaging", event_type="analysis_requested")
    revision = store.get_issue(22)["revision"]
    payload = {
        "event_id": "triage:22:done",
        "issue_number": 22,
        "issue_revision": revision,
        "stage": "waiting_approval",
        "summary": "Small parser fix",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"callback", body, hashlib.sha256).hexdigest()

    response = client.post(
        "/callbacks/workflow",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Viking-Forge-Signature": signature,
        },
    )

    assert response.status_code == 200
    assert store.get_issue(22)["bot_state"] == "waiting_approval"


def test_dashboard_uses_readable_chinese_actions(app_parts):
    client, store, _ = app_parts
    add_issue(store)

    response = client.get("/", auth=auth())

    assert "忽略" in response.text
    assert "继续分析" in response.text


def test_signed_reconcile_callback_applies_github_snapshot(app_parts):
    client, store, _ = app_parts
    payload = {
        "snapshot_id": "reconcile:123",
        "issues": [
            {
                "issue_number": 31,
                "revision": "revision-31",
                "title": "Reconciled issue",
                "issue_url": "https://github.com/volcengine/OpenViking/issues/31",
                "author": "reporter",
                "github_state": "open",
                "bot_state": "waiting_approval",
                "pr_number": None,
                "pr_url": None,
            }
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"callback", body, hashlib.sha256).hexdigest()

    response = client.post(
        "/callbacks/reconcile",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Viking-Forge-Signature": signature,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "applied"}
    assert store.get_issue(31)["bot_state"] == "waiting_approval"


def test_reconcile_callback_is_idempotent(app_parts):
    client, _, _ = app_parts
    payload = {"snapshot_id": "reconcile:same", "issues": []}
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"callback", body, hashlib.sha256).hexdigest()
    headers = {"X-Viking-Forge-Signature": signature}

    assert client.post("/callbacks/reconcile", content=body, headers=headers).json() == {
        "status": "applied"
    }
    assert client.post("/callbacks/reconcile", content=body, headers=headers).json() == {
        "status": "ignored"
    }

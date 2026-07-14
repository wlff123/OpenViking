from viking_forge.security import compute_issue_revision
from viking_forge.store import Store
from viking_forge.webhooks import apply_github_event


def issue_payload(action, label=None):
    payload = {
        "action": action,
        "repository": {"full_name": "volcengine/OpenViking"},
        "issue": {
            "number": 8,
            "title": "Cannot parse config",
            "body": "Steps",
            "html_url": "https://github.com/volcengine/OpenViking/issues/8",
            "state": "open",
            "user": {"login": "reporter"},
        },
        "sender": {"login": "maintainer"},
    }
    if label:
        payload["label"] = {"name": label}
    return payload


def make_store(tmp_path):
    store = Store(tmp_path / "forge.sqlite3")
    store.initialize()
    return store


def test_opened_issue_is_recorded_without_starting_triage(tmp_path):
    store = make_store(tmp_path)

    result = apply_github_event(store, "issues", "delivery-1", issue_payload("opened"))

    assert result == "applied"
    issue = store.get_issue(8)
    assert issue["bot_state"] == "awaiting_decision"
    assert issue["revision"] == compute_issue_revision("Cannot parse config", "Steps")


def test_duplicate_delivery_is_ignored(tmp_path):
    store = make_store(tmp_path)
    payload = issue_payload("opened")

    assert apply_github_event(store, "issues", "same", payload) == "applied"
    assert apply_github_event(store, "issues", "same", payload) == "ignored"


def test_decision_labels_drive_state(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))

    apply_github_event(store, "issues", "analyze", issue_payload("labeled", "agent:analyze"))
    assert store.get_issue(8)["bot_state"] == "triaging"


def test_ignored_label_does_not_start_triage(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))

    apply_github_event(store, "issues", "ignore", issue_payload("labeled", "agent:ignored"))

    assert store.get_issue(8)["bot_state"] == "ignored"


def test_retriage_label_returns_reviewed_issue_to_triaging(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))
    apply_github_event(store, "issues", "analyze", issue_payload("labeled", "agent:analyze"))
    store.transition_issue(8, "waiting_approval", event_type="triage_complete")

    result = apply_github_event(
        store,
        "issues",
        "retriage",
        issue_payload("labeled", "agent:retriage"),
    )

    assert result == "applied"
    assert store.get_issue(8)["bot_state"] == "triaging"


def test_unrelated_repository_is_rejected(tmp_path):
    store = make_store(tmp_path)
    payload = issue_payload("opened")
    payload["repository"]["full_name"] = "someone/else"

    assert apply_github_event(store, "issues", "delivery", payload) == "rejected"
    assert store.get_issue(8) is None

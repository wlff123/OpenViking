import pytest

from viking_forge.callbacks import CallbackConflict, apply_workflow_callback
from viking_forge.store import Store


def make_store(tmp_path):
    store = Store(tmp_path / "forge.sqlite3")
    store.initialize()
    store.upsert_issue(9, "revision", "Title", "https://example.test/9", "user", "open")
    store.transition_issue(9, "triaging", event_type="analysis_requested")
    return store


def test_triage_callback_moves_issue_to_waiting_approval(tmp_path):
    store = make_store(tmp_path)

    result = apply_workflow_callback(
        store,
        {
            "event_id": "triage:9:1",
            "issue_number": 9,
            "issue_revision": "revision",
            "stage": "waiting_approval",
            "summary": "Likely parser bug",
        },
    )

    assert result == "applied"
    issue = store.get_issue(9)
    assert issue["bot_state"] == "waiting_approval"
    assert "Likely parser bug" in issue["triage_json"]


def test_duplicate_callback_is_ignored(tmp_path):
    store = make_store(tmp_path)
    payload = {
        "event_id": "triage:9:1",
        "issue_number": 9,
        "issue_revision": "revision",
        "stage": "waiting_approval",
    }

    assert apply_workflow_callback(store, payload) == "applied"
    assert apply_workflow_callback(store, payload) == "ignored"


def test_stale_callback_is_rejected(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(CallbackConflict):
        apply_workflow_callback(
            store,
            {
                "event_id": "triage:9:stale",
                "issue_number": 9,
                "issue_revision": "old-revision",
                "stage": "waiting_approval",
            },
        )


def test_pr_callback_enqueues_feishu_notification(tmp_path):
    store = make_store(tmp_path)
    for state in ("waiting_approval", "claimed", "coding", "validating", "publishing"):
        store.transition_issue(9, state, event_type=f"entered_{state}")

    result = apply_workflow_callback(
        store,
        {
            "event_id": "fix:9:77:pr",
            "run_id": "77",
            "issue_number": 9,
            "issue_revision": "revision",
            "stage": "pr_open",
            "summary": "Fix ready for review",
            "validation": "pytest passed",
            "pr_number": 12,
            "pr_url": "https://example.test/pull/12",
        },
    )

    assert result == "applied"
    notification = store.get_notification("77", "pr_open")
    assert notification is not None
    assert "Fix ready for review" in notification["payload_json"]

import pytest

from viking_forge.store import InvalidTransition, Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "forge.sqlite3")
    value.initialize()
    yield value
    value.close()


def test_new_issue_waits_for_human_decision(store):
    store.upsert_issue(
        issue_number=42,
        revision="rev-1",
        title="Crash on empty collection",
        issue_url="https://github.com/volcengine/OpenViking/issues/42",
        author="contributor",
        github_state="open",
    )

    issue = store.get_issue(42)

    assert issue is not None
    assert issue["bot_state"] == "awaiting_decision"


def test_decision_and_fix_transitions_are_explicit(store):
    store.upsert_issue(1, "rev", "Title", "https://example.test/1", "user", "open")

    store.transition_issue(1, "ignored", event_type="decision_ignored")
    assert store.get_issue(1)["bot_state"] == "ignored"

    store.upsert_issue(2, "rev", "Title", "https://example.test/2", "user", "open")
    for state in (
        "triaging",
        "waiting_approval",
        "claimed",
        "coding",
        "validating",
        "publishing",
        "pr_open",
        "merged",
    ):
        store.transition_issue(2, state, event_type=f"entered_{state}")
    assert store.get_issue(2)["bot_state"] == "merged"


def test_issue_cannot_skip_human_analysis_decision(store):
    store.upsert_issue(3, "rev", "Title", "https://example.test/3", "user", "open")

    with pytest.raises(InvalidTransition):
        store.transition_issue(3, "claimed", event_type="invalid")


def test_delivery_ids_are_idempotent(store):
    assert store.record_delivery("github:abc", "issues") is True
    assert store.record_delivery("github:abc", "issues") is False


def test_snapshot_reconciles_state_without_transition_history(store):
    snapshot = {
        "issue_number": 9,
        "revision": "live-revision",
        "title": "Live title",
        "issue_url": "https://example.test/9",
        "author": "reporter",
        "github_state": "open",
        "bot_state": "pr_open",
        "pr_number": 17,
        "pr_url": "https://example.test/pull/17",
    }

    store.apply_snapshot([snapshot])

    issue = store.get_issue(9)
    assert issue["bot_state"] == "pr_open"
    assert issue["pr_number"] == 17
    assert issue["pr_url"] == "https://example.test/pull/17"


def test_closed_issue_can_be_confirmed_as_merged(store):
    store.upsert_issue(10, "rev", "Title", "https://example.test/10", "user", "open")
    store.transition_issue(10, "closed", event_type="issue_closed")

    store.transition_issue(10, "merged", event_type="generated_pr_merged")

    assert store.get_issue(10)["bot_state"] == "merged"

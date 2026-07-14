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


def test_closed_issue_can_be_confirmed_as_merged(store):
    store.upsert_issue(10, "rev", "Title", "https://example.test/10", "user", "open")
    store.transition_issue(10, "closed", event_type="issue_closed")

    store.transition_issue(10, "merged", event_type="generated_pr_merged")

    assert store.get_issue(10)["bot_state"] == "merged"


def test_enqueue_run_changes_issue_state_atomically(store):
    store.upsert_issue(11, "rev-11", "Title", "https://example.test/11", "user", "open")

    run_id = store.enqueue_run(11, "triage", "triaging")

    issue = store.get_issue(11)
    run = store.get_run(run_id)
    assert issue["bot_state"] == "triaging"
    assert issue["active_run_id"] == run_id
    assert run["issue_number"] == 11
    assert run["issue_revision"] == "rev-11"
    assert run["kind"] == "triage"
    assert run["status"] == "queued"


def test_enqueue_rejects_duplicate_active_run(store):
    store.upsert_issue(12, "rev-12", "Title", "https://example.test/12", "user", "open")
    store.enqueue_run(12, "triage", "triaging")

    with pytest.raises(RuntimeError, match="active run"):
        store.enqueue_run(12, "triage", "waiting_approval")


def test_claim_run_is_fifo(store):
    for issue_number in (13, 14):
        store.upsert_issue(
            issue_number,
            f"rev-{issue_number}",
            "Title",
            f"https://example.test/{issue_number}",
            "user",
            "open",
        )
    first = store.enqueue_run(13, "triage", "triaging")
    second = store.enqueue_run(14, "triage", "triaging")

    assert store.claim_run(now=100)["run_id"] == first
    assert store.claim_run(now=101)["run_id"] == second
    assert store.claim_run(now=102) is None


def test_finish_run_clears_active_run(store):
    store.upsert_issue(15, "rev-15", "Title", "https://example.test/15", "user", "open")
    run_id = store.enqueue_run(15, "triage", "triaging")
    store.claim_run(now=100)

    store.finish_run(run_id, "succeeded", result={"candidate": True})

    assert store.get_issue(15)["active_run_id"] is None
    run = store.get_run(run_id)
    assert run["status"] == "succeeded"
    assert run["result"] == {"candidate": True}


def test_initialize_requeues_interrupted_run(tmp_path):
    database_path = tmp_path / "forge.sqlite3"
    first_store = Store(database_path)
    first_store.initialize()
    first_store.upsert_issue(16, "rev-16", "Title", "https://example.test/16", "user", "open")
    run_id = first_store.enqueue_run(16, "triage", "triaging")
    first_store.claim_run(now=100)
    first_store.close()

    recovered_store = Store(database_path)
    recovered_store.initialize()
    try:
        assert recovered_store.get_run(run_id)["status"] == "queued"
        assert recovered_store.claim_run(now=200)["run_id"] == run_id
    finally:
        recovered_store.close()


def test_enqueue_rolls_back_when_transition_is_invalid(store):
    store.upsert_issue(17, "rev-17", "Title", "https://example.test/17", "user", "open")

    with pytest.raises(InvalidTransition):
        store.enqueue_run(17, "fix", "claimed")

    assert store.get_issue(17)["active_run_id"] is None
    count = store.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert count == 0

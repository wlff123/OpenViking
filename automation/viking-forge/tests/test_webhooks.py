import json

import pytest

from viking_forge.security import compute_issue_revision
from viking_forge.store import Store
from viking_forge.webhooks import apply_github_event as _apply_github_event


def apply_github_event(store, event_type, delivery_id, payload, **kwargs):
    return _apply_github_event(
        store,
        event_type,
        delivery_id,
        payload,
        trusted_app_login="vikingforge-wlff123[bot]",
        **kwargs,
    )


def issue_payload(
    action,
    label=None,
    *,
    sender="vikingforge-wlff123[bot]",
    labels=None,
):
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
            "labels": [{"name": name} for name in (labels or [])],
        },
        "sender": {"login": sender},
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
    issue = store.get_issue(8)
    assert issue["bot_state"] == "triaging"
    assert store.get_run(issue["active_run_id"])["kind"] == "triage"


def test_analyze_label_from_another_actor_is_rejected(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))

    result = apply_github_event(
        store,
        "issues",
        "analyze",
        issue_payload("labeled", "agent:analyze", sender="someone-else[bot]"),
    )

    assert result == "rejected"
    assert store.get_issue(8)["bot_state"] == "awaiting_decision"


def test_ignored_label_does_not_start_triage(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))

    apply_github_event(store, "issues", "ignore", issue_payload("labeled", "agent:ignored"))

    assert store.get_issue(8)["bot_state"] == "ignored"


def test_retriage_label_returns_reviewed_issue_to_triaging(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))
    apply_github_event(store, "issues", "analyze", issue_payload("labeled", "agent:analyze"))
    first_run = store.claim_run()
    store.transition_issue(8, "waiting_approval", event_type="triage_complete")
    store.finish_run(first_run["run_id"], "succeeded")

    result = apply_github_event(
        store,
        "issues",
        "retriage",
        issue_payload("labeled", "agent:retriage", sender="maintainer"),
        actor_can_write=True,
    )

    assert result == "applied"
    assert store.get_issue(8)["bot_state"] == "triaging"


def test_retriage_requires_maintainer_permission(tmp_path):
    store = make_store(tmp_path)
    apply_github_event(store, "issues", "open", issue_payload("opened"))

    result = apply_github_event(
        store,
        "issues",
        "retriage",
        issue_payload("labeled", "agent:retriage", sender="contributor"),
        actor_can_write=False,
    )

    assert result == "rejected"
    assert store.get_issue(8)["bot_state"] == "awaiting_decision"


def complete_candidate_triage(store):
    apply_github_event(store, "issues", "open", issue_payload("opened"))
    apply_github_event(store, "issues", "analyze", issue_payload("labeled", "agent:analyze"))
    run = store.claim_run()
    store.update_issue_metadata(
        8,
        triage={
            "summary": "Small fix",
            "candidate": True,
            "needs_info": False,
            "risk_flags": [],
        },
    )
    store.transition_issue(8, "waiting_approval", event_type="triage_complete")
    store.finish_run(run["run_id"], "succeeded")


def test_ready_from_maintainer_queues_fix(tmp_path):
    store = make_store(tmp_path)
    complete_candidate_triage(store)

    result = apply_github_event(
        store,
        "issues",
        "ready",
        issue_payload("labeled", "agent:ready", sender="maintainer", labels=["agent:ready"]),
        actor_can_write=True,
    )

    issue = store.get_issue(8)
    run = store.get_run(issue["active_run_id"])
    assert result == "applied"
    assert issue["bot_state"] == "claimed"
    assert run["kind"] == "fix"
    assert run["issue_revision"] == issue["revision"]


@pytest.mark.parametrize(
    ("triage_update", "labels", "change_revision"),
    [
        ({"candidate": False}, [], False),
        ({"needs_info": True}, [], False),
        ({"risk_flags": ["auth"]}, [], False),
        ({}, ["needs:info"], False),
        ({}, ["agent:human-only"], False),
        ({}, [], True),
    ],
)
def test_ready_rejects_ineligible_or_stale_issue(tmp_path, triage_update, labels, change_revision):
    store = make_store(tmp_path)
    complete_candidate_triage(store)
    issue = store.get_issue(8)
    triage = json.loads(issue["triage_json"])
    triage.update(triage_update)
    store.update_issue_metadata(8, triage=triage)
    payload = issue_payload(
        "labeled", "agent:ready", sender="maintainer", labels=["agent:ready", *labels]
    )
    if change_revision:
        payload["issue"]["body"] = "Changed"

    result = apply_github_event(store, "issues", "ready", payload, actor_can_write=True)

    assert result == "ignored"
    assert store.get_issue(8)["bot_state"] == "waiting_approval"


def test_ready_rejects_non_maintainer(tmp_path):
    store = make_store(tmp_path)
    complete_candidate_triage(store)

    result = apply_github_event(
        store,
        "issues",
        "ready",
        issue_payload("labeled", "agent:ready", sender="contributor"),
        actor_can_write=False,
    )

    assert result == "rejected"
    assert store.get_issue(8)["bot_state"] == "waiting_approval"


def test_unrelated_repository_is_rejected(tmp_path):
    store = make_store(tmp_path)
    payload = issue_payload("opened")
    payload["repository"]["full_name"] = "someone/else"

    assert apply_github_event(store, "issues", "delivery", payload) == "rejected"
    assert store.get_issue(8) is None

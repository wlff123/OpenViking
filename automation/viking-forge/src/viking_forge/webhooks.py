from __future__ import annotations

from typing import Any

from .security import compute_issue_revision
from .store import InvalidTransition, Store


def apply_github_event(
    store: Store,
    event_type: str,
    delivery_id: str,
    payload: dict[str, Any],
    *,
    repository: str = "volcengine/OpenViking",
) -> str:
    if payload.get("repository", {}).get("full_name") != repository:
        return "rejected"
    if not store.record_delivery(f"github:{delivery_id}", event_type):
        return "ignored"
    if event_type != "issues":
        return "ignored"
    issue = payload.get("issue") or {}
    action = payload.get("action")
    issue_number = int(issue["number"])
    if action in {"opened", "reopened", "edited"}:
        store.upsert_issue(
            issue_number,
            compute_issue_revision(str(issue.get("title", "")), issue.get("body")),
            str(issue.get("title", "")),
            str(issue.get("html_url", "")),
            str(issue.get("user", {}).get("login", "unknown")),
            str(issue.get("state", "open")),
        )
        if action == "reopened" and store.get_issue(issue_number)["bot_state"] == "closed":
            store.transition_issue(issue_number, "awaiting_decision", event_type="issue_reopened")
        return "applied"
    if action == "labeled":
        label = payload.get("label", {}).get("name")
        target = {
            "agent:analyze": "triaging",
            "agent:retriage": "triaging",
            "agent:ignored": "ignored",
        }.get(label)
        if target is None:
            return "ignored"
        try:
            store.transition_issue(
                issue_number,
                target,
                event_type="analysis_requested" if target == "triaging" else "decision_ignored",
                payload={"sender": payload.get("sender", {}).get("login")},
            )
        except InvalidTransition:
            return "ignored"
        return "applied"
    if action == "closed":
        try:
            store.transition_issue(issue_number, "closed", event_type="issue_closed")
        except InvalidTransition:
            return "ignored"
        return "applied"
    return "ignored"

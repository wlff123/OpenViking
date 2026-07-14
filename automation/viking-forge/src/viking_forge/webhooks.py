from __future__ import annotations

import json
from typing import Any

from .security import compute_issue_revision
from .store import InvalidTransition, Store


def apply_github_event(
    store: Store,
    event_type: str,
    delivery_id: str,
    payload: dict[str, Any],
    *,
    trusted_app_login: str,
    actor_can_write: bool = False,
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
        label = str(payload.get("label", {}).get("name", ""))
        sender = str(payload.get("sender", {}).get("login", ""))
        if label not in {
            "agent:analyze",
            "agent:retriage",
            "agent:ready",
            "agent:ignored",
        }:
            return "ignored"
        if label in {"agent:analyze", "agent:ignored"} and sender != trusted_app_login:
            return "rejected"
        if label in {"agent:retriage", "agent:ready"} and not actor_can_write:
            return "rejected"
        if store.get_issue(issue_number) is None:
            store.upsert_issue(
                issue_number,
                compute_issue_revision(str(issue.get("title", "")), issue.get("body")),
                str(issue.get("title", "")),
                str(issue.get("html_url", "")),
                str(issue.get("user", {}).get("login", "unknown")),
                str(issue.get("state", "open")),
            )
        try:
            if label in {"agent:analyze", "agent:retriage"}:
                store.enqueue_run(issue_number, "triage", "triaging")
            elif label == "agent:ready":
                if not _eligible_for_fix(store, issue_number, issue):
                    return "ignored"
                store.enqueue_run(issue_number, "fix", "claimed")
            else:
                store.transition_issue(
                    issue_number,
                    "ignored",
                    event_type="decision_ignored",
                    payload={"sender": sender},
                )
        except (InvalidTransition, RuntimeError):
            return "ignored"
        return "applied"
    if action == "closed":
        try:
            store.transition_issue(issue_number, "closed", event_type="issue_closed")
        except InvalidTransition:
            return "ignored"
        return "applied"
    return "ignored"


def _eligible_for_fix(store: Store, issue_number: int, webhook_issue: dict[str, Any]) -> bool:
    issue = store.get_issue(issue_number)
    if issue is None or issue["bot_state"] != "waiting_approval":
        return False
    if issue["revision"] != compute_issue_revision(
        str(webhook_issue.get("title", "")), webhook_issue.get("body")
    ):
        return False
    try:
        triage = json.loads(issue["triage_json"] or "{}")
    except json.JSONDecodeError:
        return False
    if (
        triage.get("candidate") is not True
        or triage.get("needs_info") is True
        or bool(triage.get("risk_flags"))
    ):
        return False
    labels = {str(label.get("name", "")) for label in webhook_issue.get("labels", [])}
    exclusions = {
        "needs:info",
        "agent:human-only",
        "agent:blocked",
        "agent:pr-open",
        "agent:claimed",
    }
    return not labels.intersection(exclusions)

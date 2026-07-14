from __future__ import annotations

from typing import Any

from .store import InvalidTransition, Store


class CallbackConflict(RuntimeError):
    pass


def apply_workflow_callback(store: Store, payload: dict[str, Any]) -> str:
    issue_number = int(payload["issue_number"])
    issue = store.get_issue(issue_number)
    if issue is None:
        raise CallbackConflict("Unknown issue")
    if payload.get("issue_revision") != issue["revision"]:
        raise CallbackConflict("Stale issue revision")
    event_id = str(payload["event_id"])
    if not store.record_delivery(f"callback:{event_id}", "workflow_callback"):
        return "ignored"
    stage = str(payload["stage"])
    try:
        store.transition_issue(
            issue_number,
            stage,
            event_type="workflow_callback",
            payload=payload,
            run_id=payload.get("run_id"),
        )
    except InvalidTransition as exc:
        raise CallbackConflict(str(exc)) from exc
    summary = payload.get("summary")
    store.update_issue_metadata(
        issue_number,
        triage={"summary": summary} if summary else None,
        workflow_url=payload.get("github_run_url"),
        pr_number=payload.get("pr_number"),
        pr_url=payload.get("pr_url"),
    )
    if stage in {"pr_open", "blocked", "merged"}:
        store.enqueue_notification(
            str(payload.get("run_id") or event_id),
            stage,
            {
                "issue_number": issue_number,
                "issue_title": issue["title"],
                "issue_url": issue["issue_url"],
                "status": stage,
                "summary": payload.get("summary"),
                "validation": payload.get("validation"),
                "workflow_url": payload.get("github_run_url"),
                "pr_url": payload.get("pr_url"),
            },
        )
    return "applied"

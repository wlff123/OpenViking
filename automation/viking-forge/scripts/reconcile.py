from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _state(labels: set[str], pull_request: dict[str, Any]) -> str:
    if pull_request.get("merged_at"):
        return "merged"
    if "agent:pr-open" in labels:
        return "pr_open"
    if "agent:claimed" in labels:
        return "claimed"
    if "agent:blocked" in labels:
        return "blocked"
    if "agent:ignored" in labels:
        return "ignored"
    if "agent:analyze" in labels:
        return "triaging"
    if "agent:triaged" in labels:
        return "waiting_approval"
    return "awaiting_decision"


def build_snapshot(
    issues: list[dict[str, Any]],
    pull_requests: list[dict[str, Any]],
    *,
    limit: int = 1000,
) -> dict[str, Any]:
    pr_by_issue = {
        int(pr["issue_number"]): pr for pr in pull_requests if pr.get("issue_number") is not None
    }
    normalized = []
    for issue in issues[:limit]:
        title = str(issue.get("title") or "")
        body = str(issue.get("body") or "")
        labels = {label["name"] for label in issue.get("labels", [])}
        pr = pr_by_issue.get(int(issue["number"]), {})
        normalized.append(
            {
                "issue_number": int(issue["number"]),
                "revision": hashlib.sha256(f"{title}\0{body}".encode()).hexdigest(),
                "title": title,
                "issue_url": issue["html_url"],
                "author": issue.get("user", {}).get("login", "unknown"),
                "github_state": issue.get("state", "open"),
                "bot_state": _state(labels, pr),
                "pr_number": pr.get("number"),
                "pr_url": pr.get("html_url"),
            }
        )
    return {"issues": normalized}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a VikingForge reconciliation snapshot")
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--pull-requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()

    issues = json.loads(args.issues.read_text(encoding="utf-8"))
    pull_requests = json.loads(args.pull_requests.read_text(encoding="utf-8"))
    snapshot = build_snapshot(issues, pull_requests)
    snapshot["snapshot_id"] = args.snapshot_id
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

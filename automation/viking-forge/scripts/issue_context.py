from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _revision(title: str, body: str) -> str:
    import hashlib

    return hashlib.sha256(f"{title}\0{body}".encode()).hexdigest()


def extract_issue_context(payload: dict[str, Any]) -> dict[str, Any]:
    issue = payload["issue"]
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    return {
        "repository": payload["repository"]["full_name"],
        "issue_number": int(issue["number"]),
        "title": title,
        "body": body,
        "issue_url": str(issue["html_url"]),
        "author": str(issue.get("user", {}).get("login", "unknown")),
        "issue_revision": _revision(title, body),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.event:
        raise SystemExit("--event or GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(args.event).read_text(encoding="utf-8"))
    Path(args.output).write_text(
        json.dumps(extract_issue_context(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

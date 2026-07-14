from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .store import Store


SUPPORTED_TYPES = {"pr_open", "blocked", "merged"}


def _text(value: Any, limit: int = 1200) -> str:
    return str(value or "-")[:limit]


def build_card(notification_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if notification_type not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported notification type: {notification_type}")
    target_url = payload.get("pr_url") or payload.get("workflow_url") or payload.get("issue_url")
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"VikingForge: {notification_type}"}
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**#{payload.get('issue_number')} {_text(payload.get('issue_title'), 200)}**\n"
                        f"状态：{_text(payload.get('status'), 100)}\n"
                        f"摘要：{_text(payload.get('summary'))}\n"
                        f"校验：{_text(payload.get('validation'))}"
                    ),
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看详情"},
                            "url": target_url,
                            "type": "primary",
                        }
                    ],
                },
            ],
        },
    }


class NotificationDispatcher:
    def __init__(
        self,
        store: Store,
        webhook_url: str,
        *,
        http_client: httpx.Client | None = None,
    ):
        self.store = store
        self.webhook_url = webhook_url
        self.http_client = http_client or httpx.Client(timeout=10)

    def dispatch_once(self, *, now: int | None = None) -> int:
        timestamp = int(time.time()) if now is None else now
        rows = self.store.claim_notifications(now=timestamp)
        for row in rows:
            run_id = str(row["run_id"])
            notification_type = str(row["notification_type"])
            try:
                payload = json.loads(row["payload_json"])
                response = self.http_client.post(
                    self.webhook_url, json=build_card(notification_type, payload)
                )
                response.raise_for_status()
                response_payload = response.json()
                if response_payload.get("code", 0) != 0:
                    raise RuntimeError(f"Feishu returned code {response_payload.get('code')}")
                self.store.mark_notification_sent(run_id, notification_type, now=timestamp)
            except Exception as exc:
                self.store.mark_notification_failed(
                    run_id,
                    notification_type,
                    str(exc),
                    now=timestamp,
                )
        return len(rows)

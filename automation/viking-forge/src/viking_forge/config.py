from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    repository: str
    database_path: str
    dashboard_username: str
    dashboard_password: str
    dashboard_csrf_secret: str
    github_webhook_secret: str
    callback_secret: str
    github_app_id: str
    github_app_slug: str
    github_app_private_key: str
    feishu_webhook_url: str

    @classmethod
    def from_env(cls) -> "Config":
        required = (
            "REPOSITORY",
            "DATABASE_PATH",
            "DASHBOARD_USERNAME",
            "DASHBOARD_PASSWORD",
            "DASHBOARD_CSRF_SECRET",
            "GITHUB_WEBHOOK_SECRET",
            "CALLBACK_SECRET",
            "GITHUB_APP_ID",
            "GITHUB_APP_SLUG",
            "GITHUB_APP_PRIVATE_KEY",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            repository=os.environ["REPOSITORY"],
            database_path=os.environ["DATABASE_PATH"],
            dashboard_username=os.environ["DASHBOARD_USERNAME"],
            dashboard_password=os.environ["DASHBOARD_PASSWORD"],
            dashboard_csrf_secret=os.environ["DASHBOARD_CSRF_SECRET"],
            github_webhook_secret=os.environ["GITHUB_WEBHOOK_SECRET"],
            callback_secret=os.environ["CALLBACK_SECRET"],
            github_app_id=os.environ["GITHUB_APP_ID"],
            github_app_slug=os.environ["GITHUB_APP_SLUG"],
            github_app_private_key=os.environ["GITHUB_APP_PRIVATE_KEY"].replace("\\n", "\n"),
            feishu_webhook_url=os.environ.get("FEISHU_WEBHOOK_URL", ""),
        )

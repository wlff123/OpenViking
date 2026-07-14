from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    repository: str
    repository_path: str
    database_path: str
    runs_directory: str
    git_remote: str
    base_branch: str
    codex_executable: str
    dashboard_username: str
    dashboard_password: str
    dashboard_csrf_secret: str
    github_webhook_secret: str
    github_app_id: str
    github_app_slug: str
    github_app_private_key: str
    feishu_webhook_url: str

    @classmethod
    def from_env(cls) -> "Config":
        required = (
            "REPOSITORY",
            "REPOSITORY_PATH",
            "DATABASE_PATH",
            "RUNS_DIRECTORY",
            "DASHBOARD_USERNAME",
            "DASHBOARD_PASSWORD",
            "DASHBOARD_CSRF_SECRET",
            "GITHUB_WEBHOOK_SECRET",
            "GITHUB_APP_ID",
            "GITHUB_APP_SLUG",
        )
        missing = [name for name in required if not os.environ.get(name)]
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
        private_key_file = os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE")
        if private_key_file:
            private_key = Path(private_key_file).read_text(encoding="utf-8")
        if not private_key:
            missing.append("GITHUB_APP_PRIVATE_KEY_FILE")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            repository=os.environ["REPOSITORY"],
            repository_path=os.environ["REPOSITORY_PATH"],
            database_path=os.environ["DATABASE_PATH"],
            runs_directory=os.environ["RUNS_DIRECTORY"],
            git_remote=os.environ.get("GIT_REMOTE", "origin"),
            base_branch=os.environ.get("BASE_BRANCH", "main"),
            codex_executable=os.environ.get("CODEX_EXECUTABLE", "codex"),
            dashboard_username=os.environ["DASHBOARD_USERNAME"],
            dashboard_password=os.environ["DASHBOARD_PASSWORD"],
            dashboard_csrf_secret=os.environ["DASHBOARD_CSRF_SECRET"],
            github_webhook_secret=os.environ["GITHUB_WEBHOOK_SECRET"],
            github_app_id=os.environ["GITHUB_APP_ID"],
            github_app_slug=os.environ["GITHUB_APP_SLUG"],
            github_app_private_key=private_key,
            feishu_webhook_url=os.environ.get("FEISHU_WEBHOOK_URL", ""),
        )

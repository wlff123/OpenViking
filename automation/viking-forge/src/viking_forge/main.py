from __future__ import annotations

import threading
from pathlib import Path

from .app import create_app
from .config import Config
from .github import GitHubAppTokenProvider, GitHubClient
from .notifications import NotificationDispatcher
from .store import Store
from .codex import CodexRunner
from .worker import LocalWorker
from .workspace import WorkspaceManager


config = Config.from_env()
store = Store(config.database_path)
store.initialize()
token_provider = GitHubAppTokenProvider(
    app_id=config.github_app_id,
    private_key=config.github_app_private_key,
    repository=config.repository,
)
github = GitHubClient(repository=config.repository, token_provider=token_provider)
project_root = Path(__file__).resolve().parents[2]
workspace = WorkspaceManager(
    config.repository_path,
    config.runs_directory,
    config.git_remote,
    config.base_branch,
)
codex = CodexRunner(
    config.codex_executable,
    project_root / "prompts",
    project_root / "schemas",
)
worker = LocalWorker(
    store,
    workspace,
    codex,
    github,
    base_branch=config.base_branch,
)
dispatcher = NotificationDispatcher(store, config.feishu_webhook_url)
app = create_app(config=config, store=store, github=github)

stop_background_tasks = threading.Event()


def run_worker() -> None:
    while not stop_background_tasks.is_set():
        worked = worker.run_once()
        if not worked:
            stop_background_tasks.wait(2)


def dispatch_notifications() -> None:
    while not stop_background_tasks.wait(10):
        dispatcher.dispatch_once()


@app.on_event("startup")
def start_background_tasks() -> None:
    threading.Thread(
        target=run_worker,
        name="viking-forge-worker",
        daemon=True,
    ).start()
    if config.feishu_webhook_url:
        threading.Thread(
            target=dispatch_notifications,
            name="viking-forge-notifications",
            daemon=True,
        ).start()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_background_tasks.set()
    store.close()

from __future__ import annotations

import threading

from .app import create_app
from .config import Config
from .github import GitHubAppTokenProvider, GitHubClient
from .notifications import NotificationDispatcher
from .store import Store


config = Config.from_env()
store = Store(config.database_path)
store.initialize()
token_provider = GitHubAppTokenProvider(
    app_id=config.github_app_id,
    private_key=config.github_app_private_key,
    repository=config.repository,
)
github = GitHubClient(repository=config.repository, token_provider=token_provider)
app = create_app(config=config, store=store, github=github, start_background_tasks=False)

stop_dispatcher = threading.Event()


def dispatch_notifications() -> None:
    dispatcher = NotificationDispatcher(store, config.feishu_webhook_url)
    while not stop_dispatcher.wait(10):
        dispatcher.dispatch_once()


@app.on_event("startup")
def start_notification_dispatcher() -> None:
    if config.feishu_webhook_url:
        threading.Thread(
            target=dispatch_notifications,
            name="viking-forge-notifications",
            daemon=True,
        ).start()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_dispatcher.set()
    store.close()

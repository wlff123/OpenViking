from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

import httpx
import jwt


class GitHubClient:
    def __init__(
        self,
        *,
        repository: str,
        token_provider: Callable[[], str],
        http_client: httpx.Client | None = None,
    ):
        self.repository = repository
        self.token_provider = token_provider
        self.http_client = http_client or httpx.Client(
            base_url="https://api.github.com",
            timeout=10,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token_provider()}"}

    def get_issue(self, issue_number: int) -> dict:
        response = self.http_client.get(
            f"/repos/{self.repository}/issues/{issue_number}", headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def add_label(self, issue_number: int, label: str) -> None:
        response = self.http_client.post(
            f"/repos/{self.repository}/issues/{issue_number}/labels",
            headers=self._headers(),
            json={"labels": [label]},
        )
        response.raise_for_status()


class GitHubAppTokenProvider:
    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        repository: str,
        http_client: httpx.Client | None = None,
    ):
        self.app_id = app_id
        self.private_key = private_key
        self.repository = repository
        self.http_client = http_client or httpx.Client(
            base_url="https://api.github.com",
            timeout=10,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        self._installation_id: int | None = None
        self._token: str | None = None
        self._expires_at = 0.0

    def __call__(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        app_jwt = self._create_app_jwt()
        headers = {"Authorization": f"Bearer {app_jwt}"}
        if self._installation_id is None:
            response = self.http_client.get(
                f"/repos/{self.repository}/installation", headers=headers
            )
            response.raise_for_status()
            self._installation_id = int(response.json()["id"])
        response = self.http_client.post(
            f"/app/installations/{self._installation_id}/access_tokens",
            headers=headers,
            json={"repositories": [self.repository.split("/", 1)[1]]},
        )
        response.raise_for_status()
        payload = response.json()
        self._token = str(payload["token"])
        self._expires_at = datetime.fromisoformat(
            payload["expires_at"].replace("Z", "+00:00")
        ).timestamp()
        return self._token

    def _create_app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )

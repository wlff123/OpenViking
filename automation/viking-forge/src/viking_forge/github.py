from __future__ import annotations

import base64
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

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

    def remove_label(self, issue_number: int, label: str) -> None:
        response = self.http_client.delete(
            f"/repos/{self.repository}/issues/{issue_number}/labels/{quote(label, safe='')}",
            headers=self._headers(),
        )
        if response.status_code != 404:
            response.raise_for_status()

    def get_collaborator_permission(self, login: str) -> str:
        response = self.http_client.get(
            f"/repos/{self.repository}/collaborators/{quote(login, safe='')}/permission",
            headers=self._headers(),
        )
        response.raise_for_status()
        return str(response.json()["permission"])

    def upsert_triage_comment(self, issue_number: int, body: str) -> None:
        marker = "<!-- viking-forge-triage -->"
        rendered = body.rstrip() + f"\n\n{marker}"
        response = self.http_client.get(
            f"/repos/{self.repository}/issues/{issue_number}/comments",
            headers=self._headers(),
            params={"per_page": 100},
        )
        response.raise_for_status()
        existing = next(
            (comment for comment in response.json() if marker in str(comment.get("body", ""))),
            None,
        )
        if existing:
            response = self.http_client.patch(
                f"/repos/{self.repository}/issues/comments/{existing['id']}",
                headers=self._headers(),
                json={"body": rendered},
            )
        else:
            response = self.http_client.post(
                f"/repos/{self.repository}/issues/{issue_number}/comments",
                headers=self._headers(),
                json={"body": rendered},
            )
        response.raise_for_status()

    def create_branch_from_files(
        self,
        base_sha: str,
        branch: str,
        worktree: str | Path,
        changed: list[dict],
        message: str,
    ) -> str:
        root = Path(worktree).resolve()
        tree = []
        for item in changed:
            path = str(item["path"]).replace("\\", "/")
            pure_path = PurePosixPath(path)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise ValueError(f"Invalid changed path: {path}")
            mode = str(item.get("mode", "100644"))
            if mode not in {"100644", "100755"}:
                raise ValueError(f"Unsupported file mode: {mode}")
            blob_sha = None
            if item.get("status") != "D":
                file_path = (root / path).resolve()
                if not file_path.is_relative_to(root) or not file_path.is_file():
                    raise ValueError(f"Changed file is outside worktree: {path}")
                response = self.http_client.post(
                    f"/repos/{self.repository}/git/blobs",
                    headers=self._headers(),
                    json={
                        "content": base64.b64encode(file_path.read_bytes()).decode(),
                        "encoding": "base64",
                    },
                )
                response.raise_for_status()
                blob_sha = str(response.json()["sha"])
            tree.append({"path": path, "mode": mode, "type": "blob", "sha": blob_sha})

        response = self.http_client.post(
            f"/repos/{self.repository}/git/trees",
            headers=self._headers(),
            json={"base_tree": base_sha, "tree": tree},
        )
        response.raise_for_status()
        tree_sha = str(response.json()["sha"])
        response = self.http_client.post(
            f"/repos/{self.repository}/git/commits",
            headers=self._headers(),
            json={"message": message, "tree": tree_sha, "parents": [base_sha]},
        )
        response.raise_for_status()
        commit_sha = str(response.json()["sha"])
        response = self.http_client.post(
            f"/repos/{self.repository}/git/refs",
            headers=self._headers(),
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        response.raise_for_status()
        return commit_sha

    def create_draft_pr(self, branch: str, base: str, title: str, body: str) -> dict:
        response = self.http_client.post(
            f"/repos/{self.repository}/pulls",
            headers=self._headers(),
            json={
                "head": branch,
                "base": base,
                "title": title,
                "body": body,
                "draft": True,
            },
        )
        response.raise_for_status()
        return response.json()


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

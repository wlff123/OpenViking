from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Config
from .callbacks import CallbackConflict, apply_workflow_callback
from .security import compute_issue_revision, verify_hmac_signature
from .store import Store
from .webhooks import apply_github_event


class GitHubDecisions(Protocol):
    def get_issue(self, issue_number: int) -> dict: ...

    def add_label(self, issue_number: int, label: str) -> None: ...

    def get_collaborator_permission(self, login: str) -> str: ...


def create_app(
    *,
    config: Config,
    store: Store,
    github: GitHubDecisions,
    start_background_tasks: bool = True,
) -> FastAPI:
    del start_background_tasks
    package_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=package_dir / "templates")
    security = HTTPBasic(auto_error=False)
    app = FastAPI(title="VikingForge", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")

    def require_auth(
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )
        valid_user = hmac.compare_digest(credentials.username, config.dashboard_username)
        valid_password = hmac.compare_digest(credentials.password, config.dashboard_password)
        if not (valid_user and valid_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/github")
    async def github_webhook(request: Request) -> dict[str, str]:
        body = await request.body()
        if not verify_hmac_signature(
            config.github_webhook_secret.encode(),
            body,
            request.headers.get("X-Hub-Signature-256"),
            prefix="sha256=",
        ):
            raise HTTPException(status_code=403, detail="Invalid GitHub signature")
        event_type = request.headers.get("X-GitHub-Event")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        if not event_type or not delivery_id:
            raise HTTPException(status_code=400, detail="Missing GitHub event headers")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        actor_can_write = False
        label = payload.get("label", {}).get("name")
        if (
            event_type == "issues"
            and payload.get("action") == "labeled"
            and label in {"agent:ready", "agent:retriage"}
        ):
            login = str(payload.get("sender", {}).get("login", ""))
            try:
                permission = github.get_collaborator_permission(login)
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail="GitHub permission check failed"
                ) from exc
            actor_can_write = permission in {"admin", "maintain", "write"}
        result = apply_github_event(
            store,
            event_type,
            delivery_id,
            payload,
            trusted_app_login=f"{config.github_app_slug}[bot]",
            actor_can_write=actor_can_write,
            repository=config.repository,
        )
        if result == "rejected":
            raise HTTPException(status_code=403, detail="Rejected GitHub event")
        return {"status": result}

    @app.post("/callbacks/workflow")
    async def workflow_callback(request: Request) -> dict[str, str]:
        body = await request.body()
        if not verify_hmac_signature(
            config.callback_secret.encode(),
            body,
            request.headers.get("X-Viking-Forge-Signature"),
        ):
            raise HTTPException(status_code=403, detail="Invalid callback signature")
        try:
            payload = json.loads(body)
            result = apply_workflow_callback(store, payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid callback") from exc
        except CallbackConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": result}

    @app.post("/callbacks/reconcile")
    async def reconcile_callback(request: Request) -> dict[str, str]:
        body = await request.body()
        if not verify_hmac_signature(
            config.callback_secret.encode(),
            body,
            request.headers.get("X-Viking-Forge-Signature"),
        ):
            raise HTTPException(status_code=403, detail="Invalid callback signature")
        try:
            payload = json.loads(body)
            snapshot_id = str(payload["snapshot_id"])
            issues = payload["issues"]
            if not isinstance(issues, list):
                raise TypeError("issues must be a list")
            if not store.record_delivery(f"reconcile:{snapshot_id}", "reconcile_snapshot"):
                return {"status": "ignored"}
            store.apply_snapshot(issues)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid snapshot") from exc
        return {"status": "applied"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        state: str | None = None,
        _username: str = Depends(require_auth),
    ) -> HTMLResponse:
        issues = store.list_issues(state)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "issues": issues,
                "selected_state": state,
                "csrf_token": config.dashboard_csrf_secret,
            },
        )

    @app.post("/issues/{issue_number}/decision")
    def decide_issue(
        issue_number: int,
        decision: str = Form(...),
        csrf_token: str = Form(...),
        _username: str = Depends(require_auth),
    ) -> RedirectResponse:
        if not hmac.compare_digest(csrf_token, config.dashboard_csrf_secret):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        labels = {"ignore": "agent:ignored", "analyze": "agent:analyze"}
        label = labels.get(decision)
        if label is None:
            raise HTTPException(status_code=400, detail="Unknown decision")
        issue = store.get_issue(issue_number)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if issue["bot_state"] != "awaiting_decision":
            raise HTTPException(status_code=409, detail="Issue is not awaiting a decision")
        try:
            live_issue = github.get_issue(issue_number)
            live_revision = compute_issue_revision(live_issue["title"], live_issue.get("body"))
            if live_issue.get("state") != "open" or live_revision != issue["revision"]:
                raise HTTPException(status_code=409, detail="Issue changed or closed")
            github.add_label(issue_number, label)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="GitHub decision failed") from exc
        return RedirectResponse(url="/", status_code=303)

    return app

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from . import validation
from .security import compute_issue_revision
from .store import InvalidTransition, Store


class Workspace(Protocol):
    runs_directory: Path

    def prepare(self, run_id: str) -> tuple[Path, str]: ...

    def cleanup(self, worktree: Path) -> None: ...


class Codex(Protocol):
    def run(
        self,
        kind: str,
        worktree: Path,
        run_directory: Path,
        issue_context: dict[str, Any],
        triage: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class GitHub(Protocol):
    repository: str

    def get_issue(self, issue_number: int) -> dict[str, Any]: ...

    def upsert_triage_comment(self, issue_number: int, body: str) -> None: ...

    def add_label(self, issue_number: int, label: str) -> None: ...

    def remove_label(self, issue_number: int, label: str) -> None: ...

    def create_branch_from_files(
        self,
        base_sha: str,
        branch: str,
        worktree: Path,
        changed: list[dict[str, Any]],
        message: str,
    ) -> str: ...

    def create_draft_pr(self, branch: str, base: str, title: str, body: str) -> dict[str, Any]: ...


class LocalWorker:
    def __init__(
        self,
        store: Store,
        workspace: Workspace,
        codex: Codex,
        github: GitHub,
        *,
        base_branch: str,
    ):
        self.store = store
        self.workspace = workspace
        self.codex = codex
        self.github = github
        self.base_branch = base_branch

    def run_once(self) -> bool:
        run = self.store.claim_run()
        if run is None:
            return False
        worktree: Path | None = None
        try:
            issue = self._live_issue(run)
            worktree, base_sha = self.workspace.prepare(str(run["run_id"]))
            if run["kind"] == "triage":
                self._run_triage(run, issue, worktree)
            elif run["kind"] == "fix":
                self._run_fix(run, issue, worktree, base_sha)
            else:
                raise RuntimeError(f"Unknown run kind: {run['kind']}")
        except Exception as exc:
            self._fail_run(run, exc)
        finally:
            if worktree is not None:
                try:
                    self.workspace.cleanup(worktree)
                except Exception:
                    pass
        return True

    def _live_issue(self, run: dict[str, Any]) -> dict[str, Any]:
        issue = self.github.get_issue(int(run["issue_number"]))
        revision = compute_issue_revision(str(issue.get("title", "")), issue.get("body"))
        if issue.get("state") != "open" or revision != run["issue_revision"]:
            raise RuntimeError("Issue changed or closed after the run was queued")
        return issue

    def _context(self, issue: dict[str, Any], revision: str) -> dict[str, Any]:
        return {
            "repository": self.github.repository,
            "issue_number": int(issue["number"]),
            "title": str(issue.get("title") or ""),
            "body": str(issue.get("body") or ""),
            "issue_url": str(issue.get("html_url") or ""),
            "author": str(issue.get("user", {}).get("login", "unknown")),
            "issue_revision": revision,
        }

    def _run_triage(
        self,
        run: dict[str, Any],
        issue: dict[str, Any],
        worktree: Path,
    ) -> None:
        run_id = str(run["run_id"])
        issue_number = int(run["issue_number"])
        result = self.codex.run(
            "triage",
            worktree,
            self.workspace.runs_directory / run_id,
            self._context(issue, str(run["issue_revision"])),
        )
        required = {
            "summary",
            "category",
            "confidence",
            "candidate",
            "needs_info",
            "risk_flags",
        }
        if not required.issubset(result):
            raise RuntimeError("Codex triage result is incomplete")
        self._live_issue(run)
        self.github.upsert_triage_comment(issue_number, _triage_comment(result))
        self.github.add_label(issue_number, "agent:triaged")
        self.github.remove_label(issue_number, "agent:analyze")
        self.github.remove_label(issue_number, "agent:retriage")
        if result["needs_info"]:
            self.github.add_label(issue_number, "needs:info")
        else:
            self.github.remove_label(issue_number, "needs:info")
        if result["candidate"]:
            self.github.remove_label(issue_number, "agent:blocked")
        else:
            self.github.add_label(issue_number, "agent:blocked")
        self.store.update_issue_metadata(issue_number, triage=result)
        self.store.update_issue_error(issue_number, None)
        self.store.transition_issue(
            issue_number,
            "waiting_approval",
            event_type="triage_complete",
            run_id=run_id,
        )
        self.store.finish_run(run_id, "succeeded", result=result)

    def _run_fix(
        self,
        run: dict[str, Any],
        issue: dict[str, Any],
        worktree: Path,
        base_sha: str,
    ) -> None:
        run_id = str(run["run_id"])
        issue_number = int(run["issue_number"])
        stored_issue = self.store.get_issue(issue_number)
        triage = json.loads(stored_issue["triage_json"] or "{}")
        self.store.transition_issue(issue_number, "coding", event_type="fix_coding", run_id=run_id)
        result = self.codex.run(
            "fix",
            worktree,
            self.workspace.runs_directory / run_id,
            self._context(issue, str(run["issue_revision"])),
            triage=triage,
        )
        if not {"summary", "tests", "risks"}.issubset(result):
            raise RuntimeError("Codex fix result is incomplete")
        self.store.transition_issue(
            issue_number, "validating", event_type="fix_validating", run_id=run_id
        )
        changed = validation.inspect_changes(worktree, base_sha)
        validation.validate_changed_files(changed)
        validation_results = validation.run_validation(worktree, changed)
        self.store.transition_issue(
            issue_number, "publishing", event_type="fix_publishing", run_id=run_id
        )
        self._live_issue(run)
        branch = f"agent/issue-{issue_number}-{run_id}"
        self.github.create_branch_from_files(
            base_sha,
            branch,
            worktree,
            changed,
            f"fix: resolve issue #{issue_number}",
        )
        summary = str(result["summary"]).strip()
        title_summary = " ".join(summary.split())[:80]
        pull_request = self.github.create_draft_pr(
            branch,
            self.base_branch,
            f"Fix #{issue_number}: {title_summary}",
            f"Closes #{issue_number}\n\n由 VikingForge 本地 Codex 生成，等待维护者审核。",
        )
        pr_number = int(pull_request["number"])
        pr_url = str(pull_request["html_url"])
        self.github.add_label(pr_number, "agent:generated")
        self.github.add_label(issue_number, "agent:pr-open")
        for label in ("agent:ready", "agent:claimed", "agent:blocked"):
            self.github.remove_label(issue_number, label)
        persisted_result = {
            "codex": result,
            "changed": changed,
            "validation": validation_results,
        }
        self.store.record_pr_open(
            issue_number,
            run_id,
            pr_number,
            pr_url,
            {
                "issue_number": issue_number,
                "issue_title": issue["title"],
                "issue_url": issue["html_url"],
                "status": "pr_open",
                "summary": summary,
                "validation": validation_results,
                "pr_url": pr_url,
            },
            run_result=persisted_result,
        )

    def _fail_run(self, run: dict[str, Any], error: Exception) -> None:
        run_id = str(run["run_id"])
        issue_number = int(run["issue_number"])
        message = str(error) or error.__class__.__name__
        issue = self.store.get_issue(issue_number)
        current_run = self.store.get_run(run_id)
        if current_run and current_run["status"] in {"succeeded", "failed"}:
            return
        if issue and issue["bot_state"] == "closed":
            self.store.finish_run(run_id, "failed", error=message)
            return
        if issue and issue["bot_state"] != "blocked":
            try:
                self.store.transition_issue(
                    issue_number,
                    "blocked",
                    event_type="run_failed",
                    payload={"error": message[-2000:]},
                    run_id=run_id,
                )
            except InvalidTransition:
                pass
        self.store.update_issue_error(issue_number, message)
        self.store.finish_run(run_id, "failed", error=message)
        self.store.enqueue_notification(
            run_id,
            "blocked",
            {
                "issue_number": issue_number,
                "issue_title": issue["title"] if issue else "",
                "issue_url": issue["issue_url"] if issue else "",
                "status": "blocked",
                "summary": message[-1200:],
                "validation": "-",
            },
        )
        for label in ("agent:claimed", "agent:analyze", "agent:retriage", "agent:ready"):
            try:
                self.github.remove_label(issue_number, label)
            except Exception:
                pass
        try:
            self.github.add_label(issue_number, "agent:blocked")
        except Exception:
            pass


def _triage_comment(result: dict[str, Any]) -> str:
    risks = "、".join(str(value) for value in result["risk_flags"]) or "无"
    return (
        "## VikingForge 分诊\n\n"
        f"{result['summary']}\n\n"
        f"- 分类：`{result['category']}`\n"
        f"- 可自动修复候选：`{str(bool(result['candidate'])).lower()}`\n"
        f"- 需要补充信息：`{str(bool(result['needs_info'])).lower()}`\n"
        f"- 置信度：`{result['confidence']}`\n"
        f"- 风险：{risks}"
    )

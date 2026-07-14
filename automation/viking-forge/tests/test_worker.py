import json

from viking_forge.codex import CodexExecutionError
from viking_forge.security import compute_issue_revision
from viking_forge.store import Store
from viking_forge.worker import LocalWorker


class FakeWorkspace:
    def __init__(self, root):
        self.runs_directory = root / "runs"
        self.cleaned = []

    def prepare(self, run_id):
        worktree = self.runs_directory / run_id / "worktree"
        worktree.mkdir(parents=True)
        return worktree, "base-sha"

    def cleanup(self, worktree):
        self.cleaned.append(worktree)


class FakeCodex:
    def __init__(self, result=None, error=None, write_fix=False):
        self.result = result
        self.error = error
        self.write_fix = write_fix
        self.calls = []

    def run(self, kind, worktree, run_dir, issue_context, triage=None):
        self.calls.append((kind, worktree, run_dir, issue_context, triage))
        if self.error:
            raise self.error
        if self.write_fix:
            source = worktree / "openviking" / "a.py"
            source.parent.mkdir()
            source.write_text("value = 2\n", encoding="utf-8")
            test = worktree / "tests" / "test_a.py"
            test.parent.mkdir()
            test.write_text("def test_a():\n    assert True\n", encoding="utf-8")
        return self.result


class FakeGitHub:
    def __init__(self, issue):
        self.repository = "volcengine/OpenViking"
        self.issue = issue
        self.comments = []
        self.added_labels = []
        self.removed_labels = []
        self.branches = []
        self.pull_requests = []
        self.get_issue_calls = 0

    def get_issue(self, issue_number):
        self.get_issue_calls += 1
        return dict(self.issue)

    def upsert_triage_comment(self, issue_number, body):
        self.comments.append((issue_number, body))

    def add_label(self, issue_number, label):
        self.added_labels.append((issue_number, label))

    def remove_label(self, issue_number, label):
        self.removed_labels.append((issue_number, label))

    def create_branch_from_files(self, base_sha, branch, worktree, changed, message):
        self.branches.append((base_sha, branch, worktree, changed, message))
        return "commit-sha"

    def create_draft_pr(self, branch, base, title, body):
        self.pull_requests.append((branch, base, title, body))
        return {"number": 99, "html_url": "https://example.test/pull/99"}


def make_store(tmp_path):
    store = Store(tmp_path / "forge.sqlite3")
    store.initialize()
    return store


def live_issue(number=8):
    return {
        "number": number,
        "title": "Parser crash",
        "body": "Steps",
        "html_url": f"https://example.test/issues/{number}",
        "state": "open",
        "user": {"login": "reporter"},
    }


def add_issue(store, number=8):
    issue = live_issue(number)
    store.upsert_issue(
        number,
        compute_issue_revision(issue["title"], issue["body"]),
        issue["title"],
        issue["html_url"],
        "reporter",
        "open",
    )


def test_triage_lifecycle_publishes_result_and_completes_run(tmp_path):
    store = make_store(tmp_path)
    add_issue(store)
    run_id = store.enqueue_run(8, "triage", "triaging")
    workspace = FakeWorkspace(tmp_path)
    triage = {
        "summary": "Small parser fix",
        "category": "bug",
        "confidence": 0.9,
        "candidate": True,
        "needs_info": False,
        "risk_flags": [],
    }
    codex = FakeCodex(triage)
    github = FakeGitHub(live_issue())
    worker = LocalWorker(store, workspace, codex, github, base_branch="main")

    assert worker.run_once() is True

    issue = store.get_issue(8)
    run = store.get_run(run_id)
    assert run["status"] == "succeeded"
    assert run["result"] == triage
    assert issue["bot_state"] == "waiting_approval"
    assert issue["active_run_id"] is None
    assert json.loads(issue["triage_json"]) == triage
    assert github.comments[0][0] == 8
    assert "Small parser fix" in github.comments[0][1]
    assert (8, "agent:triaged") in github.added_labels
    assert (8, "agent:analyze") in github.removed_labels
    assert workspace.cleaned == [codex.calls[0][1]]


def test_fix_lifecycle_validates_publishes_draft_pr_and_notifies(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    add_issue(store)
    store.transition_issue(8, "triaging", event_type="analysis_requested")
    triage = {
        "summary": "Small parser fix",
        "candidate": True,
        "needs_info": False,
        "risk_flags": [],
    }
    store.update_issue_metadata(8, triage=triage)
    store.transition_issue(8, "waiting_approval", event_type="triage_complete")
    run_id = store.enqueue_run(8, "fix", "claimed")
    workspace = FakeWorkspace(tmp_path)
    codex = FakeCodex(
        {"summary": "Guard empty input", "tests": ["pytest"], "risks": []},
        write_fix=True,
    )
    github = FakeGitHub(live_issue())
    changed = [
        {"path": "openviking/a.py", "status": "M", "mode": "100644"},
        {"path": "tests/test_a.py", "status": "A", "mode": "100644"},
    ]
    validation_results = [{"command": ["pytest"], "exit_code": 0, "output": "ok"}]
    monkeypatch.setattr("viking_forge.worker.validation.inspect_changes", lambda *_: changed)
    monkeypatch.setattr("viking_forge.worker.validation.validate_changed_files", lambda _: None)
    monkeypatch.setattr(
        "viking_forge.worker.validation.run_validation", lambda *_: validation_results
    )
    worker = LocalWorker(store, workspace, codex, github, base_branch="main")

    assert worker.run_once() is True

    issue = store.get_issue(8)
    assert store.get_run(run_id)["status"] == "succeeded"
    assert issue["bot_state"] == "pr_open"
    assert issue["pr_number"] == 99
    assert issue["pr_url"] == "https://example.test/pull/99"
    events = [
        row[0]
        for row in store.connection.execute(
            "SELECT event_type FROM events WHERE issue_number = 8 ORDER BY id"
        )
    ]
    assert events[-4:] == ["fix_coding", "fix_validating", "fix_publishing", "pr_opened"]
    assert github.get_issue_calls == 2
    assert github.branches[0][0] == "base-sha"
    assert github.branches[0][1].startswith("agent/issue-8-")
    assert github.branches[0][3] == changed
    assert github.pull_requests[0][1] == "main"
    assert (99, "agent:generated") in github.added_labels
    assert (8, "agent:pr-open") in github.added_labels
    notification = store.get_notification(run_id, "pr_open")
    assert notification is not None
    assert json.loads(notification["payload_json"])["pr_url"].endswith("/99")
    assert workspace.cleaned == [codex.calls[0][1]]


def test_worker_failure_blocks_issue_records_error_and_notifies(tmp_path):
    store = make_store(tmp_path)
    add_issue(store)
    run_id = store.enqueue_run(8, "triage", "triaging")
    workspace = FakeWorkspace(tmp_path)
    codex = FakeCodex(error=CodexExecutionError("model failed"))
    github = FakeGitHub(live_issue())
    worker = LocalWorker(store, workspace, codex, github, base_branch="main")

    assert worker.run_once() is True

    issue = store.get_issue(8)
    run = store.get_run(run_id)
    assert run["status"] == "failed"
    assert run["error"] == "model failed"
    assert issue["bot_state"] == "blocked"
    assert issue["last_error"] == "model failed"
    assert (8, "agent:blocked") in github.added_labels
    assert store.get_notification(run_id, "blocked") is not None
    assert len(workspace.cleaned) == 1


def test_worker_returns_false_when_queue_is_empty(tmp_path):
    store = make_store(tmp_path)
    worker = LocalWorker(
        store,
        FakeWorkspace(tmp_path),
        FakeCodex(),
        FakeGitHub(live_issue()),
        base_branch="main",
    )

    assert worker.run_once() is False

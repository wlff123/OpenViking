# VikingForge 本地执行改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Codex 分诊、修复、验证和 PR 发布全部迁移到维护者本地机器，并删除 GitHub Actions 执行面和仓库端密钥。

**Architecture:** FastAPI、SQLite 队列和单 Worker 运行在同一个受信任进程中。每个任务创建独立 Git worktree，并启动独立的 `codex exec --ephemeral`；Codex 不继承发布密钥，GitHub App 发布发生在 Codex 退出和确定性验证通过之后。

**Tech Stack:** Python 3.10+、FastAPI、SQLite、httpx、Codex CLI、Git worktree、pytest。

## Global Constraints

- 全部新增代码、测试、部署资源和文档必须位于 `automation/viking-forge/`。
- 删除 `.github/workflows/agent-triage.yml`、`agent-fix.yml` 和 `agent-reconcile.yml`，保留 OpenViking 原有 CI。
- GitHub 不保存 VikingForge Secret、Variable 或 OpenAI API Key。
- 每个运行使用独立 worktree 和独立 `codex exec --ephemeral` 会话。
- Codex 子进程不得继承 GitHub App、Webhook、飞书或面板密钥。
- 自动补丁最多修改 5 个文件和 500 行；禁止修改 `.github/`、`automation/`、依赖、认证和安全策略。
- 自动化只创建草稿 PR，不批准、不转 Ready、不合并。

---

### Task 1: SQLite 本地运行队列

**Files:**
- Modify: `automation/viking-forge/src/viking_forge/store.py`
- Modify: `automation/viking-forge/tests/test_store.py`

**Interfaces:**
- Produces: `Store.enqueue_run(issue_number, kind, target_state) -> str`
- Produces: `Store.claim_run(now=None) -> dict | None`
- Produces: `Store.finish_run(run_id, status, result=None, error=None) -> None`
- Produces: `Store.get_run(run_id) -> dict | None`

- [ ] **Step 1: Write failing queue tests**

Add tests proving that enqueue changes the Issue state atomically, duplicate active work is rejected, claim is FIFO, completion clears `active_run_id`, and initialization returns interrupted `running` work to `queued`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_store.py`

Expected: failures because the `runs` table and queue methods do not exist.

- [ ] **Step 3: Implement the minimal queue**

Create a `runs` table with `run_id`, `issue_number`, `kind`, `issue_revision`, `status`, `result_json`, `error`, and timestamps. Use `BEGIN IMMEDIATE` for enqueue and claim, one active run per Issue, UUID run IDs, and startup recovery from `running` to `queued`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `uv run pytest -q tests/test_store.py`

Commit: `feat:add-local-run-queue`

### Task 2: 独立 worktree 和本地 Codex 执行器

**Files:**
- Create: `automation/viking-forge/src/viking_forge/workspace.py`
- Create: `automation/viking-forge/src/viking_forge/codex.py`
- Create: `automation/viking-forge/tests/test_workspace.py`
- Create: `automation/viking-forge/tests/test_codex.py`

**Interfaces:**
- Produces: `WorkspaceManager.prepare(run_id) -> tuple[Path, str]`
- Produces: `WorkspaceManager.cleanup(worktree) -> None`
- Produces: `CodexRunner.run(kind, worktree, run_dir, issue_context, triage=None) -> dict`

- [ ] **Step 1: Write failing worktree tests**

Use a temporary real Git repository to prove `prepare` creates an external detached worktree at the configured base ref and `cleanup` removes only that worktree.

- [ ] **Step 2: Verify RED and implement worktree manager**

Run: `uv run pytest -q tests/test_workspace.py`

Implement subprocess calls without `shell=True`: fetch configured remote/branch, resolve the base SHA, create the run artifact directory, add a detached worktree, and prune it on cleanup.

- [ ] **Step 3: Write failing Codex command tests**

Inject a fake executable that records arguments and environment, writes valid JSON, and verify:

```python
assert "--ephemeral" in command
assert command[command.index("--sandbox") + 1] == "read-only"
assert "GITHUB_APP_PRIVATE_KEY" not in child_environment
```

Add a second test requiring `workspace-write` for `fix`, plus failure tests for nonzero exit and invalid JSON.

- [ ] **Step 4: Implement the minimal Codex runner**

Write `issue-context.json` and optional `triage.json` into the worktree, invoke the local CLI with the matching prompt and Schema, write logs/results under the run directory, parse the final JSON, and always remove temporary context files before returning.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest -q tests/test_workspace.py tests/test_codex.py`

Commit: `feat:add-isolated-local-codex-runner`

### Task 3: 本地补丁门禁和确定性验证

**Files:**
- Create: `automation/viking-forge/src/viking_forge/validation.py`
- Delete: `automation/viking-forge/scripts/guard_patch.py`
- Delete: `automation/viking-forge/scripts/validate_patch.py`
- Modify: `automation/viking-forge/tests/test_scripts.py`

**Interfaces:**
- Produces: `inspect_changes(worktree, base_sha) -> list[dict]`
- Produces: `validate_changed_files(changed) -> None`
- Produces: `run_validation(worktree, changed) -> list[dict]`

- [ ] **Step 1: Move tests to the package API and verify RED**

Change imports from `scripts.*` to `viking_forge.validation`, add a real Git diff test for `inspect_changes`, and run `uv run pytest -q tests/test_scripts.py`.

- [ ] **Step 2: Implement the package module**

Move existing 5-file/500-line policy without widening it. Run commands with an explicit worktree `cwd`, capture bounded output, stop on first failure, and raise `ValidationError` containing results.

- [ ] **Step 3: Delete obsolete scripts, verify, and commit**

Run: `uv run pytest -q tests/test_scripts.py`

Commit: `refactor:move-patch-validation-local`

### Task 4: GitHub 本地发布器

**Files:**
- Modify: `automation/viking-forge/src/viking_forge/github.py`
- Modify: `automation/viking-forge/tests/test_github.py`

**Interfaces:**
- Produces: `GitHubClient.get_collaborator_permission(login) -> str`
- Produces: `GitHubClient.remove_label(issue_number, label) -> None`
- Produces: `GitHubClient.upsert_triage_comment(issue_number, body) -> None`
- Produces: `GitHubClient.create_branch_from_files(base_sha, branch, worktree, changed, message) -> str`
- Produces: `GitHubClient.create_draft_pr(branch, base, title, body) -> dict`

- [ ] **Step 1: Write failing HTTP contract tests**

Use `httpx.MockTransport` to assert exact GitHub REST paths and payloads for permission checks, comment upsert, label removal, Git blob/tree/commit/ref creation, and draft PR creation.

- [ ] **Step 2: Verify RED and implement**

Run: `uv run pytest -q tests/test_github.py`

Publish changed text files through the Git Data API so no installation token enters Git command arguments or Codex environment. Use `sha: null` for deletions and preserve executable mode from the worktree index.

- [ ] **Step 3: Verify GREEN and commit**

Commit: `feat:add-local-github-publisher`

### Task 5: Webhook 授权和本地任务入队

**Files:**
- Modify: `automation/viking-forge/src/viking_forge/webhooks.py`
- Modify: `automation/viking-forge/src/viking_forge/app.py`
- Modify: `automation/viking-forge/tests/test_webhooks.py`
- Modify: `automation/viking-forge/tests/test_app.py`

**Interfaces:**
- Consumes: Store queue methods and `GitHubClient.get_collaborator_permission`
- Produces: trusted `agent:analyze`/`agent:retriage` triage jobs and `agent:ready` fix jobs

- [ ] **Step 1: Write failing authorization tests**

Cover app-bot-only `agent:analyze`, maintainer-only `agent:retriage` and `agent:ready`, candidate/revision/exclusion gates, duplicate delivery idempotency, and rejection of non-write actors.

- [ ] **Step 2: Verify RED and implement**

Run: `uv run pytest -q tests/test_webhooks.py tests/test_app.py`

The webhook endpoint obtains collaborator permission only for maintainer labels, then passes the verified fact into the pure event handler. The event handler atomically enqueues `triage` or `fix`; the UI still only offers ignore/analyze.

- [ ] **Step 3: Verify GREEN and commit**

Commit: `feat:queue-local-runs-from-webhooks`

### Task 6: 本地 Worker 生命周期

**Files:**
- Create: `automation/viking-forge/src/viking_forge/worker.py`
- Create: `automation/viking-forge/tests/test_worker.py`
- Modify: `automation/viking-forge/src/viking_forge/store.py`

**Interfaces:**
- Produces: `LocalWorker.run_once() -> bool`
- Consumes: Store, WorkspaceManager, CodexRunner, validation API and GitHubClient

- [ ] **Step 1: Write failing triage lifecycle test**

With fake collaborators, assert `queued -> running -> succeeded`, Issue `triaging -> waiting_approval`, structured result persistence, fixed-marker comment upsert, and lifecycle label cleanup.

- [ ] **Step 2: Implement triage and verify GREEN**

Run: `uv run pytest -q tests/test_worker.py -k triage`

- [ ] **Step 3: Write failing fix lifecycle test**

Assert `claimed -> coding -> validating -> publishing -> pr_open`, live revision recheck, policy/validation execution, Git Data API branch publication, draft PR metadata, `agent:generated`/`agent:pr-open` labels, and Feishu Outbox entry.

- [ ] **Step 4: Implement fix and failure handling**

On any Codex, Git, policy or validation error, complete the run as failed, move the Issue to `blocked`, save a bounded error, remove active labels, add `agent:blocked`, enqueue a blocked notification, and always clean the worktree.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest -q tests/test_worker.py`

Commit: `feat:add-local-vikingforge-worker`

### Task 7: 运行时、界面和错误架构清理

**Files:**
- Modify: `automation/viking-forge/src/viking_forge/config.py`
- Modify: `automation/viking-forge/src/viking_forge/main.py`
- Modify: `automation/viking-forge/src/viking_forge/templates/index.html`
- Modify: `automation/viking-forge/src/viking_forge/notifications.py`
- Delete: `automation/viking-forge/src/viking_forge/callbacks.py`
- Delete: `automation/viking-forge/scripts/post_callback.py`
- Delete: `automation/viking-forge/scripts/reconcile.py`
- Delete: `automation/viking-forge/tests/test_callbacks.py`
- Delete: `.github/workflows/agent-triage.yml`
- Delete: `.github/workflows/agent-fix.yml`
- Delete: `.github/workflows/agent-reconcile.yml`
- Modify: `automation/viking-forge/tests/test_assets.py`

**Interfaces:**
- Consumes: `LocalWorker.run_once()` in one daemon thread
- Removes: `/callbacks/workflow`, `/callbacks/reconcile`, `CALLBACK_SECRET`, Workflow URL

- [ ] **Step 1: Write failing asset/config/runtime tests**

Require no `agent-*.yml`, no callback routes or config, one local Worker thread, local repository/Codex/run paths, and dashboard links only to Issue/PR.

- [ ] **Step 2: Verify RED and implement cleanup**

Run: `uv run pytest -q tests/test_assets.py tests/test_app.py`

Start Worker and notification dispatch from the same process, with test startup disabled through the existing dependency seam.

- [ ] **Step 3: Run the complete suite and commit**

Run: `uv run pytest -q`

Commit: `refactor:remove-github-actions-execution`

### Task 8: 本地部署文档和实际验证

**Files:**
- Modify: `automation/viking-forge/deploy/.env.example`
- Create: `automation/viking-forge/deploy/viking-forge.service`
- Delete: `automation/viking-forge/deploy/Dockerfile`
- Delete: `automation/viking-forge/deploy/docker-compose.yml`
- Delete: `automation/viking-forge/deploy/Caddyfile`
- Delete: `automation/viking-forge/.dockerignore`
- Rewrite: `automation/viking-forge/README.md`
- Rewrite: `automation/viking-forge/docs/design.md`
- Rewrite: `automation/viking-forge/docs/deployment.md`
- Replace: `automation/viking-forge/docs/implementation-plan.md`

**Interfaces:**
- Documents: `openeuler00` / `wlf1`, repository path, `CODEX_HOME`, local service start, HTTPS webhook forwarding, GitHub App, Feishu and recovery

- [ ] **Step 1: Update Chinese documentation and deployment assets**

Document `codex login status`, local-only secrets, one-process service, backup, logs, emergency stop, and the exact final effect. Remove all Actions Secret/Variable and GitHub-hosted Codex instructions.

- [ ] **Step 2: Remove repository-side obsolete configuration**

Delete the five VikingForge Actions Secrets, three Variables, and disable/remove the obsolete workflow runs. Update the repository webhook event list to only `issues` and `pull_request`.

- [ ] **Step 3: Verify locally**

Run:

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
codex login status
```

- [ ] **Step 4: Deploy and run an end-to-end Fork test**

Start the service under `wlf1`, create a bounded documentation Issue, choose “继续分析”, verify a local triage run and comment, add `agent:ready`, verify a distinct local fix run and draft PR, then confirm the panel and notification Outbox.

- [ ] **Step 5: Commit and create the final PR**

Commit: `docs:document-local-vikingforge-deployment`

Create a non-draft PR against `wlff123/OpenViking:main`, wait for relevant checks, merge into the Fork, and leave the local service running on the documented URL.


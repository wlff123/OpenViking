# VikingForge 本地执行架构

## 目标

VikingForge 在维护者自己的机器上完成 Issue 分诊、代码修复、验证和 PR 发布。GitHub 只提供 Issue、标签、分支、PR 和普通 CI，不保存 OpenAI、GitHub App 或飞书密钥，也不运行 Codex。

## 选型

采用单进程控制面和一个本地 Worker：FastAPI 提供 Webhook 与网页面板，SQLite 保存 Issue、运行队列和通知 Outbox，后台线程串行领取任务。每次任务都创建独立 Git worktree，并启动全新的 `codex exec --ephemeral` 进程。

未采用以下方案：

- GitHub Actions 执行 Codex：需要把 OpenAI 密钥放到 GitHub，且执行位置不符合本地部署目标。
- Redis、Celery 或独立 Worker 服务：当前只有一个仓库和低并发 Issue，额外基础设施没有收益。

## 组件边界

- `app.py`：Webhook、Basic Auth 面板和人工决定；不执行 Git 或 Codex。
- `store.py`：SQLite Issue 状态、运行队列、事件和飞书 Outbox。
- `worker.py`：领取一个任务，编排分诊或修复生命周期。
- `workspace.py`：从本地基准仓库创建和清理独立 worktree。
- `codex.py`：以最小环境变量调用本地 Codex CLI，解析 Schema 约束输出。
- `github.py`：使用本地 GitHub App 私钥签发短期 Token，读写 Issue、标签、评论、分支和草稿 PR。
- `validation.py`：执行补丁策略和仓库校验命令。
- `notifications.py`：从 Outbox 发送飞书通知。

## 数据流

1. GitHub Issue Webhook 写入 `awaiting_decision`，不启动 Codex。
2. 维护者在面板选择“忽略”或“继续分析”。继续分析会添加 `agent:analyze`，由签名 Webhook 将一个 `triage` 任务写入本地队列。
3. Worker 创建只读分诊 worktree，写入 Issue 上下文，执行独立的 `codex exec --ephemeral --sandbox read-only`。
4. 分诊成功后，本地发布器更新固定 Issue 评论和标签，将状态改为 `waiting_approval`。
5. 维护者在 GitHub 添加 `agent:ready`。VikingForge 校验操作者具有写权限、Issue 修订未变化且分诊允许自动修复，然后创建 `fix` 任务。
6. Worker 创建新的修复 worktree，执行 `codex exec --ephemeral --sandbox workspace-write`。Codex 只修改工作区，不持有 GitHub App、Webhook 或飞书密钥。
7. Worker 运行补丁门禁和确定性校验。通过后，发布器使用短期 GitHub App Token 推送 `agent/issue-<编号>-<运行ID>`，创建草稿 PR 并发送飞书通知。
8. PR 合并或关闭事件更新面板状态。系统不自动转为 Ready、不自动批准、不自动合并。

## 隔离与安全

- 不向 GitHub Actions 写入任何 VikingForge Secret 或 Variable。
- Codex CLI 使用部署用户本地 `CODEX_HOME` 中的登录状态；认证文件不得进入仓库或日志。
- Codex 子进程使用环境变量白名单，不继承 GitHub App 私钥、安装 Token、Webhook Secret、飞书 Webhook 或面板密码。
- 每个运行使用独立 worktree 和独立 Codex 会话；任务完成后清理 worktree。
- 分诊使用只读沙箱。修复只能写 worktree，并继续限制最多 5 个文件和 500 行，禁止工作流、依赖、认证及安全策略修改。
- GitHub Token 仅在发布阶段短时存在，Codex 和测试进程均不能读取。

## 状态与失败

运行状态为 `queued`、`running`、`succeeded` 或 `failed`。Issue 状态继续使用 `awaiting_decision`、`ignored`、`triaging`、`waiting_approval`、`claimed`、`coding`、`validating`、`publishing`、`pr_open`、`blocked`、`merged` 和 `closed`。

Codex、Git、门禁或测试失败时，Worker 记录截断后的错误，移除生命周期标签，添加 `agent:blocked`，更新面板并写入飞书 Outbox。进程重启后，超时的 `running` 任务恢复为 `queued`；同一 Issue 同时最多有一个活动任务。

## 部署

VikingForge 运行在持有本地仓库和 Codex 登录状态的受信任 Linux 用户下。当前环境使用专用 `viking-forge-agent-runtime` sidecar 中的 `wlf1` 用户、`/data/wlf1/viking-forge-workspace` 仓库和 `/home/wlf1/.codex` 登录目录。sidecar 使用 `seccomp=unconfined` 允许 Codex 的 `bwrap` 沙箱创建用户命名空间，但不使用 `--privileged`，Codex 仍按分诊只读、修复仅工作区可写的模式运行。服务只需一个 Python 进程；公网入口仅转发 GitHub Webhook，面板只暴露在 PC 本地端口。

## 删除项

- 删除 `.github/workflows/agent-triage.yml`、`agent-fix.yml` 和 `agent-reconcile.yml`。
- 删除 Workflow 回调端点、回调签名脚本和 GitHub Actions 专用对账脚本。
- 删除 `CALLBACK_SECRET`、Actions Secret/Variable 配置和 Workflow URL 展示。
- 保留 OpenViking 原有 CI 工作流；它们只验证创建后的 PR。

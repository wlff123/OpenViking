# VikingForge 本地执行实施结果

## 已完成

- 将 Codex 分诊和修复从 GitHub Actions 迁移到维护者本地机器。
- 新增 SQLite 持久化运行队列，支持进程重启恢复和单 Issue 活动任务约束。
- 每次运行创建独立 detached Git worktree，并启动独立 `codex exec --ephemeral`。
- Codex 和验证进程使用环境白名单，不继承服务密钥。
- 新增本地补丁门禁、仓库验证和 GitHub Data API 发布器。
- 新增维护者权限检查、Issue 修订检查和修复候选门禁。
- 新增单 Worker 生命周期、失败阻塞、飞书 Outbox 和 PR 状态回写。
- 面板显示 Issue 状态、本地任务状态、分诊摘要、错误和 PR 链接。
- 删除三个 Agent Actions、Workflow 回调、对账脚本、回调密钥和嵌套 Docker 部署。
- 提供本地环境样例、systemd 服务单元和中文部署文档。

## 验收标准

1. 新 Issue 只进入面板，不自动运行 Codex。
2. 面板“继续分析”创建一个本地只读分诊运行。
3. 只有维护者添加 `agent:ready` 才创建新的本地修复运行。
4. Codex 和测试无法读取 GitHub App、Webhook、飞书和面板密钥。
5. 门禁或测试失败时 Issue 进入 `blocked` 并保留错误。
6. 成功时只创建草稿 PR，飞书通知维护者人工审核。
7. GitHub 仓库不保存 VikingForge Actions Secret 或 Variable。

详细设计见 `local-execution-design.md`，逐步实现记录见 `local-execution-implementation-plan.md`。

# VikingForge

VikingForge 是 OpenViking 的人工把关 Issue 自动处理服务。GitHub 负责 Issue、标签、分支和 PR；维护者本地机器负责 Codex 分诊、代码修改、验证和发布。GitHub Actions 不运行 Codex，也不保存 OpenAI API Key、GitHub App 私钥或飞书 Webhook。

## 最终效果

1. 新 Issue 出现在网页面板，初始状态为 `awaiting_decision`，不会自动调用 Codex。
2. 维护者在面板选择“忽略”或“继续分析”。
3. “继续分析”会在本机启动一个只读 Codex 会话，结果写入 Issue 评论。
4. 维护者确认分诊结论后，在 GitHub 添加 `agent:ready`。
5. 本机为该 Issue 创建新的 worktree 和新的 Codex 会话，修改代码并运行门禁与测试。
6. 验证通过后，GitHub App 创建分支和草稿 PR，飞书通知维护者审核。
7. 系统不会自动批准、转为 Ready、合并或发布 PR。

不同 Issue 使用不同运行记录、worktree 和 Codex 会话；单个 Worker 串行执行，避免任务互相污染。

## 目录

- `src/viking_forge/`：Webhook、面板、SQLite 队列、Worker、GitHub 发布和飞书通知。
- `prompts/`、`schemas/`：Codex 分诊与修复提示词及结构化输出约束。
- `scripts/labels.py`：初始化 GitHub 标签。
- `deploy/`：本地环境变量样例和 systemd 服务单元。
- `docs/design.md`：已落地架构与安全边界。
- `docs/deployment.md`：部署、GitHub 配置、使用和恢复步骤。

## 验证

```bash
cd automation/viking-forge
uv sync --extra test
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
codex login status
```

部署和实际使用参见 [部署文档](docs/deployment.md)。

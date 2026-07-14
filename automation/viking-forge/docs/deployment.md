# VikingForge 部署与使用

## 1. 最终运行效果

1. 社区成员创建 OpenViking Issue，VikingForge Webhook 将其显示为“待决定”，不会调用 Codex。
2. 维护者登录面板，选择“忽略”或“继续分析”。前者添加 `agent:ignored`，后者添加 `agent:analyze`。
3. `agent:analyze` 触发只读 Codex 分诊。分诊结果写回带固定标记的 Issue 评论，并添加 `agent:triaged`；信息不足时添加 `needs:info`，不进入修复。
4. 维护者审核分诊结论，在 GitHub Issue 上添加 `agent:ready`。只有具有仓库写权限的操作者才能通过授权检查。
5. Codex 在隔离任务中修改代码，策略脚本限制文件和行数；另一个全新检出任务应用补丁并运行检查。
6. 校验通过后，GitHub App 推送 `agent/issue-<编号>-<run_id>` 分支并创建草稿 PR，添加 `agent:generated`。系统不会自动转为 Ready、合并或发布。
7. 草稿 PR、阻塞和合并状态通过飞书机器人通知维护者；面板展示 Issue、Workflow 和 PR 链接。
8. 每小时对账 GitHub 的 Issue/PR 标签状态，修复丢失 Webhook 或短时故障造成的面板状态偏差。

## 2. 前置条件

- 一台可由 GitHub 访问 HTTPS 443 端口的 Linux 主机和域名。
- Docker Engine 与 Docker Compose v2。
- OpenViking 仓库管理员权限、OpenAI API Key、飞书群自定义机器人 Webhook。
- GitHub Actions 允许运行仓库中的三个 `agent-*.yml` 工作流。

## 3. 创建 GitHub App

创建仅安装到 `volcengine/OpenViking` 的 GitHub App：

- Webhook URL：`https://<域名>/webhooks/github`
- Webhook Secret：生成至少 32 字节随机值。
- Repository permissions：Metadata 只读；Contents、Issues、Pull requests 读写；Actions、Checks 只读。
- Subscribe to events：Issues、Pull request、Workflow run。

安装 App 后记录 App ID 和 PEM 私钥。面板使用 App 身份添加 `agent:analyze`，工作流据此区分网页人工决定与外部用户伪造的同名标签。

## 4. 部署服务

```bash
cd automation/viking-forge/deploy
cp .env.example .env
chmod 600 .env
docker compose up -d --build
docker compose ps
curl https://<域名>/healthz
```

编辑 `.env`，替换所有示例值。`GITHUB_APP_PRIVATE_KEY` 保持单行，并用字面量 `\n` 表示换行。只运行一个 Uvicorn worker；SQLite 和通知租约按单进程部署设计。Caddy 自动申请 TLS 证书，数据库保存在命名卷 `viking-forge-data`。

## 5. 配置仓库

在 GitHub 仓库 Actions Secrets 中设置：

- `OPENAI_API_KEY`
- `VIKING_FORGE_APP_ID`
- `VIKING_FORGE_PRIVATE_KEY`
- `VIKING_FORGE_CALLBACK_URL`，值为 `https://<域名>`
- `VIKING_FORGE_CALLBACK_SECRET`，必须与服务端 `CALLBACK_SECRET` 相同

在 Actions Variables 中设置：

- `VIKING_FORGE_APP_SLUG`：GitHub App 的 slug，不含 `[bot]`
- `VIKING_FORGE_CODEX_MODEL`：经过验证的 Codex 模型名
- `VIKING_FORGE_CODEX_EFFORT`：建议 `medium`

首次执行以下命令创建或更新标签：

```bash
cd automation/viking-forge
gh auth login
python scripts/labels.py --repo volcengine/OpenViking
```

在 GitHub App 页面确认 Webhook 最近投递为 2xx，然后手动运行 `Agent Reconcile` 工作流完成初始同步。

## 6. 日常使用

访问 `https://<域名>/`，输入 `.env` 中的面板用户名和密码。面板只对 `awaiting_decision` 状态显示操作：

- “忽略”：添加 `agent:ignored`，不会运行 Codex。
- “继续分析”：添加 `agent:analyze`，启动一次只读分诊。

分诊完成后到 GitHub 阅读机器人评论。确认值得修复且风险可接受，再添加 `agent:ready`。草稿 PR 只表示自动修复已生成、等待人工审查；维护者需要检查代码、CI 和安全影响，必要时要求修改，最后自行转为 Ready 并合并。

## 7. 运维检查

```bash
docker compose logs -f app
docker compose logs -f caddy
docker compose exec app python -c "import sqlite3; c=sqlite3.connect('/data/viking-forge.sqlite3'); print(c.execute('select bot_state,count(*) from issues group by bot_state').fetchall())"
```

备份 `viking-forge-data` 卷中的 SQLite 数据库。升级前先备份，再执行 `docker compose up -d --build`。若面板状态与 GitHub 不一致，先手动运行 `Agent Reconcile`；不要直接修改数据库。


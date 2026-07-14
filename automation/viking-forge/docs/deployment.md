# VikingForge 部署与使用

## 1. 部署完成后会看到什么

- `http://127.0.0.1:18081/` 是带 Basic Auth 的 Issue 状态面板，只在 `awaiting_decision` 行显示“忽略”和“继续分析”。
- 社区新建 Issue 后，面板出现一行记录，但 Codex 不会启动。
- 点击“继续分析”后，本地出现一个 `triage` 运行，GitHub Issue 收到 VikingForge 分诊评论。
- 维护者在 GitHub 添加 `agent:ready` 后，本地出现另一个 `fix` 运行；它与分诊使用不同 worktree 和 Codex 会话。
- 修复成功后，Fork 中出现 `agent/issue-<编号>-<run_id>` 分支和草稿 PR，面板显示 PR 链接，飞书收到审核通知。
- 最终是否转为 Ready、是否合并，完全由维护者决定。

## 2. 当前环境

已验证的运行位置：

- 专用运行容器：`viking-forge-agent-runtime`
- Linux 用户：`wlf1`
- 仓库：`/data/wlf1/viking-forge-workspace`
- 应用：`/data/wlf1/viking-forge-workspace/automation/viking-forge`
- Codex 登录目录：`/home/wlf1/.codex`
- 服务端口：`18081`

原容器的默认 Docker seccomp 配置会阻止 Codex 沙箱创建用户命名空间，因此应用不直接运行在 `openeuler00`。专用容器只额外使用 `seccomp=unconfined` 允许 Codex 自己的 `bwrap` 沙箱工作；不要把 Codex 改成 `danger-full-access`，也不要给容器增加 `--privileged`。

先确认本地 Codex 登录有效：

```bash
docker exec -u wlf1 viking-forge-agent-runtime bash -lc 'CODEX_HOME=/home/wlf1/.codex codex login status'
```

应显示 `Logged in using ChatGPT`。这里不需要 `OPENAI_API_KEY`。

## 3. GitHub App 和 Webhook

GitHub App 只安装到目标仓库，权限如下：

- Metadata：Read-only
- Contents：Read and write
- Issues：Read and write
- Pull requests：Read and write

记录 App ID、App slug 和 PEM 私钥。PEM 只保存在本地运行目录，权限设为 `600`。

在目标仓库的 Settings -> Webhooks 创建 Webhook：

- Payload URL：公网入口加 `/webhooks/github`
- Content type：`application/json`
- Secret：与本地 `GITHUB_WEBHOOK_SECRET` 相同
- Events：只选 `Issues` 和 `Pull requests`

仓库 Webhook 与 GitHub App Webhook 二选一即可；当前 Fork 使用仓库 Webhook。公网入口可以是固定反向代理或 Tunnel，但必须把请求转发到本地 18081。

GitHub Actions 中不配置任何 VikingForge Secret 或 Variable。若旧版本配置过，应删除：

- Secrets：`OPENAI_API_KEY`、`VIKING_FORGE_APP_ID`、`VIKING_FORGE_PRIVATE_KEY`、`VIKING_FORGE_CALLBACK_URL`、`VIKING_FORGE_CALLBACK_SECRET`
- Variables：`VIKING_FORGE_APP_SLUG`、`VIKING_FORGE_CODEX_MODEL`、`VIKING_FORGE_CODEX_EFFORT`

## 4. 本地配置

```bash
docker exec -u wlf1 viking-forge-agent-runtime bash -lc '
  mkdir -p /data/wlf1/viking-forge-runtime/runs
  chmod 700 /data/wlf1/viking-forge-runtime /data/wlf1/viking-forge-runtime/runs
  cd /data/wlf1/viking-forge-workspace
  uv sync --extra test --extra dev
  cd /data/wlf1/viking-forge-workspace/automation/viking-forge
  uv sync --extra test
'
```

把 `deploy/.env.example` 复制为 `/data/wlf1/viking-forge-runtime/viking-forge.env` 并填写真实值。把 GitHub App PEM 放到：

```text
/data/wlf1/viking-forge-runtime/github-app-private-key.pem
```

两个文件都必须属于 `wlf1` 且权限为 `600`。环境文件中关键路径为：

```dotenv
REPOSITORY=wlff123/OpenViking
REPOSITORY_PATH=/data/wlf1/viking-forge-workspace
VALIDATION_VENV=/data/wlf1/viking-forge-workspace/.venv
DATABASE_PATH=/data/wlf1/viking-forge-runtime/viking-forge.sqlite3
RUNS_DIRECTORY=/data/wlf1/viking-forge-runtime/runs
GIT_REMOTE=fork
BASE_BRANCH=main
CODEX_EXECUTABLE=/usr/local/nvm/versions/node/v25.9.0/bin/codex
GITHUB_APP_PRIVATE_KEY_FILE=/data/wlf1/viking-forge-runtime/github-app-private-key.pem
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/...
```

`FEISHU_WEBHOOK_URL` 使用飞书群自定义机器人的 Webhook，只保存在这个本地环境文件中，不放入 GitHub。暂时留空时，PR 和失败通知仍会写入 SQLite Outbox，但不会发送；补上地址并重启服务后会继续投递待处理通知。

`VALIDATION_VENV` 指向基准仓库预先执行 `uv sync --extra test --extra dev` 得到的环境。修复任务只复用其中的 Ruff、pytest 和依赖，待测源码仍通过 `PYTHONPATH` 指向本次独立 worktree；这样不会为每个 Issue 重装整套依赖。

## 5. 启动

支持 systemd 的 Linux 主机使用 `deploy/viking-forge.service`。调整路径后安装：

```bash
sudo cp deploy/viking-forge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viking-forge
sudo systemctl status viking-forge
```

当前 PC 使用专用 sidecar。首次创建时挂载 `wlf1` 的 HOME 和 `/data`，用 `--init` 回收沙箱子进程，并只把面板端口发布到 PC 回环地址：

```powershell
docker run -d --name viking-forge-agent-runtime `
  --init `
  --security-opt seccomp=unconfined `
  -p 127.0.0.1:18081:18081 `
  -v D:/docker/home-selected/wlf1:/home/wlf1 `
  -v D:/docker:/data `
  openeuler00-sshfix:20260429163136 sleep infinity
```

容器已存在时直接以 `wlf1` 启动应用：

```bash
set -a
source /data/wlf1/viking-forge-runtime/viking-forge.env
set +a
export CODEX_HOME=/home/wlf1/.codex
export PATH=/home/wlf1/.local/bin:/usr/local/nvm/versions/node/v25.9.0/bin:/usr/local/bin:/usr/bin:/bin
cd /data/wlf1/viking-forge-workspace/automation/viking-forge
exec uv run uvicorn viking_forge.main:app --host 0.0.0.0 --port 18081
```

可用 `docker exec -d -u wlf1 viking-forge-agent-runtime bash -lc '<上述命令>'` 让服务在容器后台运行。当前验证实例因为创建 sidecar 时未发布端口，使用 `viking-forge-proxy` Caddy 容器把 PC 的 `127.0.0.1:18081` 转发到 sidecar 的 `18081`；新部署优先直接使用上面的 `-p`。

健康检查：

```bash
curl http://127.0.0.1:18081/healthz
```

公网 Webhook Tunnel 指向 PC 的 18081，并把 GitHub Payload URL 配置成公网地址加 `/webhooks/github`。临时 Tunnel 地址会失效，长期运行应使用固定 HTTPS 域名或固定 Tunnel。

## 6. 初始化标签

使用有仓库管理权限的 GitHub CLI 身份执行一次：

```bash
cd /data/wlf1/viking-forge-workspace/automation/viking-forge
uv run python scripts/labels.py --repo wlff123/OpenViking
```

保留的标签包括 `agent:analyze`、`agent:retriage`、`agent:ready`、`agent:claimed`、`agent:triaged`、`agent:blocked`、`agent:pr-open`、`agent:generated`、`agent:ignored`、`agent:human-only` 和 `needs:info`。

## 7. 日常使用

1. 社区成员创建新 Issue。
2. 维护者打开面板，选择“忽略”或“继续分析”。
3. 分诊完成后，到 GitHub 阅读机器人评论。
4. 只有结论明确、风险可接受时，由有写权限的维护者添加 `agent:ready`。
5. 打开生成的草稿 PR，检查 diff、测试、CI 和安全影响。
6. 人工决定修改、关闭、转为 Ready 或合并。

Issue 编辑本身不会重复分诊。需要重新分析时，由维护者添加 `agent:retriage`。非维护者添加 `agent:ready` 或 `agent:retriage` 不会启动任务。

## 8. 运维与恢复

查看状态：

```bash
sqlite3 /data/wlf1/viking-forge-runtime/viking-forge.sqlite3 \
  'select issue_number,bot_state,active_run_id,last_error from issues order by updated_at desc;'
```

备份时复制 SQLite 主文件及同目录的 `-wal`、`-shm` 文件，或先停止服务再复制主文件。运行日志和结果位于 `RUNS_DIRECTORY/<run_id>/`。

紧急停止：

```bash
sudo systemctl stop viking-forge
```

容器内手工启动时，向 Uvicorn 进程发送 `SIGTERM`。停止服务不会删除队列；尚未领取的 `queued` 任务会保留，重启时遗留的 `running` 任务会标记为 `failed`，对应 Issue 进入 `blocked`，需要维护者确认后重新添加 `agent:retriage` 或 `agent:ready`。若要阻止新任务，同时停掉服务并在 GitHub 暂停 Webhook，不要直接修改 SQLite。

## 9. 验收清单

- `codex login status` 显示 ChatGPT 已登录。
- `/healthz` 返回 `{"status":"ok"}`。
- GitHub Webhook 最近一次投递为 2xx。
- 新 Issue 出现在面板但没有自动运行。
- 点击“继续分析”后生成分诊评论。
- 维护者添加 `agent:ready` 后生成不同 run ID 的修复任务。
- 修复只创建草稿 PR，不自动合并。
- GitHub Actions Secrets 和 Variables 中没有 VikingForge 配置。

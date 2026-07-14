# VikingForge

VikingForge 是 OpenViking 的人工把关 Issue 自动处理系统。它接收 GitHub Issue Webhook，在网页面板列出待处理项；维护者选择“忽略”或“继续分析”后，GitHub Actions 才会调用 Codex 分诊。维护者随后在 GitHub 添加 `agent:ready`，Codex 才会生成修复、执行策略校验并创建草稿 PR。系统通过飞书通知维护者审核，不自动合并。

## 目录

- `src/viking_forge/`：面板、Webhook、状态存储、回调和飞书通知。
- `scripts/`：Actions 使用的上下文、策略、验证、回调和对账脚本。
- `prompts/`、`schemas/`：Codex 提示词与结构化输出约束。
- `deploy/`：Docker Compose、Caddy 和环境变量样例。
- `docs/design.md`：系统设计和状态流转。
- `docs/deployment.md`：完整部署及 GitHub 配置步骤。
- `.github/workflows/agent-*.yml`：仓库级触发入口，是唯一放在本目录之外的文件。

## 本地测试

```bash
cd automation/viking-forge
uv sync --extra test
uv run pytest
```

生产部署参见 [docs/deployment.md](docs/deployment.md)。


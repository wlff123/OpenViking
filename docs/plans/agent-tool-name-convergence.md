# OpenViking 提供 Agent 调用接口&能力归一化

这份文档从现有插件真实暴露的工具和 hook 出发，整理 OpenViking 提供给 Agent 的归一接口能力，判断哪些能力可以在不改变语义的前提下复用 OpenViking 已有接口，哪些需要未来下沉为新的 OV 通用接口，哪些应继续留在插件内。

判断标准：只有在不改变原功能、默认 scope、参数语义、返回语义和 lifecycle 行为时，才标记为“可以直接收敛”。如果 OV 没有对应接口，但多个插件都需要同一能力，再考虑补 OV 通用接口；单宿主专用能力继续留在插件内。

注意：“当前 OpenViking 底层接口”表示底层 REST / MCP / CLI 能力是否已经存在；“建议收敛目标工具名 / 能力名”表示未来如果统一 Agent 可见工具名时的目标语义名，不表示该 `viking_xxx` 名称已经是 OV server 当前接口。很多插件已经调用了 OV 底层接口，但仍保留宿主侧默认 scope、参数名、返回格式或 lifecycle 行为，这类只能算“底层已复用”，不能算“工具名可直接收敛”。

本次盘点覆盖：

- 本仓插件：OpenClaw、Claude Code、Codex MCP、opencode-memory-plugin、opencode skill plugin。
- 本仓外插件：Hermes 官方仓内置 OpenViking memory provider，本仓没有实现代码，本 PR 不改。
- 通用 MCP 客户端：Cursor / Trae / Manus / Claude Desktop / ChatGPT 等直接消费 OV server `/mcp`，不是单独插件，本 PR 不改 `/mcp` 工具名。

## OpenViking 归一接口

| Viking 接口 / 能力名 | 提供能力 |
|---|---|
| `viking_search` | 根据 query 和可选 target_uri、limit、score_threshold 检索 memories、resources、skills，返回 URI、摘要和相关性信息。 |
| `viking_remember` | 写入文本、消息或会话内容，触发 session commit / memory extraction，形成长期记忆。 |
| `viking_forget` | 按明确的 `viking://` URI 删除 OpenViking 中的记忆或资源。 |
| `viking_import` | 导入外部资源、文件、目录或 skill，并进入资源 / skill 的索引与处理流程。 |
| `viking_session_archive_search` | 在已归档的 session 原文中按关键词或模式定位历史消息片段。 |
| `viking_session_archive_read` | 根据 session_id 和 archive_id 读取指定归档中的原始消息内容。 |
| `viking_health` | 检查 OpenViking server 是否可达、可用，并返回基础健康状态。 |
| `viking_read` | 根据 `viking://` URI 读取 abstract、overview 或 full content。 |
| `viking_browse` | 根据 `viking://` URI 查看目录列表、树结构或单个节点元信息，发现可检索 / 可读取 URI。 |

## 1. `viking_search`

接口功能：面向 Agent / 插件提供统一语义检索能力，根据 query 和可选 target_uri、limit、score_threshold 检索 memories、resources、skills，并返回可继续读取的 URI、摘要和相关性信息。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `memory_recall` | 有：REST `/api/v1/search/find`、MCP `search`、CLI `ov find` | 否 | OV 已有基础搜索接口，但搜索接口入参需要外部传入(query, target_uri, limit, score_threshold, filter)，需要插件根据业务场景自定义。 |
| OpenClaw | `ov_search` | 有：REST `/api/v1/search/find`、MCP `search`、CLI `ov find` | 否 | OV 已有基础搜索，但该工具自身和当前基础搜索不等价：默认 scope 是 `viking://resources` + `viking://agent/skills`，默认不搜 memories；参数名是 `uri` 而不是 `target_uri`；不设置默认 score threshold；多 scope 查询支持部分成功返回；返回文案和 details 结构也不同。 |
| Claude Code hooks | `UserPromptSubmit` 自动召回，无模型可见工具名 | 有：REST `/api/v1/search/find` + `/api/v1/content/read` | 已调用 OV，但不改 | hook 对应统一搜索/召回能力，但负责多 scope、ranking、token budget、注入格式，这些是 Claude Code lifecycle 语义；底层检索已直接调用 OV。 |
| Codex MCP | `openviking_recall` | 有：REST `/api/v1/search/find`、MCP `search`、CLI `ov find` | 否 | OV 已有基础搜索，但该工具默认只搜 `viking://user/memories`，并按 memory 结果格式输出。 |
| opencode-memory-plugin | `memsearch` | 有：REST `/api/v1/search/find` / `/api/v1/search/search`、MCP `search`、CLI `ov find` / `ov search` | 否 | OV 已有基础搜索和 session-aware search，但该工具有 `auto` / `fast` / `deep` 模式，会按模式选择接口并自动注入当前 OpenCode session。 |

## 2. `viking_remember`

接口功能：面向 Agent / 插件提供统一记忆写入能力，把文本、消息或会话内容写入 OpenViking session，并触发 commit / memory extraction 形成长期记忆。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `memory_store` | 有：REST `/api/v1/sessions/*`、MCP `store` | 否 | OV 已有 session 写入与 commit，但该工具会写 session message、commit，并等待记忆提取完成，和异步 store 不等价。 |
| Claude Code hooks | `Stop` / `PreCompact` / `SessionEnd` / `SubagentStop` 自动捕获与 commit，无模型可见工具名 | 有：REST `/api/v1/sessions/*` | 已调用 OV，但不改 | hook 对应统一记忆写入能力，但负责 transcript 解析、增量状态、subagent 隔离和异步写，这些是 Claude Code lifecycle 语义；底层 session 写入和 commit 已直接调用 OV。 |
| Codex MCP | `openviking_store` | 有：REST `/api/v1/sessions/*`、MCP `store` | 否 | OV 已有 session 写入与 commit，但该工具会同步等待记忆提取完成。 |
| opencode-memory-plugin | `memcommit` | 有：REST `/api/v1/sessions/{id}/messages` + `/api/v1/sessions/{id}/commit` | 否 | OV 已有 session 写入与 commit，但该工具绑定当前 OpenCode session，会先 flush pending messages，并等待或跟踪记忆提取。 |

## 3. `viking_forget`

接口功能：面向 Agent / 插件提供统一删除能力，按明确的 `viking://` URI 删除 OpenViking 中的记忆或资源；按 query 搜索候选属于宿主侧增强语义。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `memory_forget` | 有：REST `DELETE /api/v1/fs`、MCP `forget`、CLI `ov rm` | 否 | OV 已有 URI 删除，但该工具还支持按 query 搜索候选并删除唯一高置信 memory。 |
| Codex MCP | `viking_forget`（由 `openviking_forget` 收敛） | 有：REST `DELETE /api/v1/fs`、MCP `forget`、CLI `ov rm` | 是 | 当前实现按 exact memory URI 删除，保留 memory-only guard 后调用 OV 删除接口。 |

## 4. `viking_import`

接口功能：面向 Agent / 插件提供统一导入能力，把外部资源、文件、目录或 skill 导入 OpenViking，并进入资源 / skill 的索引与处理流程。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `ov_import` | 部分有：resource 有 REST `/api/v1/resources`、MCP `add_resource`、CLI `ov add-resource`；skill 有 REST `/api/v1/skills`、CLI `ov add-skill` | 否 | `viking_import` 更符合该工具同时导入 resource / skill 的目标能力；不能只改成 `viking_add_resource`。 |

## 5. `viking_session_archive_search`

接口功能：面向 Agent / 插件提供 session archive 检索能力，在已归档的会话原文中按关键词或模式定位历史消息片段。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `ov_archive_search` | 部分有：REST `/api/v1/search/grep`、CLI `ov grep` 可检索 session history URI | 否 | 该能力实际搜索 session history archive，目标名应带 session archive；OV 目前只有通用 grep，没有专用 Agent/MCP 工具。 |

## 6. `viking_session_archive_read`

接口功能：面向 Agent / 插件提供 session archive 读取能力，根据 session_id 和 archive_id 读取指定归档中的原始消息内容。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| OpenClaw | `ov_archive_expand` | 部分有：REST `/api/v1/sessions/{id}/archives/{archive_id}`、CLI `ov session get-session-archive` | 否 | 该能力实际读取单个 session archive 原文，`read` 比 `expand` 更贴近 OV 读取语义；仍绑定当前 OpenClaw session lifecycle 和返回格式。 |

## 7. `viking_health`

接口功能：面向 Agent / 插件提供统一健康检查能力，确认 OpenViking server 是否可达、可用，并返回基础健康状态。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| Codex MCP | `viking_health`（由 `openviking_health` 收敛） | 有：REST `/health`、MCP `health`、CLI `ov health` | 是 | 当前实现调用 `/health` 检查 server reachability，健康检查语义一致。 |

## 8. `viking_read`

接口功能：面向 Agent / 插件提供统一内容读取能力，根据 `viking://` URI 读取 abstract、overview 或 full content，并为目录 / 文件选择合适读取层级。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| opencode-memory-plugin | `memread` | 有：REST `/api/v1/content/{abstract,overview,read}` + `/api/v1/fs/stat`、MCP `read`、CLI `ov read/abstract/overview` | 否 | OV 已有分层读取接口，但该工具支持 `auto` 层级，会先 stat 判断目录或文件后选择 `overview` / `read`。 |

## 9. `viking_browse`

接口功能：面向 Agent / 插件提供统一浏览能力，根据 `viking://` URI 查看目录列表、树结构或单个节点元信息，帮助发现可检索 / 可读取的 URI。

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| opencode-memory-plugin | `membrowse` | 有：REST `/api/v1/fs/ls` / `/api/v1/fs/tree` / `/api/v1/fs/stat`、MCP `list`、CLI `ov ls/tree/stat` | 否 | OV 已有 browse 底层接口，但该工具把 `list` / `tree` / `stat` / `simple` 视图合成一个工具。 |

## 10. 保持 OV server `/mcp` 工具名

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| Claude Code MCP | `search` / `read` / `list` / `store` / `add_resource` / `grep` / `glob` / `forget` / `health` | 有：`/mcp` 已提供 | 已下沉，不在本 PR 改名 | Claude Code 插件的 `.mcp.json` 只是指向 OV server `/mcp`，工具语义已经在 OV server 内；改名会影响所有 MCP 客户端，不是插件局部收敛。 |

## 11. 保持 OV CLI 能力名

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| opencode skill plugin | `ov search` / `ov grep` / `ov glob` / `ov read` / `ov abstract` / `ov overview` / `ov ls` / `ov tree` / `ov add-resource` / `ov rm` / `ov health` | 有：OV CLI 已提供 | 已下沉，不改 | 该插件不是注册 native tools，而是安装 skill，指导模型通过 shell 调 OV CLI；已经直接复用 OV 能力。 |

## 12. 保持 Hermes memory provider 能力名

| 插件 / 接入 | 当前暴露工具名 / 接口 | 当前 OpenViking 底层接口 | 能否直接收敛 | 结论 / 原因 |
|---|---|---|---|---|
| Hermes memory provider | 外部 Hermes 官方仓 `openviking` provider | 本仓无代码，需在 Hermes 仓单独盘点 | 不在本 PR 改 | Hermes 插件不在 OV 仓；本 PR 只能记录范围，不能在本仓做工具名或接口收敛。 |

## 可以直接改的候选

- `openviking_forget` -> `viking_forget`
- `openviking_health` -> `viking_health`

本 PR 只落这两个 Codex 插件对外改名，不引入新的 ToolCatalog / agent tools 抽象，不迁移 OpenClaw、Claude Code、opencode、Hermes 的既有工具名和执行语义。

## 后续下沉原则

1. 先看插件是否能无语义变化调用 OV 已有接口；能就直接收敛。
2. OV 没有接口，但多个插件都重复实现同一能力，再补一个具体 OV 通用接口。
3. 只有单个宿主需要，或依赖宿主 lifecycle、默认 scope、返回格式的能力，继续留在插件里。

# PyCoder API 参考文档

> 版本: 1.0 | 更新时间: 2026-07-16 | 基础路径: `http://localhost:8420`

---

## 1. 概述

PyCoder 是一个基于 FastAPI 的 Python AI 编程助手后端服务，提供 REST API 和 WebSocket 两种通信方式。API 涵盖文件管理、代码执行、Git 操作、AI 聊天、代码重构、可视化、配置管理、团队协作、自进化等核心功能。

### 1.1 认证方式

所有 API 请求（除 `/api/health`、`/docs`、`/openapi.json`、`/ws/*` 外）需要通过 `X-API-Key` 请求头进行认证：

```
X-API-Key: <your-api-key>
```

认证支持三种模式：
- **PYCODER_API_KEY=disabled**：关闭认证（仅开发环境）
- **PYCODER_API_KEY=\<key\>**：使用指定密钥强制认证
- **未设置**：自动生成临时密钥，存储于 `~/.pycoder/.api_key`

WebSocket 连接通过查询参数 `?api_key=` 或请求头 `X-API-Key` 进行认证。

### 1.2 速率限制

对敏感端点（`/api/code/`、`/api/chat`、`/api/skills`）实施速率限制：每 IP 每分钟最多 60 次请求，超出返回 HTTP 429。

### 1.3 CORS 配置

允许的来源域名：
- `http://localhost:8420`
- `http://127.0.0.1:8420`
- `http://localhost:8423`
- `http://127.0.0.1:8423`
- `http://localhost:5173`
- `http://127.0.0.1:5173`

允许的请求方法：`GET`、`POST`、`PUT`、`DELETE`、`OPTIONS`

### 1.4 通用响应格式

成功响应：
```json
{ "success": true, "data": { ... } }
```

错误响应：
```json
{ "success": false, "error": "错误描述" }
```

---

## 2. REST API 端点

### 2.1 系统与健康检查

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/health` | 系统健康检查，返回版本、Python 版本、运行时间、数据库状态 | 无 |
| GET | `/api/models` | 列出所有可用的 AI 模型 | 无 |
| GET | `/api/models/recommended` | 获取推荐模型列表 | 无 |
| GET | `/api/models/suggest` | 根据任务类型推荐模型 | `task_type` (query): general/coding/analysis |
| GET | `/api/env` | 获取当前环境信息（Python 版本、虚拟环境、包管理器、框架等） | 无 |
| GET | `/api/v2/status` | V2 引擎运行状态（能力数量、信任级别、意识模式等） | 无 |
| GET | `/api/v2/health` | V2 系统健康检查（引擎、进化、监控状态） | 无 |
| GET | `/api/v2/stats` | V2 引擎完整统计 | 无 |

### 2.2 文件管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/files/list` | 列出目录内容（含文件/文件夹及图标类型） | `path` (query): 目录路径，默认 "." |
| GET | `/api/files/read` | 读取文件内容（返回 content + language） | `path` (query): 文件路径 |
| POST | `/api/files/write` | 写入文件（覆盖或新建） | `path` (body): 文件路径, `content` (body): 文件内容 |
| POST | `/api/files/workspace/switch` | 切换工作区根目录 | `path` (body): 新工作区路径 |
| GET | `/api/files/workspace/current` | 获取当前工作区路径 | 无 |
| GET | `/api/files/workspace/recent` | 获取最近打开的项目列表 | 无 |
| GET | `/api/files/workspace/restore` | 重启时自动恢复上次工作区 | 无 |

### 2.3 代码搜索

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/search/query` | 全文代码搜索（支持正则/大小写/全词匹配） | `query` (body): 搜索关键词, `limit` (body): 结果数, `file_type` (body): 文件类型过滤, `regex` (body): 是否正则, `case_sensitive` (body): 大小写敏感, `whole_word` (body): 全词匹配 |
| GET | `/api/search` | 全文搜索（GET 简易版） | `query` (query): 搜索关键词, `limit` (query): 结果数, `file_type` (query): 文件类型过滤 |
| GET | `/api/search/files` | 按文件名 glob 模式搜索 | `pattern` (query): 文件名模式, 如 `*.py`, `limit` (query): 结果数 |

### 2.4 代码执行

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/code/exec` | 在安全沙箱中执行 Python 代码 | `code` (body): Python 代码, `timeout` (body): 超时秒数(默认30s), `long_running` (body): 长时运行模式(最长600s) |
| POST | `/api/code/exec-multilang` | 执行多语言代码（Java/Go/Rust/C/C++/JS/TS/Bash） | `language` (body): 目标语言, `code` (body): 源代码, `timeout` (body): 超时秒数 |
| GET | `/api/code/languages` | 列出所有支持的语言及可用状态 | 无 |
| GET | `/api/code/exec/config` | 获取当前沙箱配置 | 无 |
| POST | `/api/code/exec/config` | 更新沙箱配置（运行时生效） | `default_timeout`, `max_timeout`, `max_output_length`, `memory_limit_mb`, `allow_network`, `allow_multithreading` |
| POST | `/api/code/install` | 安装 Python 依赖包 | `packages` (body): 包名列表，支持版本指定 |
| GET | `/api/code/capabilities` | 获取沙箱能力信息 | 无 |
| POST | `/api/code/run` | 在沙箱中执行 Python 代码（复用 code_exec 子进程隔离） | `code` (body), `timeout` (body) |
| POST | `/api/code/debug` | 调试模式执行代码（返回详细 traceback） | `code` (body), `timeout` (body) |
| POST | `/api/code/repl/clear` | 清除 REPL 环境 | 无 |
| GET | `/api/code/repl/globals` | 获取 REPL 全局变量 | 无 |
| GET | `/api/code/repl/locals` | 获取 REPL 局部变量 | 无 |
| GET | `/api/code/history` | 获取代码执行历史 | 无 |

### 2.5 代码差异

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/diff` | 生成两段文本的 unified diff | `original` (body): 原始文本, `modified` (body): 修改后文本, `context_lines` (body): 上下文行数, `filename` (body): 文件名 |
| POST | `/api/diff/file` | 生成文件与新内容/两文件之间的 diff | `source_path` (body), `target_path` (body), `content` (body), `context_lines` (body) |
| GET | `/api/diff/recent` | 列出最近的 diff 记录 | `limit` (query): 数量 |
| GET | `/api/diff/hunks` | 将 unified diff 解析为 hunk 列表 | `diff_text` (query): diff 文本 |
| POST | `/api/diff/hunk/invert` | 从 hunk 差异行中提取原始代码 | `hunk_lines` (body), `original_context` (body) |
| POST | `/api/diff/hunk/apply` | 将单个 hunk 的修改应用到文件 | `file_path` (body), `hunk_text` (body), `action` (body): accept/reject |
| GET | `/api/diff-list/list` | 列出 Git 文件差异列表 | `staged` (query): 是否只看暂存, `path` (query): 仓库路径 |

### 2.6 Git 操作

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/git/init` | 检查工作区是否是 Git 仓库 | 无 |
| POST | `/api/git/init` | 初始化新 Git 仓库 | `path` (body): 路径 |
| GET | `/api/git/status` | 获取 Git 状态（staged/unstaged/untracked） | `path` (query): 仓库路径 |
| GET | `/api/git/log` | 获取最近提交记录 | `limit` (query): 数量, `path` (query): 仓库路径 |
| POST | `/api/git/commit` | 自动 Git commit（add + commit） | `files` (body): 文件列表, `message` (body): 提交信息, `author` (body): 作者 |
| POST | `/api/git/commit/generate-message` | AI 生成 conventional commit message | 无 |
| GET | `/api/git/branches` | 列出所有分支 | `path` (query): 仓库路径 |
| POST | `/api/git/branch/create` | 创建新分支 | `name` (body): 分支名 |
| POST | `/api/git/branch/switch` | 切换分支 | `name` (body): 分支名 |
| POST | `/api/git/branch/delete` | 删除分支 | `name` (body): 分支名, `force` (body): 是否强制 |
| POST | `/api/git/branch/merge` | 合并分支 | `source_branch` (body): 源分支 |
| POST | `/api/git/push` | 推送到远程 | `remote` (body): 远程名, `branch` (body): 分支名 |
| POST | `/api/git/pull` | 从远程拉取 | `remote` (body): 远程名, `branch` (body): 分支名 |
| POST | `/api/git/fetch` | 从远程拉取但不合并 | `remote` (body): 远程名 |
| POST | `/api/git/stash` | 暂存操作 | `action` (body): push/pop/list/drop, `message` (body): 暂存信息 |
| POST | `/api/git/stash/detail` | 查看特定 stash 的 diff | `index` (body): stash 索引 |
| POST | `/api/git/stash/apply` | 应用 stash 但不删除 | `index` (body): stash 索引 |
| POST | `/api/git/stage` | 暂存指定文件 | `files` (body): 文件列表 |
| POST | `/api/git/unstage` | 取消暂存 | `files` (body): 文件列表, `all` (body): 取消全部 |
| POST | `/api/git/discard` | 放弃文件变更 | `files` (body): 文件列表 |
| GET | `/api/git/diff` | 获取文件或整个工作区的 diff | `file` (query): 文件路径, `staged` (query): 是否暂存 |
| GET | `/api/git/blame` | 逐行溯源 | `file` (query): 文件路径 |
| GET | `/api/git/file-history` | 查看单个文件提交历史 | `file` (query), `limit` (query): 数量 |
| GET | `/api/git/compare` | 对比两个提交/分支的 diff | `base` (query), `head` (query) |
| GET | `/api/git/tags` | 列出所有标签 | 无 |
| POST | `/api/git/tag/create` | 创建标签 | `name` (body), `message` (body), `commit` (body) |
| POST | `/api/git/tag/delete` | 删除标签 | `name` (body) |
| POST | `/api/git/reset` | 重置 HEAD | `mode` (body): soft/mixed/hard, `commit` (body): 目标提交 |
| POST | `/api/git/revert` | 撤销提交 | `commit` (body): 提交哈希 |
| POST | `/api/git/cherry-pick` | 摘取提交 | `commit` (body): 提交哈希 |
| POST | `/api/git/rebase` | 变基 | `branch` (body): 目标分支 |
| GET | `/api/git/remotes` | 列出所有远程仓库 | 无 |
| POST | `/api/git/remote/add` | 添加远程 | `name` (body), `url` (body) |
| POST | `/api/git/remote/remove` | 删除远程 | `name` (body) |
| GET | `/api/git/conflicts` | 检测并列出合并冲突文件 | 无 |
| POST | `/api/git/resolve-conflict` | 解决合并冲突 | `file` (body), `resolution` (body): ours/theirs |
| POST | `/api/git/ignore` | 添加到 .gitignore | `pattern` (body): 忽略模式 |

### 2.7 代码可视化

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/visualize/structure` | 生成项目结构树 | `path` (query): 项目路径, `max_depth` (query): 最大深度(1-5) |
| GET | `/api/visualize/imports` | 分析项目导入依赖关系 | `path` (query): 项目路径 |
| POST | `/api/visualize/calls` | 分析函数调用关系 | `path` (query): 文件路径 |

### 2.8 代码重构

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/refactor/rename` | 批量重命名符号 | `file` (body), `old_name` (body), `new_name` (body) |
| POST | `/api/refactor/extract` | 提取函数 | `file` (body), `start_line` (body), `end_line` (body), `new_name` (body) |
| POST | `/api/refactor/move` | 移动模块 | `source_path` (body), `dest_dir` (body) |
| POST | `/api/refactor/add-types` | 添加类型注解 | `file` (body) |
| POST | `/api/refactor/analyze` | 代码质量问题分析 | `code` (body) |
| POST | `/api/refactor/suggest` | 获取重构建议 | `code` (body) |
| POST | `/api/refactor/quality` | 代码质量评分 | `code` (body) |

### 2.9 代码格式化

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/format` | 格式化 Python 代码（支持 black/isort/ruff） | `code` (body), `style` (body): black/isort/ruff |

### 2.10 代码文档与类型提示

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/docstring/styles` | 获取支持的文档字符串风格列表 | 无 |
| POST | `/api/docstring/generate` | 生成文档字符串 | `code` (body), `style` (body): google/numpy/rest |
| GET | `/api/typehint/status` | 获取类型提示功能状态 | 无 |
| POST | `/api/typehint/check` | 检查类型提示 | `code` (body) |
| POST | `/api/typehint/infer` | 推断类型提示 | `code` (body) |

### 2.11 AI 聊天

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/chat` | 非流式 AI 聊天（REST） | `message` (body), `model` (body), `session_id` (body), `system_prompt` (body), `hermes` (body) |
| POST | `/api/completion` | 轻量级内联补全 | `prefix` (body): 代码前缀, `maxTokens` (body): 最大 token 数 |

### 2.12 会话管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/sessions` | 列出所有会话 | `limit` (query): 数量, `offset` (query): 偏移 |
| POST | `/api/sessions` | 创建新会话 | `model` (body): 模型名 |
| GET | `/api/sessions/{session_id}` | 获取会话详情 | `session_id` (path) |
| GET | `/api/sessions/{session_id}/messages` | 获取会话消息历史 | `session_id` (path), `limit` (query), `offset` (query) |
| DELETE | `/api/sessions/{session_id}` | 删除会话 | `session_id` (path) |
| POST | `/api/sessions/batch-delete` | 批量删除会话 | `session_ids` (body): 会话 ID 列表 |
| DELETE | `/api/sessions/all` | 清空所有会话 | 无 |

### 2.13 配置管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/config/setup` | 设置 API Key | `provider` (body), `api_key` (body) |
| GET | `/api/config/keys` | 检查所有提供商的 API Key 配置状态 | 无 |
| GET | `/api/model/config` | 获取模型配置（默认模型、温度、max_tokens 等） | 无 |
| POST | `/api/model/config` | 更新模型配置 | `temperature`, `max_tokens`, `top_p`, `system_prompt` 等 |
| POST | `/api/model/default` | 设置默认模型 | `model` (body): 模型名 |

### 2.14 项目工具

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/project/deps/check` | 检查项目依赖（已安装/缺失/过时） | 无 |
| POST | `/api/project/deps/install` | 安装项目依赖 | `packages` (body): 包名列表 |
| POST | `/api/project/deps/generate` | 生成依赖列表 | 无 |
| GET | `/api/project/deps/analyze` | 分析项目依赖（项目名、Python 版本、框架等） | 无 |
| GET | `/api/project/tests/generate` | 生成测试（需要 AI 模型支持） | 无 |
| POST | `/api/project/tests/run` | 运行测试 | 无 |
| GET | `/api/project/scaffold/types` | 获取项目脚手架类型列表 | 无 |
| POST | `/api/project/scaffold` | 生成项目脚手架 | `project_name` (body), `project_type` (body) |

### 2.15 Skills 管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/skills` | 列出所有可用的 Skills（项目级 + 用户级） | 无 |
| GET | `/api/skills/{name}` | 按名称获取单个 Skill 详情 | `name` (path) |
| GET | `/api/skills/v1` | Skills 注册表查询 | `q` (query): 搜索关键词, `limit` (query): 数量 |

### 2.16 权限管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/permissions` | 获取当前权限策略 | 无 |
| POST | `/api/permissions` | 更新权限策略 | 权限策略配置项 |

### 2.17 移动端状态

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/mobile/status` | 获取移动端状态（iOS/Android/Web） | 无 |
| POST | `/api/mobile/quick` | 移动端快速配置 | 数据对象 |

### 2.18 异步模式与 SQLAlchemy

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/async/patterns` | 获取异步编程模式列表 | 无 |
| GET | `/api/async/patterns/{action}` | 获取特定异步模式详情 | `action` (path) |
| GET | `/api/sqlalchemy/models` | 获取 SQLAlchemy 模型列表 | 无 |
| POST | `/api/sqlalchemy/project` | 创建 SQLAlchemy 项目 | `project_name` (body) |
| POST | `/api/sqlalchemy/generate/model` | 生成 SQLAlchemy 模型 | `model` (body) |
| POST | `/api/sqlalchemy/generate/crud` | 生成 SQLAlchemy CRUD 操作 | `model` (body) |

### 2.19 Docker 工具

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/docker/types` | 获取 Docker 项目类型 | 无 |
| GET | `/api/docker/dockerfile` | 生成 Dockerfile | `project_type` (query) |
| GET | `/api/docker/compose` | 生成 docker-compose.yml | `project_type` (query) |
| POST | `/api/docker/project` | 创建 Docker 项目 | `project_name` (body), `project_type` (body) |

### 2.20 测试与安全

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/test/mock` | 生成 Mock 对象 | `type` (body): mock 类型 |
| GET | `/api/test/coverage` | 获取测试覆盖率 | 无 |
| GET | `/api/test/benchmark` | 获取性能基准测试 | 无 |
| GET | `/api/security/types` | 获取安全类型列表 | 无 |
| POST | `/api/security/{action}` | 执行安全检查 | `action` (path): 安全操作类型 |

### 2.21 Agent 管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/agent/status` | 获取 Agent 状态 | 无 |
| GET | `/api/agent/skills` | 获取 Agent 技能列表 | 无 |
| GET | `/api/agent/skills/{skill_id}` | 获取 Agent 技能详情 | `skill_id` (path) |
| POST | `/api/agent/execute` | 执行 Agent 任务 | `task` (body) |
| GET | `/api/agent/history` | 获取 Agent 历史 | `query` (query): 搜索关键词 |
| GET | `/api/agent/preferences` | 获取 Agent 偏好设置 | 无 |
| POST | `/api/agent/preference` | 设置 Agent 偏好 | `key` (body), `value` (body) |
| POST | `/api/agent/learn` | Agent 学习 | 无 |

---

### 2.22 上下文管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/context` | 获取项目上下文信息 | 无 |
| POST | `/api/context/refresh` | 刷新项目上下文 | 无 |

---

### 2.23 扩展管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/extensions` | 列出所有扩展 | 无 |
| POST | `/api/extensions/install` | 安装扩展 | `name` (body), `version` (body) |
| POST | `/api/extensions/uninstall` | 卸载扩展 | `name` (body) |
| POST | `/api/extensions/enable` | 启用扩展 | `name` (body) |
| POST | `/api/extensions/disable` | 禁用扩展 | `name` (body) |

---

### 2.24 环境管理（env_api）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/env/info` | 获取详细环境信息 | 无 |
| POST | `/api/env/venv/create` | 创建虚拟环境 | `name` (body), `python_version` (body) |
| GET | `/api/env/venv/list` | 列出虚拟环境 | 无 |
| POST | `/api/env/venv/activate` | 激活虚拟环境 | `name` (body) |

---

### 2.25 依赖管理（dep_api）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/deps/list` | 列出项目依赖 | 无 |
| POST | `/api/deps/add` | 添加依赖 | `package` (body), `version` (body) |
| POST | `/api/deps/remove` | 移除依赖 | `package` (body) |
| POST | `/api/deps/update` | 更新依赖 | `package` (body), `version` (body) |
| GET | `/api/deps/outdated` | 检查过时依赖 | 无 |

---

### 2.26 会话搜索

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/sessions/search` | 搜索会话 | `q` (query): 搜索关键词, `limit` (query): 数量 |

---

### 2.27 工作区管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/workspace/info` | 获取工作区信息 | 无 |
| POST | `/api/workspace/create` | 创建工作区 | `name` (body), `path` (body) |
| GET | `/api/workspace/list` | 列出工作区 | 无 |
| DELETE | `/api/workspace/{id}` | 删除工作区 | `id` (path) |

---

### 2.28 知识管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/knowledge` | 列出知识条目 | `limit` (query), `offset` (query) |
| POST | `/api/knowledge` | 创建知识条目 | `title` (body), `content` (body), `tags` (body) |
| GET | `/api/knowledge/{id}` | 获取知识条目 | `id` (path) |
| PUT | `/api/knowledge/{id}` | 更新知识条目 | `id` (path), `title` (body), `content` (body) |
| DELETE | `/api/knowledge/{id}` | 删除知识条目 | `id` (path) |
| GET | `/api/knowledge/search` | 搜索知识库 | `q` (query) |

---

### 2.29 记忆系统

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/memory` | 获取记忆列表 | 无 |
| POST | `/api/memory` | 创建记忆 | `content` (body), `type` (body) |
| DELETE | `/api/memory/{id}` | 删除记忆 | `id` (path) |

---

### 2.30 深度记忆系统（Phase 1 升级）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/deep-memory/status` | 获取深度记忆状态 | 无 |
| POST | `/api/deep-memory/store` | 存储深度记忆 | `content` (body), `metadata` (body) |
| POST | `/api/deep-memory/recall` | 回忆深度记忆 | `query` (body), `limit` (body) |
| POST | `/api/deep-memory/consolidate` | 记忆整合 | 无 |

---

### 2.31 通知系统

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/notifications` | 获取通知列表 | `limit` (query) |
| POST | `/api/notifications/mark-read` | 标记通知已读 | `ids` (body): 通知 ID 列表 |
| DELETE | `/api/notifications/{id}` | 删除通知 | `id` (path) |

---

### 2.32 推荐系统

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/recommendations` | 获取推荐列表 | `type` (query): 推荐类型 |
| POST | `/api/recommendations/feedback` | 提交推荐反馈 | `item_id` (body), `rating` (body) |

---

### 2.33 云同步

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/cloud/status` | 获取云同步状态 | 无 |
| POST | `/api/cloud/sync` | 触发云同步 | `direction` (body): push/pull |
| POST | `/api/cloud/auth` | 云服务认证 | `token` (body) |

---

### 2.34 团队协作

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/team/workspaces` | 列出团队工作区 | 无 |
| POST | `/api/team/workspaces` | 创建团队工作区 | `name` (body), `members` (body) |
| GET | `/api/team/workspaces/{id}` | 获取工作区详情 | `id` (path) |
| POST | `/api/team/workspaces/{id}/join` | 加入工作区 | `id` (path) |
| POST | `/api/team/workspaces/{id}/leave` | 离开工作区 | `id` (path) |

---

### 2.35 Skills API v2

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/skills/v2` | 列出 Skills v2 | `category` (query), `search` (query) |
| POST | `/api/skills/v2` | 创建 Skill | `name` (body), `description` (body), `code` (body) |
| GET | `/api/skills/v2/{id}` | 获取 Skill 详情 | `id` (path) |
| PUT | `/api/skills/v2/{id}` | 更新 Skill | `id` (path) |
| DELETE | `/api/skills/v2/{id}` | 删除 Skill | `id` (path) |
| POST | `/api/skills/v2/{id}/execute` | 执行 Skill | `id` (path), `params` (body) |

---

### 2.36 Skills 市场

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/skills-marketplace` | 浏览技能市场 | `category` (query), `search` (query), `limit` (query) |
| GET | `/api/skills-marketplace/{id}` | 获取技能详情 | `id` (path) |
| POST | `/api/skills-marketplace/{id}/install` | 安装技能 | `id` (path) |
| POST | `/api/skills-marketplace/publish` | 发布技能到市场 | `name` (body), `description` (body), `code` (body) |

---

### 2.37 项目脚手架

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/scaffold/templates` | 获取脚手架模板列表 | 无 |
| POST | `/api/scaffold/generate` | 生成项目脚手架 | `template` (body), `name` (body), `path` (body) |

---

### 2.38 第三方集成

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/integrations` | 列出已安装集成 | 无 |
| POST | `/api/integrations/connect` | 连接集成服务 | `type` (body), `config` (body) |
| POST | `/api/integrations/disconnect` | 断开集成服务 | `type` (body) |
| GET | `/api/integrations/{type}/status` | 获取集成状态 | `type` (path) |

### 2.39 高级功能（advanced_api）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/scheduler/start` | 启动调度器 | 无 |
| POST | `/api/scheduler/stop` | 停止调度器 | 无 |
| GET | `/api/scheduler/status` | 获取调度器状态 | 无 |
| GET | `/api/scheduler/tasks` | 列出调度任务 | 无 |
| POST | `/api/scheduler/tasks` | 添加调度任务 | `id` (body), `name` (body), `trigger` (body), `config` (body) |
| DELETE | `/api/scheduler/tasks/{id}` | 删除调度任务 | `id` (path) |
| GET | `/api/rules` | 获取规则列表 | 无 |
| POST | `/api/rules` | 创建规则 | `name` (body), `pattern` (body), `action` (body) |
| DELETE | `/api/rules/{id}` | 删除规则 | `id` (path) |
| GET | `/api/debug/info` | 获取调试信息 | 无 |
| POST | `/api/debug/log` | 获取调试日志 | `level` (body), `limit` (body) |

---

### 2.40 全自主开发流水线

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/autonomous/pipeline` | 启动全自主开发流水线 | `task` (body), `target` (body), `auto_apply` (body) |
| GET | `/api/autonomous/status/{task_id}` | 获取流水线状态 | `task_id` (path) |
| POST | `/api/autonomous/cancel/{task_id}` | 取消流水线 | `task_id` (path) |
| GET | `/api/autonomous/history` | 获取流水线历史 | `limit` (query) |

---

### 2.41 多平台消息网关（Phase 1）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/gateway/platforms` | 列出支持的消息平台 | 无 |
| POST | `/api/gateway/platforms/{platform}/connect` | 连接消息平台 | `platform` (path), `config` (body) |
| POST | `/api/gateway/platforms/{platform}/disconnect` | 断开消息平台 | `platform` (path) |
| GET | `/api/gateway/platforms/{platform}/status` | 获取平台连接状态 | `platform` (path) |
| POST | `/api/gateway/send` | 通过网关发送消息 | `platform` (body), `target` (body), `message` (body) |

---

### 2.42 Docker 沙箱（Phase 1）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/sandbox/status` | 获取沙箱状态（Docker/子进程） | 无 |
| POST | `/api/sandbox/exec` | 在 Docker 沙箱中执行代码 | `code` (body), `language` (body), `timeout` (body) |
| POST | `/api/sandbox/create` | 创建沙箱环境 | `image` (body), `memory` (body), `cpu` (body) |
| DELETE | `/api/sandbox/{id}` | 销毁沙箱 | `id` (path) |
| GET | `/api/sandbox/list` | 列出运行中的沙箱 | 无 |

---

### 2.43 幻觉抑制守卫（Phase 1）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/guard/validate` | 验证 AI 输出是否存在幻觉 | `output` (body), `context` (body) |
| GET | `/api/guard/stats` | 获取幻觉检测统计 | 无 |
| POST | `/api/guard/threshold` | 设置幻觉检测阈值 | `threshold` (body) |

---

### 2.44 DAG 并行任务调度（Phase 2-3）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/dag/create` | 创建 DAG 任务图 | `tasks` (body): 任务节点列表, `edges` (body): 依赖边 |
| POST | `/api/dag/execute` | 执行 DAG 任务 | `dag_id` (body) |
| GET | `/api/dag/status/{dag_id}` | 获取 DAG 执行状态 | `dag_id` (path) |
| POST | `/api/dag/cancel/{dag_id}` | 取消 DAG 执行 | `dag_id` (path) |
| GET | `/api/dag/history` | 获取 DAG 执行历史 | `limit` (query) |

---

### 2.45 任务评分与持久化（Phase 2-3）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/tasks` | 列出任务 | `status` (query), `limit` (query) |
| POST | `/api/tasks` | 创建任务 | `title` (body), `description` (body), `priority` (body) |
| GET | `/api/tasks/{id}` | 获取任务详情 | `id` (path) |
| PUT | `/api/tasks/{id}` | 更新任务 | `id` (path) |
| DELETE | `/api/tasks/{id}` | 删除任务 | `id` (path) |
| POST | `/api/tasks/{id}/score` | 任务评分 | `id` (path), `score` (body) |

---

### 2.46 进化报告生成（Phase 2-3）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/report/generate` | 生成进化报告 | `mode` (body): closed_loop/git_diff, `task_id` (body), `base_branch` (body) |
| GET | `/api/report/list` | 列出报告 | `limit` (query) |
| GET | `/api/report/{report_id}` | 获取报告详情 | `report_id` (path) |

---

### 2.47 专业 Agent 团队（Phase 2-3）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/agents` | 列出所有 Agent | 无 |
| POST | `/api/agents` | 创建 Agent | `name` (body), `role` (body), `model` (body) |
| GET | `/api/agents/{id}` | 获取 Agent 详情 | `id` (path) |
| DELETE | `/api/agents/{id}` | 删除 Agent | `id` (path) |
| POST | `/api/agents/team` | 创建 Agent 团队 | `name` (body), `members` (body) |
| POST | `/api/agents/team/{id}/execute` | 执行团队任务 | `id` (path), `task` (body) |

---

### 2.48 闭环学习循环（Phase 2-3）

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/learning/status` | 获取学习系统状态 | 无 |
| POST | `/api/learning/feedback` | 提交学习反馈 | `task_id` (body), `rating` (body), `comment` (body) |
| GET | `/api/learning/signals` | 获取学习信号 | `limit` (query) |
| POST | `/api/learning/optimize` | 触发学习优化 | 无 |

---

### 2.49 文件传输

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/file-transfer/upload` | 上传文件 | multipart/form-data |
| GET | `/api/file-transfer/download/{path}` | 下载文件 | `path` (path) |

---

### 2.50 流水线

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/pipeline/run` | 运行流水线 | `stages` (body), `context` (body) |
| GET | `/api/pipeline/status` | 获取流水线状态 | 无 |

---

### 2.51 GitHub 集成

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/github/status` | 获取 GitHub 集成状态 | 无 |
| POST | `/api/github/auth` | GitHub 认证 | `token` (body) |
| GET | `/api/github/repos` | 列出 GitHub 仓库 | 无 |
| POST | `/api/github/clone` | 克隆仓库 | `url` (body), `path` (body) |

---

## 3. WebSocket 端点

### 3.1 聊天 WebSocket

| 端点 | 说明 | 协议 |
|------|------|------|
| `WS /ws/chat` | V1 实时 AI 聊天，支持流式输出、会话管理、文件操作、MCP 工具调用 | 见下方协议详情 |
| `WS /ws/chat/v2` | V2 AI-Centric 聊天，接入 V2 引擎能力总线、审计追踪和意识引擎 | 见下方协议详情 |

#### 3.1.1 V1 聊天协议 (`/ws/chat`)

**客户端 → 服务器消息类型：**

| 消息类型 | 说明 | 关键字段 |
|----------|------|----------|
| `message` | 发送聊天消息 | `message` (str): 用户消息, `model` (str): 模型名, `system_prompt` (str): 系统提示, `hermes` (bool): Hermes 模式, `reasoning_effort` (str): 推理力度, `enable_cache` (bool): 启用缓存 |
| `create_session` | 创建新会话 | 无 |
| `switch_session` | 切换会话 | `session_id` (str) |
| `list_sessions` | 列出会话 | 无 |
| `history` | 获取历史消息 | `session_id` (str) |
| `session_share_join` | 加入共享会话 | `share_session_id` (str) |
| `session_share_leave` | 离开共享会话 | 无 |
| `write_file` | 写入文件 | `path` (str), `content` (str) |
| `project_tree` | 获取项目树 | `path` (str), `max_depth` (int) |
| `file_open` | 打开文件 | `path` (str) |
| `diff_preview` | 预览差异 | `file` (str), `staged` (bool) |
| `git_status` | Git 状态 | `path` (str) |
| `execute_plan` | 执行 Agent 计划 | `plan` (str), `model` (str) |
| `inline_edit` | 内联代码编辑 | `code` (str), `instruction` (str), `file_path` (str), `language` (str) |
| `run_fix` | Run & Fix 自动循环 | `task` (str), `target_file` (str) |
| `dep_agent` | 依赖智能体分析 | `code` (str) |
| `quality_check` | 代码质量守卫 | `file_path` (str) |
| `test_generator` | 智能测试生成 | `file_path` (str) |
| `team_ws` | 团队协作 | `subcommand` (str): create/list/get/delete/join/leave/members/review_* |
| `cloud` | PyCoder Cloud | `subcommand` (str): register/login/check_quota/usage/plans/upgrade |
| `mcp_list` | 列出 MCP 工具 | 无 |
| `mcp_call` | 调用 MCP 工具 | `tool` (str), `args` (dict) |
| `mcp_connect` | 连接外部 MCP Server | `name` (str), `command` (str), `args` (list) |
| `mcp_disconnect` | 断开 MCP Server | `name` (str) |

**服务器 → 客户端事件：**

| 事件类型 | 说明 |
|----------|------|
| `connected` | 连接成功，返回 session_id、version、has_history |
| `session_created` | 新会话创建 |
| `session_switched` | 会话切换 |
| `session_list` | 会话列表 |
| `history` | 历史消息 |
| `token` | 流式输出 token |
| `reasoning` | 推理过程 |
| `done` | 流式输出完成 |
| `error` | 错误消息 |
| `file_write_result` | 文件写入结果 |
| `project_tree` | 项目树结构 |
| `file_open` | 文件打开结果 |
| `diff_preview` | Diff 预览 |
| `git_status` | Git 状态 |
| `inline_edit_stream` | 内联编辑流式输出 |
| `inline_edit_done` | 内联编辑完成 |
| `run_fix_done` | Run & Fix 完成 |
| `dep_agent_done` | 依赖分析完成 |
| `quality_report` | 质量报告 |
| `test_generator_done` | 测试生成完成 |
| `team_ws_result` | 团队协作结果 |
| `mcp_tools` | MCP 工具列表 |
| `mcp_result` | MCP 工具调用结果 |
| `mcp_connect_result` | MCP 连接结果 |

#### 3.1.2 V2 聊天协议 (`/ws/chat/v2`)

V2 端点完全兼容 V1 的消息格式，额外支持：

| 消息类型 | 说明 | 关键字段 |
|----------|------|----------|
| `v2_capabilities` | 列出 V2 能力 | 无 |
| `v2_call` | 直接调用 V2 能力 | `capability_id` (str), `params` (dict) |

V2 的 `connected` 事件额外返回 `engine` (固定为 "v2")、`capabilities`（能力数量）和 `trust_level`（信任级别）。

### 3.2 终端 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /ws/terminal` | 交互式终端，支持 Windows（pywinpty PTY）和 Unix（pty） |

**客户端 → 服务器消息：**

| 消息类型 | 说明 |
|----------|------|
| `command` | 执行命令，`data` 字段包含命令文本 |
| `input` | 发送原始输入，`data` 字段包含输入文本 |
| `cd` | 切换目录，`path` 字段包含目标路径 |
| `resize` | 调整终端大小，`cols` 和 `rows` 字段 |
| `ping` | 心跳检测 |

**服务器 → 客户端事件：**

| 事件类型 | 说明 |
|----------|------|
| `connected` | 连接成功，返回 cwd、shell、platform、pty_mode |
| `output` | 终端输出，`data` 字段包含输出文本 |
| `cwd` | 当前工作目录变更 |
| `resize_ack` | 终端大小调整确认 |
| `exit` | 终端退出，`code` 字段为退出码 |
| `error` | 错误消息 |
| `pong` | 心跳响应 |

### 3.3 通知 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /ws/notifications` | 实时通知推送 |

### 3.4 消息网关 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /ws/gateway` | 多平台消息网关实时推送 |

### 3.5 全自主流水线 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /ws/autonomous` | 全自主开发流水线实时状态推送 |

### 3.6 团队协作 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /ws/collab` | 团队协作实时通信 |

---

## 4. V2 能力总线（V2 Capability Bus）

V2 引擎提供了一套完整的能力总线系统，用于自进化、能力管理和信任控制。

### 4.1 进化端点

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/v2/evolution/scan` | 扫描代码库，识别问题 | `path` (body): 扫描路径, `use_llm` (bool): 是否使用 LLM 深度分析 |
| POST | `/api/v2/evolution/fix` | 为指定问题生成修复方案 | `file` (body), `line` (body), `severity` (body), `issue_type` (body), `title` (body), `description` (body), `suggestion` (body) |
| POST | `/api/v2/evolution/apply` | 应用修复方案（需人工确认） | `issue_index` (body), `confirm` (bool) |
| GET | `/api/v2/evolution/history` | 获取进化历史 | `limit` (query) |
| GET | `/api/v2/evolution/stats` | 获取进化统计 | 无 |
| GET | `/api/v2/evolution/tasks` | 列出进化任务 | `limit` (query) |
| GET | `/api/v2/evolution/tasks/{task_id}` | 获取进化任务详情 | `task_id` (path) |
| POST | `/api/v2/evolution/run` | 运行进化管线 | `type` (body), `target` (body), `custom` (body), `auto_apply` (body), `dry_run` (body) |
| POST | `/api/v2/evolution/watch/start` | 启动自进化监控 | `interval` (body): 扫描间隔（秒） |
| POST | `/api/v2/evolution/watch/stop` | 停止自进化监控 | 无 |
| GET | `/api/v2/evolution/watch/status` | 获取监控状态 | 无 |

### 4.2 自优化端点

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/v2/evolution/optimize/analyze-usage` | 分析使用模式 | `days` (query): 分析天数 |
| POST | `/api/v2/evolution/optimize/prompts` | 优化提示词 | 无 |
| POST | `/api/v2/evolution/optimize/heal` | 自动修复 | `target` (query), `dry_run` (query) |
| GET | `/api/v2/evolution/optimize/report` | 获取优化报告 | 无 |

### 4.3 信任管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/v2/trust/escalate` | 提升 AI 信任级别 | `reason` (body) |
| GET | `/api/v2/trust/status` | 获取信任状态 | 无 |
| GET | `/api/v2/evolution/approvals` | 列出待审批进化任务 | 无 |
| POST | `/api/v2/evolution/approve/{approval_id}` | 审批进化任务 | `approval_id` (path) |
| POST | `/api/v2/evolution/reject/{approval_id}` | 拒绝进化任务 | `approval_id` (path) |
| POST | `/api/v2/evolution/token/generate` | 生成进化令牌 | `files` (body): 文件列表 |
| DELETE | `/api/v2/evolution/token` | 清除令牌 | 无 |
| GET | `/api/v2/evolution/token/status` | 获取令牌状态 | 无 |

### 4.4 能力管理

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/api/v2/capabilities` | 列出所有已注册的能力 | `category` (query): 能力分类, `search` (query): 搜索关键词 |

**能力分类：**
- `CODE_GENERATION` — 代码生成
- `CODE_ANALYSIS` — 代码分析
- `REFACTORING` — 代码重构
- `TESTING` — 测试
- `FILE_OPERATION` — 文件操作
- `GIT_OPERATION` — Git 操作
- `SHELL_EXECUTION` — Shell 执行
- `WEB_FETCH` — 网页抓取
- `NOTIFICATION` — 通知

**信任级别：**
- `READ_ONLY` (0) — 只读
- `LOW_TRUST` (1) — 低信任
- `MEDIUM_TRUST` (2) — 中等信任
- `HIGH_TRUST` (3) — 高信任
- `FULL_AUTONOMY` (4) — 完全自主

### 4.5 进化 WebSocket

| 端点 | 说明 |
|------|------|
| `WS /api/v2/ws/evolution` | V2 进化实时通信，支持流式进化事件 |

**消息类型：**
- `evolve` — 启动进化任务（流式返回事件）
- `stats` — 获取进化统计
- `tasks` — 获取任务列表
- `approve` — 审批操作
- `reject` — 拒绝操作
- `approvals` — 获取待审批列表

---

## 5. 错误码

| HTTP 状态码 | 说明 | 常见场景 |
|-------------|------|----------|
| 200 | 成功 | 正常响应 |
| 400 | 请求参数错误 | 缺少必填参数、路径穿越、文件类型错误 |
| 401 | 未授权 | 缺少或错误的 API Key |
| 403 | 禁止访问 | 无权访问指定路径 |
| 404 | 资源不存在 | 会话/文件/任务未找到 |
| 413 | 请求体过大 | 文件大小超过限制（最大 1MB） |
| 415 | 不支持的媒体类型 | 文件编码不支持（可能是二进制文件） |
| 422 | 请求体验证失败 | Pydantic 模型校验失败 |
| 429 | 请求过于频繁 | 超过速率限制（每 IP 每分钟 60 次） |
| 500 | 服务器内部错误 | 代码执行异常、Git 操作失败 |
| 503 | 服务不可用 | V2 引擎未初始化、进化引擎未就绪 |

### 5.1 代码执行特定错误

| 错误类型 | 说明 |
|----------|------|
| `SecurityViolation` | 静态扫描检测到危险模式（`__import__`、`exec`、`eval`、`compile` 等） |
| `BannedImport` | 尝试导入禁止模块（`os`、`subprocess`、`socket` 等） |
| `TimeoutError` | 代码执行超时 |
| `SyntaxError` | 代码语法错误 |
| `SubprocessError` | 子进程执行异常 |

---

## 附录：中间件与安全

### A.1 API 密钥认证中间件

- 路径 `/api/health`、`/docs`、`/openapi.json` 和 `/ws/*` 免认证
- `file://` 来源和 `Origin: null` 的请求免认证（VSCode 内置浏览器 / Electron 开发模式）
- 使用 `secrets.compare_digest` 防止时序攻击

### A.2 速率限制中间件

- 限制范围：`/api/code/`、`/api/chat`、`/api/skills`
- 限制策略：每 IP 每分钟 60 次请求
- 窗口时间：60 秒

### A.3 CORS 中间件

- 允许的来源：`localhost:8420`、`localhost:8423`、`localhost:5173`
- 允许的方法：`GET`、`POST`、`PUT`、`DELETE`、`OPTIONS`
- 允许的请求头：`Content-Type`、`Authorization`、`X-API-Key`、`X-Request-ID`
- 支持凭证传递（`allow_credentials=True`）

### A.4 代码执行沙箱安全

代码执行通过多层安全防护：

1. **Layer 1 — 静态扫描**：正则检测危险模式（`__import__`、`exec`、`eval`、`compile`、`__subclasses__`、`getattr` with dunder）
2. **Layer 2 — 禁止模块检查**：阻止导入 40+ 个危险模块（`os`、`subprocess`、`socket`、`threading`、`ctypes` 等）
3. **Layer 3 — 子进程隔离**：使用独立子进程执行代码，白名单 `__builtins__`（仅安全函数/类型）
4. **超时限制**：默认 30 秒，最长 600 秒（长时运行模式）
5. **输出长度限制**：最大 10,000 字符
6. **代码长度限制**：最大 100,000 字符
# PyCoder 长期迭代追踪日志

> 创建时间: 2026-07-29 | 维护者: PyCoder Team
>
> 本文档记录 PyCoder 的迭代节奏、KPI 指标、待办事项与版本里程碑。
> 不受对话轮次限制，持续更新直至产品达到完美状态。

## 一、迭代节奏

- **小迭代**: 单一功能/bug 修复，1 次 commit 内完成
- **中迭代**: 功能模块完善 + 测试补充，1-3 天
- **大迭代**: 跨模块升级 + 竞品对齐，1-2 周

每次迭代必须满足的**质量门禁**：
- 本地: `python scripts/run.py quality-gate-quick`（commit 前）
- CI: GitHub Actions 自动运行 lint + typecheck + security + test + coverage

## 二、KPI 指标追踪

| 指标 | 当前值 | 目标值 | 更新日期 |
|------|--------|--------|----------|
| 单元测试通过率 | 188/188 (100%) | ≥ 95% | 2026-07-29 |
| 测试覆盖率 (核心模块) | 41% (server) / ≥80% (升级模块) | ≥ 80% 全局 | 2026-07-29 |
| PerfAdvisor 规则数 | 31 | 40+ | 2026-07-29 |
| 错误模式库数量 | 50+ | 80+ | 2026-07-29 |
| Agent 角色数 | 14 | 20+ | 2026-07-29 |
| ShellTranslator 命令数 | 30+ | 50+ | 2026-07-29 |
| CI 流水线检查项 | 5 (lint/type/security/test/build) | 6 (+docs) | 2026-07-29 |
| Bandit HIGH 问题数 | 0 | 0 | 2026-07-29 |
| Ruff 错误数 | ~200 (从 2184 降低 91%) | < 50 | 2026-07-29 |
| LSP 能力数 | 7 (completion/definition/hover/references/symbol/diagnostics/context_integration) | 10+ | 2026-07-29 |
| LSP 集成阶段 | 阶段 2 完成 (诊断→AI 提示词) | 阶段 3 (Electron Monaco) | 2026-07-29 |

## 三、迭代历史

### 迭代 #5 — 2026-07-29: LSP 集成阶段 2 — 诊断注入 AI 提示词

**变更内容**:
- **LSPClient 诊断捕获能力** (`pycoder/lsp/client.py`):
  - 新增 `Diagnostic` 数据类 (file_path/line/severity/code/source/message)
  - 实现 `textDocument/publishDiagnostics` 通知处理 (`_handle_publish_diagnostics`)
  - 诊断存储与查询: `get_diagnostics()` / `get_all_diagnostics()` / `clear_diagnostics()`
  - 诊断回调注册机制: `register_diagnostics_handler()` / `unregister_diagnostics_handler()`
  - 严重度映射常量 `DIAGNOSTIC_SEVERITY` (1=error/2=warning/3=info/4=hint)
  - URI → 本地路径转换 (`_uri_to_path`)
  - 回调异常隔离 (单个回调异常不影响其他回调和诊断存储)
- **LSPContextIntegrator** (`pycoder/lsp/context_integration.py` 新增):
  - 诊断收集 (`collect_diagnostics` / `collect_all_diagnostics`)
  - 按严重度过滤 (默认仅 error + warning)
  - 多维限量: `max_diagnostics_per_file` / `max_total_diagnostics` / `max_files`
  - 严重度优先级排序 (error > warning > information > hint)
  - AI 提示词格式化 (`format_diagnostics_for_prompt`) — 含错误统计 + 行号 + 修复建议
  - 锚点片段生成 (`get_anchor_section`) — 带 `LSP_DIAGNOSTICS_ANCHOR` 标记便于 ContextOrchestrator 识别
  - 统计信息 (`get_stats`) — total/errors/warnings/files_affected
  - 优雅降级 (LSP 异常不影响主流程)
- **DiagnosticsAggregator 升级** (`pycoder/lsp/diagnostics.py`):
  - 新增 `LSPClient` 模式 (`scan_file_from_client` / `scan_all_from_client`)
  - 兼容旧 `LSPManager` 模式 (`scan_file`)
  - 自动语言推断 (基于文件扩展名, 支持 5 种语言)
  - `AggregatedDiagnostic` 扩展字段 (code/end_line/end_column/source)
- **ContextOrchestrator LSP 集成** (`pycoder/server/services/context_orchestrator.py`):
  - 新增 `set_lsp_integrator()` / `set_context_files()` / `add_context_file()` / `get_lsp_diagnostics_snippet()`
  - `process_user_message` 自动注入 LSP 诊断到 anchor
  - 返回结果新增 `lsp_diagnostics` 字段 (独立片段) 与 `lsp_stats` 字段 (统计)
  - 推送 `lsp_diagnostics` WS 事件 (含统计)
  - LSP 异常隔离 (集成器失败不影响对话主流程)
- **模块导出** (`pycoder/lsp/__init__.py`):
  - 延迟导入 `LSPContextIntegrator` 避免循环依赖
- **单元测试** (`tests/test_lsp_context_integration.py` 新增): 54 项测试
  - Diagnostic 数据类 (5 项)
  - LSPClient 诊断捕获 (13 项) — publishDiagnostics 处理/缓存/回调/异常隔离
  - LSPContextIntegrator (20 项) — 收集/过滤/限量/格式化/锚点/统计/降级
  - DiagnosticsAggregator LSPClient 模式 (6 项)
  - ContextOrchestrator 端到端集成 (10 项) — set_lsp_integrator/context_files/process_user_message

**测试**: 188 项全部通过 (含 54 个新 LSP 集成测试 + 134 个回归测试)

**未完成项** (转入下一迭代):
- LSP 集成阶段 3: Electron Monaco Editor 集成 (前端显示诊断)
- 集成测试 (需安装 pyright 后端到端测试)
- LSP 诊断 → 自进化反馈闭环 (诊断错误模式自动学习)

### 迭代 #4 — 2026-07-29: LSP 集成阶段 1 — 协议层与客户端实现

**变更内容**:
- **LSP 协议层** (`pycoder/lsp/protocol.py`):
  - JSON-RPC 2.0 消息编解码 (Content-Length 帧格式)
  - LSPMessage 数据类 (请求/通知/响应)
  - 消息构造工具 (make_request/make_notification/make_response/make_error_response)
  - 异步消息解码 (decode_message)
  - 标准 JSON-RPC 错误码常量
- **LSP 客户端** (`pycoder/lsp/client.py`):
  - LSPClient 类: 完整生命周期管理 (start/initialize/shutdown/stop)
  - 7 个 LSP 方法: did_open/did_change/did_close/completion/definition/hover/references/document_symbol
  - 后台消息读取循环 (asyncio.Task)
  - 请求-响应 Future 映射机制
  - 4 个数据类: CompletionItem/Location/Hover/DocumentSymbol
  - 优雅降级 (pyright 未安装时返回友好提示)
- **LSP 工具能力注册** (`pycoder/capabilities/tools/lsp_tools.py`):
  - 6 个 READ_ONLY 能力: tools.lsp.completion/definition/hover/references/document_symbol/diagnostics
  - 工作区单例客户端管理
  - 权限矩阵更新 (permissions.py)
- **单元测试** (`tests/test_lsp_client.py`): 30 项测试
  - 协议层: 消息编解码/帧格式/roundtrip
  - 数据类: CompletionItem/Location/Hover/DocumentSymbol 转换
  - 客户端: 配置/状态/解析方法

**测试**: 134 项全部通过 (含 30 个新 LSP 测试)

**未完成项** (转入下一迭代):
- LSP 集成阶段 2: 与 ContextBuilder 集成 (将 LSP 诊断注入 AI 提示词)
- LSP 集成阶段 3: Electron Monaco Editor 集成
- 集成测试 (需安装 pyright 后端到端测试)

### 迭代 #3 — 2026-07-29: 格式统一 + PerfAdvisor 扩展 + LSP 调研

**变更内容**:
- **历史代码格式统一**: ruff 错误 2184 → ~200 (减少 91%)
  - 自动修复 2001 个格式问题 (ruff --fix)
  - 478 个文件 black 格式化
  - isort 导入排序
  - 36 个 unsafe-fix (B007 未使用循环变量 / B904 raise-from / F601 重复 key 等)
- **PerfAdvisor 扩展**: 19 → 31 条规则
  - 并发反模式: async_create_task 未保存引用、asyncio.wait 无 timeout、线程锁粒度过大
  - 内存反模式: readlines 全量加载、open 未用 with、大列表累积
  - 序列化反模式: pickle.load 不安全、循环内 json.dumps
  - 数据结构反模式: list.pop(0) 当队列、list.insert(0) 头部插入
  - 缓存反模式: 无缓存重复计算、无界缓存
  - 新增 8 项 AST/正则检测逻辑 + 8 个测试用例
- **LSP 集成调研报告**: 推荐 Pyright (MIT+性能最优)，分 3 阶段集成
  - 阶段1 (#4): 基础 LSP 客户端 (补全/跳转)
  - 阶段2 (#5): 完整 LSP + ContextBuilder 集成
  - 阶段3 (#6): Electron Monaco Editor 集成

**测试**: 104 项全部通过 (含 8 个新规则测试)

**未完成项** (转入下一迭代):
- 剩余 ~200 个 ruff 错误 (F821 undefined-name 51个 + F841 unused-variable 69个) 需逐个人工审查
- LSP 集成阶段 1 实际实现

### 迭代 #2 — 2026-07-29: 长期迭代机制建立

**变更内容**:
- 扩展 `PerfAdvisor` 性能规则库: 10 → 19 条
  - 新增: N+1 查询、async 同步 I/O、循环内 import、deepcopy 滥用、
    sort+reverse 双遍历、裸 except、list(d.keys()) 多余转换、
    for+break 查找、重复字典查询
- 创建 `scripts/quality_gate.py` 本地质量门禁脚本
  - 6 项检查: ruff/black/imports/bandit/mypy/pytest
  - 支持 `--quick`/`--skip-typecheck`/`--skip-security` 灵活组合
- 注册 `quality-gate` / `quality-gate-quick` 任务到 `scripts/run.py`
- 创建长期迭代追踪文档（本文件）

**测试**:
- 17 项性能规则测试全部通过
- 核心模块导入检查通过

**未完成项** (转入下一迭代):
- 项目历史代码格式统一 (2184 个 ruff 错误，507 个 black 格式问题)
  - 这是历史遗留问题，需要单独执行 `black pycoder/ tests/` + `ruff --fix` 批量修复
- 竞品对比报告深度内容补充

### 迭代 #1 — 2026-07-29: 8 项核心功能升级

**变更内容**:
- 新增 7 个核心模块:
  - `test_runner.py` — 自动化测试执行
  - `project_index.py` — 项目结构感知 + 符号索引
  - `task_pipeline.py` — 多步骤命令管道
  - `error_patterns.py` — 50+ 错误模式库
  - `decision_snapshot.py` — 决策快照管理
  - `perf_advisor.py` — 性能反模式检测
  - `code_sanitizer.py` — 安全漏洞自动检测
- 新增 2 个工具能力: `tools.testing.run_tests`, `tools.shell.run_pipeline`
- 集成 `error_classifier.infer_root_cause()` 根因推断
- 87 项单元测试全部通过
- 详见 commit `1751eee`

## 四、待办事项 (按优先级)

### P0 — 关键 (本周内)
- [x] LSP 集成阶段 2: 与 ContextBuilder 集成 (LSP 诊断 → AI 提示词) ✓ 迭代#5 完成
- [ ] 剩余 ~200 个 ruff 错误人工审查 (F821/F841)

### P1 — 重要 (2 周内)
- [ ] LSP 集成阶段 3: Electron Monaco Editor 集成 (前端显示诊断)
- [ ] LSP 诊断 → 自进化反馈闭环 (诊断错误模式自动学习)
- [ ] LSP 集成端到端测试 (安装 pyright 后跑真实诊断)
- [ ] PerfAdvisor 规则扩展至 40+ (添加 I/O/算法复杂度规则)
- [ ] 错误模式库扩展至 80+ (添加框架特定错误)
- [ ] 竞品对比报告深度分析 (Codex/Trae 最新版本功能)
- [ ] VS Code 插件版本原型

### P2 — 改进 (1 月内)
- [ ] 测试覆盖率提升至 80% 全局
- [ ] Agent 角色扩展至 20+
- [ ] ShellTranslator 命令扩展至 50+
- [ ] 前端 UI 交互优化

### P3 — 长期
- [ ] 多语言项目支持 (Rust/Go/Java)
- [ ] 自进化系统闭环验证
- [ ] 性能基准测试套件

## 五、竞品对标快照

| 能力 | PyCoder | Codex | Trae | 备注 |
|------|---------|-------|------|------|
| 代码生成 | ✅ 强 | ✅ 强 | ✅ 强 | 持平 |
| 测试执行 | ✅ 强 | ✅ 强 | ⚠️ 基础 | PyCoder 领先 |
| 错误分析 | ✅ 强 (50+ 模式) | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| 性能分析 | ✅ 中 (19 规则) | ✅ 强 | ⚠️ 基础 | 需扩展至 30+ |
| 安全审查 | ✅ 强 | ✅ 强 | ⚠️ 基础 | PyCoder 领先 |
| 自进化 | ✅ 独有 | ❌ 无 | ❌ 无 | PyCoder 独有 |
| Agent 团队 | ✅ 14 角色 | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| 记忆系统 | ✅ 4 层 | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| IDE 集成 | ⚠️ Electron | ✅ VS Code | ✅ VS Code | **主要差距** |
| 开源 | ✅ 完全开源 | ❌ 闭源 | ❌ 闭源 | PyCoder 领先 |

## 六、迭代触发条件

自动触发下一迭代的条件（满足任一即触发）：
1. 新增/修改核心模块代码
2. 测试失败率 > 0
3. Bandit 发现新的 HIGH 严重度问题
4. 覆盖率下降超过 2%
5. 竞品发布新功能

## 七、质量门禁命令速查

```bash
# 本地快速预检查 (commit 前)
python scripts/run.py quality-gate-quick

# 本地全量质量门禁
python scripts/run.py quality-gate

# 仅运行测试
python scripts/run.py test-fast

# 仅 lint
python scripts/run.py lint

# CI 模拟 (本地)
python -m pytest tests/ -m "not slow" --cov=pycoder --cov-fail-under=80
python -m ruff check pycoder/ tests/
python -m bandit -r pycoder/ -ii
```

---

*本文档由 PyCoder 长期迭代机制维护，每次迭代后更新。*

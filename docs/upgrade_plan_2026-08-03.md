# PyCoder 全面升级优化方案 (2026-08-03)

> 本文档覆盖 11 个方面的升级计划，按优先级分阶段实施。
> P0/P1/P2 已在本次执行中完成，P3 为大型功能架构方案（待实施）。

## 目录

- [执行摘要](#执行摘要)
- [P0 — 立即修复（已完成）](#p0--立即修复已完成)
- [P1 — 核心功能修复（已完成）](#p1--核心功能修复已完成)
- [P2 — 测试基础设施优化（已完成）](#p2--测试基础设施优化已完成)
- [P3 — 大型功能架构方案（待实施）](#p3--大型功能架构方案待实施)
- [验收标准与后续行动](#验收标准与后续行动)

---

## 执行摘要

| 优先级 | 项目 | 状态 | 影响范围 |
|--------|------|------|----------|
| P0-1 | 循环执行问题（agent_loop / ws_handler） | ✅ 前轮已修复 | `agent_loop.py`, `ws_handler.py` |
| P0-2 | 测试引用缺失符号 `generate_scaffold_project` | ✅ 本次修复 | `template_code.py` |
| P0-3 | `.gitignore` — db-shm/db-wal 已跟踪 | ✅ 本次修复 | `data/skills/` |
| P1-1 | `exec_python` 沙箱偶发无输出 | ✅ 本次修复 | `code_exec.py` |
| P1-2 | `shell_run` PowerShell `&&` 兼容性 | ✅ 已确认无需改动 | `shell_translator.py` |
| P1-3 | `pipeline.py` mcp_tools 残留引用 | ✅ 已确认无需改动 | `pipeline.py` |
| P2-1 | 测试套件 300s 超时 | ✅ 本次修复 | `pytest.ini` → `pyproject.toml` |
| P3-1 | 实时协作（Yjs CRDT） | 📋 架构方案 | 新模块 |
| P3-2 | GUI 编辑器（Monaco） | 📋 架构方案 | 前端 |
| P3-3 | 语音输入（Web Speech API） | 📋 架构方案 | 前端 |
| P3-4 | 移动端适配 | 📋 架构方案 | 前端 |

---

## P0 — 立即修复（已完成）

### P0-2: 实现 `generate_scaffold_project` 及相关模板函数

**根因**: `pycoder/python/template_code.py` 在 v0.10.0 被回退到旧版后，缺失 `generate_scaffold_project` 和 `generate_streamlit_dashboard` 两个函数；`generate_fastapi_crud` 引用了未定义的 `_write_crud_*` 助手函数（F821 错误）。

**修复内容** ([template_code.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/python/template_code.py)):

1. 完全重写 `template_code.py`，统一 4 个公共函数签名：
   - `generate_fastapi_crud(project_dir, entity_name="item") -> list[str]`
   - `generate_fastapi_auth(project_dir, entity_name="user") -> list[str]`
   - `generate_streamlit_dashboard(project_dir, dashboard_name="数据看板") -> list[str]`
   - `generate_scaffold_project(project_dir, template_name="fastapi-crud", entity_name="item") -> list[str]`
2. 返回值为生成文件的 POSIX 相对路径列表（如 `"src/main.py"`），匹配测试契约
3. `generate_scaffold_project` 作为统一入口，按 `template_name` 分发到具体生成器；未知模板回退到 `fastapi-crud`
4. 实体名支持复数化（`item→items`, `product→products`, `category→categories`）
5. 向后兼容 `generate.py` 中的调用 `generate_scaffold_project(project_path, template_name, entity_en)`

**验证**: `tests/test_template_code_coverage.py` (25 用例) + `tests/test_runner.py` (2 用例) = **27 passed in 0.52s**

### P0-3: 取消跟踪 SQLite WAL 文件

**根因**: `.gitignore` 已包含 `*.db-shm` / `*.db-wal` 规则，但 `data/skills/skills.db-shm` 和 `skills.db-wal` 在前次提交中已被加入 git 索引，`.gitignore` 对已跟踪文件无效。

**修复**:
```bash
git rm --cached data/skills/skills.db-shm data/skills/skills.db-wal
```

---

## P1 — 核心功能修复（已完成）

### P1-1: `exec_python` 沙箱偶发无输出

**根因** ([code_exec.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py)):

`_SANDBOX_RUNNER` 使用 `contextlib.redirect_stdout(stdout_buf)` 将用户 `print()` 输出全部捕获到内存 `StringIO`，仅在 `finally` 块中通过 `__SANDBOX_RESULT__` 标记一次性写回管道。

问题：当用户代码进入死循环或长时间阻塞时，子进程被父进程超时强杀（`taskkill /F /T`），`finally` 块未执行，`stdout_buf` 内存随进程消失，父进程收到空 stdout。

**修复 — TeeStream 双写机制**:

```python
class _TeeStream:
    """同时写入内存缓冲 (供 JSON 结果) 与真实管道 (供父进程实时读取)"""
    def write(self, s):
        self._buf.write(s)        # 内存缓冲 (供 JSON)
        self._real.write(s)       # 真实管道 (父进程可实时读取)
        self._real.flush()
```

- `print()` 输出实时流到管道，即使子进程被强杀，父进程也能拿到已产生的部分输出
- `finally` 块仍写入 `__SANDBOX_RESULT__` JSON（含完整 `stdout_buf` 内容）供正常路径解析
- 超时路径的父进程 `_kill_process_tree` + 二次 `communicate(timeout=5)` 现在能读到非空的部分输出

**验证**: 5 项手动测试全部通过（正常执行 / 异常 / 多次 print / 语法错误 / 超时死循环）

**注意**: `tests/test_code_exec_unit.py` 中 7 个 `TestRunInSubprocess` 测试为**预先存在的失败**（mock `subprocess.run` 但代码用 `subprocess.Popen`），与本次改动无关。`tests/test_sandbox_executor.py` 的 17 个失败也是预先存在的（`SandboxResult.__init__` 缺少 `exit_code` 参数，在 `pycoder/safety/sandbox_executor.py` 中，未改动）。

### P1-2: `shell_run` PowerShell `&&` 兼容性

**结论**: 无需改动。

[shell_translator.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/core/shell_translator.py) 已使用 `; if ($?) { ... }` 语法翻译 `&&`，该语法在 PowerShell 5.x 和 7+ 上均有效。

关键设计决策（已落地）：
- `&&` → `; if ($?) { CMD }` — `$?` 是通用成功标志，对 cmdlet / 别名 / 外部 exe 都有效
- `||` → `; if (-not $?) { CMD }`
- 旧版曾用 `$LASTEXITCODE -eq 0`，但 `$LASTEXITCODE` 只对外部 exe 有效，对 PowerShell 别名（如 `dir=Get-ChildItem`）不设置，已弃用
- `_collapse_windows_ifs` 兼容新旧两种格式的反向还原

无需添加 PowerShell 版本检测 — `if ($?)` 语法是跨版本通用的。

### P1-3: `pipeline.py` mcp_tools 残留引用

**结论**: 无需改动。

[pipeline.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/pipeline.py) 中：
- **无** `mcp_tools` import 语句
- L35 文档字符串 `"""直接调用 V2 引擎 registry，移除对 mcp_tools 间接层的依赖"""` 仅说明设计意图
- `_call_tool` 函数直接调用 `pycoder.bus.protocol.CapabilityCall` + `v2.registry.call()`，已完全脱离 mcp_tools 间接层

其他文件中的 `mcp_tools` 引用（`ws_handler.py`, `ws_handler_v2.py`, 测试文件）是对 `pycoder.server.mcp_tools` 模块的**合法调用**，非残留。

---

## P2 — 测试基础设施优化（已完成）

### P2-1: 激活 pytest-timeout + pytest-xdist 配置

**根因**: `pytest.ini`（最小配置：仅 `testpaths` / `markers`）覆盖了 `pyproject.toml` 中完整的 pytest 配置（含 `--timeout=60` 和 `-n auto`），导致：
- 无单测超时限制 → 单个挂死测试拖垮整个套件
- 无并行执行 → 300+ 测试串行运行，总时长 > 300s

**修复**: 删除 `pytest.ini`，激活 [pyproject.toml](file:///c:/Users/Administrator/Desktop/pycode/pyproject.toml) 中已有的配置：

```toml
[tool.pytest.ini_options]
addopts = [
    "--timeout=60",         # 单测超时 60s
    "-n", "auto",           # pytest-xdist 并行（按 CPU 核数）
    "--tb=short",
    "--durations=10",
]
markers = [
    "slow: 慢测试",
    "integration: 集成测试",
    "network: 需要网络连接",
    "windows: 仅 Windows",
    "posix: 仅 POSIX",
]
```

**CI 分片策略**（已在 pyproject.toml 注释中记录）:
1. 本地开发: 默认配置（并行 + 60s 超时）
2. CI 快速门禁: `pytest -m "not slow"`
3. CI 完整分片: 按 marker 拆分多个并行 job
   - shard-1: `pytest -m "not slow and not integration" tests/core/`
   - shard-2: `pytest -m "not slow and not integration" tests/server/`
   - shard-3: `pytest -m "slow"`
   - shard-4: `pytest -m "integration"`

---

## P3 — 大型功能架构方案（待实施）

> 以下 4 项是对标 Cursor / Claude Code / Copilot 的大型功能，仅提供架构方案，不在本次实施。

### P3-1: 实时协作（Yjs CRDT）

**目标**: 多用户同时编辑同一项目/文件，光标共享，变更实时同步。

**架构方案**:

```
┌─────────────┐     WebSocket      ┌──────────────────┐
│  Client A   │ ◄──────────────────►│                  │
│  (Monaco +  │                    │  Yjs Server      │
│   y-monaco) │                    │  (ypy-yjs +      │
└─────────────┘                    │   y-websocket)   │
                                   │                  │
┌─────────────┐     WebSocket      │  ┌────────────┐  │
│  Client B   │ ◄──────────────────►│  │ Awareness  │  │
│  (Monaco +  │                    │  │ (光标/选区  │  │
│   y-monaco) │                    │  │  /用户列表) │  │
└─────────────┘                    │  └────────────┘  │
                                   └──────────────────┘
                                            │
                                            ▼
                                   ┌──────────────────┐
                                   │  持久化层         │
                                   │  (SQLite/Redis   │
                                   │   Yjs Doc 快照)   │
                                   └──────────────────┘
```

**技术选型**:
- 前端: `yjs` + `y-monaco` + `y-websocket` (npm)
- 后端: `ypy-yjs` (Python Yjs 服务端) 或 `y-websocket` (Node.js 服务端 + Python 桥接)
- 协议: WebSocket（复用现有 `ws_handler.py` 基础设施）
- 持久化: 定期快照 Yjs Doc 到 SQLite（每 30s 或 100 次变更）

**实施阶段**:
1. **Phase 1 — MVP**: 单文件协同编辑（Yjs Doc per file），光标共享，无冲突合并
2. **Phase 2 — 多文件**: 项目级 Awareness（文件树同步、活跃文件指示）
3. **Phase 3 — 权限**: 只读/可编辑权限控制，审计日志

**项目内存提示**: 已有 `realtime_collab.py` 初步实现，需评估是否可复用。

### P3-2: GUI 编辑器（Monaco Editor 集成）

**目标**: 在 PyCoder Web 界面中嵌入 VS Code 级别的代码编辑器。

**架构方案**:

```
┌────────────────────────────────────────────────────┐
│                  Web UI (React)                     │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────┐ │
│  │ 文件树    │  │ Monaco Editor    │  │ AI 面板  │ │
│  │ (Tree)   │  │ ┌──────────────┐ │  │ (Chat +  │ │
│  │          │  │ │ 代码编辑区    │ │  │  Diff    │ │
│  │          │  │ │ (语法高亮/    │ │  │  View)   │ │
│  │          │  │ │  IntelliSense)│ │  │          │ │
│  │          │  │ └──────────────┘ │  │          │ │
│  └──────────┘  └──────────────────┘  └──────────┘ │
└────────────────────────────────────────────────────┘
         │              │                │
         ▼              ▼                ▼
┌────────────────────────────────────────────────────┐
│              FastAPI Backend                         │
│  /api/files/* (CRUD)  /api/code/exec  /api/ai/chat  │
└────────────────────────────────────────────────────┘
```

**技术选型**:
- 编辑器: `@monaco-editor/react` (Monaco Editor 的 React 封装)
- 文件树: `react-arborist` 或自实现
- Diff View: Monaco `DiffEditor` 组件
- 语言服务: Monaco 内置 TS/JS/JSON；Python 通过 `monaco-languageclient` + `pylsp` 

**实施阶段**:
1. **Phase 1 — 基础编辑**: Monaco 集成，文件树，读写文件，语法高亮
2. **Phase 2 — AI 集成**: inline 补全（Ghost Text），Diff View 接受/拒绝 AI 建议
3. **Phase 3 — LSP**: Python IntelliSense（通过 pylsp WebSocket）

### P3-3: 语音输入（Web Speech API）

**目标**: 用户通过语音输入指令/代码，支持中英文。

**架构方案**:

```
┌─────────────────────────────────────────┐
│              Web UI (React)              │
│  ┌─────────────┐    ┌─────────────────┐ │
│  │ 麦克风按钮   │───►│ SpeechRecognition│ │
│  │ (录音状态    │    │ (Web Speech API)│ │
│  │  动画)       │    │                  │ │
│  └─────────────┘    └────────┬─────────┘ │
│                              ▼            │
│                    ┌─────────────────┐   │
│                    │ 文本输出区       │   │
│                    │ (实时转写 +      │   │
│                    │  指令解析)       │   │
│                    └────────┬─────────┘   │
└─────────────────────────────┼─────────────┘
                              ▼
┌─────────────────────────────────────────┐
│            FastAPI Backend               │
│  /api/voice/parse (自然语言 → 指令映射)   │
└─────────────────────────────────────────┘
```

**技术选型**:
- 前端: `SpeechRecognition` API（Chrome/Edge 原生支持）；Safari 用 `webkitSpeechRecognition`
- 后备方案: `MediaRecorder` + Whisper API（Firefox 不支持 Web Speech API 时）
- 指令解析: 现有 AI agent 的自然语言理解能力

**实施阶段**:
1. **Phase 1 — 听写**: 语音 → 文本 → 插入编辑器光标位置
2. **Phase 2 — 指令**: 语音指令（"运行代码"、"保存文件"、"打开终端"）
3. **Phase 3 — 代码生成**: 语音描述 → AI 生成代码 → Diff View

**项目内存提示**: 已有 `voiceInput.ts` 初步实现（Web Speech API），需评估是否可复用。

### P3-4: 移动端适配

**目标**: PyCoder Web 界面在手机/平板上可用，支持触摸操作。

**架构方案**:

```
┌─────────────────────┐  ┌─────────────────────┐
│   Desktop (>=1024px) │  │   Mobile (<768px)   │
│                       │  │                       │
│  ┌─────┬─────┬────┐  │  │  ┌───────────────┐  │
│  │文件树│编辑器│ AI │  │  │  │ Tab 切换栏     │  │
│  │     │     │面板│  │  │  │ [文件][编辑][AI]│  │
│  │     │     │    │  │  │  ├───────────────┤  │
│  │     │     │    │  │  │  │ 当前活动面板   │  │
│  │     │     │    │  │  │  │ (全屏)         │  │
│  └─────┴─────┴────┘  │  │  └───────────────┘  │
└─────────────────────┘  └─────────────────────┘
```

**技术选型**:
- 响应式: CSS `@media` + CSS Grid/Flexbox（不引入额外 UI 框架，保持轻量）
- 触摸: `touch-action` + `pointer events`（统一鼠标/触摸）
- 移动编辑器: Monaco 在小屏幕上性能差，降级为 `CodeMirror 6`（更轻量）
- 离线: PWA（Service Worker 缓存静态资源）

**实施阶段**:
1. **Phase 1 — 响应式布局**: 三栏 → 单栏 Tab 切换，触摸友好按钮
2. **Phase 2 — 移动编辑器**: CodeMirror 6 替换 Monaco（屏幕 < 768px 时）
3. **Phase 3 — PWA**: 离线访问，Add to Home Screen

---

## 验收标准与后续行动

### 已完成项验收

| 项目 | 验收方法 | 结果 |
|------|----------|------|
| P0-2 template_code | `pytest tests/test_template_code_coverage.py tests/test_runner.py` | ✅ 27 passed |
| P0-3 gitignore | `git ls-files data/skills/` 不含 db-shm/db-wal | ✅ |
| P1-1 沙箱 TeeStream | 手动测试 5 场景（正常/异常/多print/语法错误/超时） | ✅ 全部通过 |
| P1-2 shell_translator | 代码审查确认 `if ($?)` 语法 | ✅ 无需改动 |
| P1-3 pipeline.py | 代码审查确认无 mcp_tools import | ✅ 无需改动 |
| P2-1 pytest 配置 | `pytest --collect-only` 确认使用 pyproject.toml | ✅ |

### 后续行动（P3）

1. **实时协作**: 评估现有 `realtime_collab.py`，确定 Yjs 服务端方案（ypy-yjs vs y-websocket）
2. **GUI 编辑器**: 选定 Monaco vs CodeMirror，设计文件系统 API
3. **语音输入**: 评估现有 `voiceInput.ts`，确定浏览器兼容性策略
4. **移动端**: 确定是否引入响应式框架或纯 CSS 实现

### 已知的预先存在问题（不在本次范围）

- `tests/test_sandbox_executor.py` (17 失败): `SandboxResult.__init__()` 缺少 `exit_code` 参数 — 需修复 `pycoder/safety/sandbox_executor.py`
- `tests/test_code_exec_unit.py` (7 失败): mock `subprocess.run` 但代码用 `subprocess.Popen` — 需更新测试 mock 目标
- 测试覆盖率: 当前未达 90% 目标，需补充测试

---

*文档生成: 2026-08-03 | 执行人: AI Agent (GLM-5.2)*

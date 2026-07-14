# P1 阶段修复计划：架构优化

> **优先级**：HIGH — 架构与代码质量改进
> **工期**：2-4 周
> **目标**：拆解上帝对象，迁移工具调用至 JSON Schema，消除裸 except，引入 Clean Architecture
> **前置条件**：P0 阶段全部完成并通过验收

---

## 修复清单总览

| ID | 问题 | 严重度 | 文件 | 工期 |
|----|------|--------|------|------|
| P1-1 | TeamOrchestrator 上帝对象 | MEDIUM | team_orchestrator.py | 5-7 天 |
| P1-2 | 工具调用 XML 解析路径迁移 JSON Schema | HIGH | agent_tools.py | 3-4 天 |
| P1-3 | 消除所有裸 except Exception | HIGH | 多文件 | 2-3 天 |
| P1-4 | 引入 Clean Architecture 分层 | MEDIUM | 全局重构 | 7-10 天 |
| P1-5 | 完善 Agent 执行链路（ReAct 循环） | MEDIUM | agent_orchestrator.py | 4-5 天 |

---

## P1-1：拆分 TeamOrchestrator 上帝对象

### 问题分析

[team_orchestrator.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/team_orchestrator.py) 单文件承担了过多职责：
- 会话生命周期管理（创建/销毁/查询）
- 任务调度（分发/聚合/重试）
- Agent 角色编排（PM/Architect/Developer/QA/DevOps）
- 审查与质量守卫
- WebSocket 事件广播

违背单一职责原则，扩展性差，测试困难。

### 修复方案

按职责拆分为 3 个独立 Orchestrator + 1 个协调器：

```
pycoder/server/services/team/
├── __init__.py              # 导出公共接口
├── session_orchestrator.py  # 会话生命周期管理
├── job_orchestrator.py      # 任务调度与聚合
├── review_orchestrator.py    # 审查与质量守卫
└── team_coordinator.py      # 协调三者，对外门面
```

#### 文件 1：session_orchestrator.py

```python
"""会话生命周期管理 — 创建、查询、销毁团队会话"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class TeamSession:
    session_id: str
    name: str
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "active"  # active / completed / cancelled / failed
    members: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class SessionOrchestrator:
    """会话生命周期管理"""

    def __init__(self) -> None:
        self._sessions: dict[str, TeamSession] = {}

    def create_session(self, name: str, members: list[str] | None = None) -> TeamSession:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        session = TeamSession(
            session_id=session_id,
            name=name,
            members=members or [],
        )
        self._sessions[session_id] = session
        logger.info("session_created", session_id=session_id, name=name)
        return session

    def get_session(self, session_id: str) -> Optional[TeamSession]:
        return self._sessions.get(session_id)

    def list_sessions(self, status: str | None = None) -> list[TeamSession]:
        if status:
            return [s for s in self._sessions.values() if s.status == status]
        return list(self._sessions.values())

    def close_session(self, session_id: str, status: str = "completed") -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.status = status
        logger.info("session_closed", session_id=session_id, status=status)
        return True
```

#### 文件 2：job_orchestrator.py

```python
"""任务调度 — 分发、聚合、重试"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any
import asyncio
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class Job:
    job_id: str
    session_id: str
    title: str
    description: str
    assignee: str = ""  # agent role
    status: str = "pending"  # pending / running / done / failed
    result: Any = None
    retries: int = 0
    max_retries: int = 3


class JobOrchestrator:
    """任务调度与聚合"""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create_job(self, session_id: str, title: str, description: str, assignee: str = "") -> Job:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = Job(
            job_id=job_id, session_id=session_id, title=title,
            description=description, assignee=assignee,
        )
        self._jobs[job_id] = job
        return job

    async def execute_parallel(self, jobs: list[Job], executor) -> list[Job]:
        """并行执行多个任务"""
        async def _run(job: Job) -> Job:
            try:
                job.status = "running"
                job.result = await executor(job)
                job.status = "done"
            except Exception as e:
                job.status = "failed"
                job.result = str(e)
                logger.exception("job_failed", job_id=job.job_id)
            return job

        return await asyncio.gather(*[_run(j) for j in jobs])

    def get_session_jobs(self, session_id: str, status: str | None = None) -> list[Job]:
        jobs = [j for j in self._jobs.values() if j.session_id == session_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs
```

#### 文件 3：review_orchestrator.py

```python
"""审查与质量守卫 — 代码审查、测试验证、质量评分"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class ReviewResult:
    job_id: str
    passed: bool
    score: float
    issues: list[str]
    suggestions: list[str]


class ReviewOrchestrator:
    """审查与质量守卫"""

    async def review_code(self, job_id: str, code: str) -> ReviewResult:
        """代码审查"""
        issues: list[str] = []
        suggestions: list[str] = []

        # 静态分析（调用 P0-3 修复后的 _static_scan_async）
        # ...

        # AI 审查（可选）
        # ...

        passed = len(issues) == 0
        score = max(0.0, 1.0 - 0.1 * len(issues))
        return ReviewResult(
            job_id=job_id, passed=passed, score=score,
            issues=issues, suggestions=suggestions,
        )

    async def run_tests(self, job_id: str) -> ReviewResult:
        """测试验证"""
        # 调用 self_evolution._run_tests_async
        # ...
        return ReviewResult(...)
```

#### 文件 4：team_coordinator.py

```python
"""团队协调器 — 对外门面，组合三个 Orchestrator"""
from __future__ import annotations
from .session_orchestrator import SessionOrchestrator
from .job_orchestrator import JobOrchestrator
from .review_orchestrator import ReviewOrchestrator


class TeamCoordinator:
    """对外门面 — 替代原 TeamOrchestrator 的对外接口"""

    def __init__(self) -> None:
        self.sessions = SessionOrchestrator()
        self.jobs = JobOrchestrator()
        self.reviews = ReviewOrchestrator()

    async def run_team_task(
        self, name: str, task_title: str, task_desc: str, members: list[str]
    ):
        """端到端团队任务执行"""
        session = self.sessions.create_session(name=name, members=members)
        job = self.jobs.create_job(
            session_id=session.session_id, title=task_title, description=task_desc,
        )
        # 调度 + 执行 + 审查
        # ...
        return job
```

### 迁移策略

**渐进式迁移，避免一次性破坏**：

1. 创建新目录 `pycoder/server/services/team/` 与 4 个文件
2. 在 [team_orchestrator.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/team_orchestrator.py) 顶部添加废弃标记，保留原实现
3. 新代码使用 `TeamCoordinator`，旧代码逐步迁移
4. 路由层 `team_api.py` 改为依赖 `TeamCoordinator`
5. 全部迁移完成后删除旧 `team_orchestrator.py`

### 测试方案

```python
# tests/test_team_orchestrator_split.py
import pytest
from pycoder.server.services.team import TeamCoordinator, TeamSession, Job


class TestSessionOrchestrator:
    def test_create_session(self):
        coord = TeamCoordinator()
        session = coord.sessions.create_session(name="test", members=["dev"])
        assert session.session_id.startswith("sess-")
        assert session.status == "active"

    def test_close_session(self):
        coord = TeamCoordinator()
        session = coord.sessions.create_session(name="test")
        assert coord.sessions.close_session(session.session_id, "completed")
        assert coord.sessions.get_session(session.session_id).status == "completed"


class TestJobOrchestrator:
    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        coord = TeamCoordinator()
        session = coord.sessions.create_session(name="test")

        async def executor(job):
            return f"result-{job.job_id}"

        jobs = [
            coord.jobs.create_job(session.session_id, f"task-{i}", "desc")
            for i in range(3)
        ]
        results = await coord.jobs.execute_parallel(jobs, executor)
        assert all(j.status == "done" for j in results)
```

### 回滚策略

- 新代码与旧代码并存，失败时直接弃用新代码
- 旧 `team_orchestrator.py` 在 P1 结束前不删除
- 路由层保留 fallback：若 `TeamCoordinator` 不可用，回退到旧实现

### 风险评估

- **风险**：高 — 拆分过程中可能遗漏职责
- **缓解**：保留旧实现作为参考与 fallback
- **工期**：5-7 天（含测试）

---

## P1-2：工具调用完全迁移至 JSON Schema

### 问题分析

[agent_tools.py:L243-L279](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/agent_tools.py#L243-L279) 中 `parse_tool_calls` 同时支持：
- Markdown JSON 代码块（L247-L262）
- 纯 JSON（部分路径）
- XML 标签 `<tool name="...">` / `<parameter name="...">`（L264-L277）

**XML 路径的脆弱性**：
- 使用正则匹配 XML 标签，LLM 输出格式偏差（多空格、属性顺序变化、嵌套引号）即失败
- 与项目记忆中"应改用 JSON Schema"的约束冲突
- 当前未做 JSON Schema 校验，仅 `json.loads` 后取 `tool_calls` 字段

### 修复方案

#### 步骤 1：定义工具调用 JSON Schema

```python
# pycoder/server/services/tool_schema.py
"""工具调用 JSON Schema 定义与校验"""
from __future__ import annotations
from jsonschema import validate, ValidationError
from typing import Any

# 单个工具调用的 Schema
TOOL_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "params": {"type": "object"},
    },
    "required": ["name", "params"],
    "additionalProperties": False,
}

# 完整响应的 Schema（LLM 应输出此格式）
TOOL_CALLS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_calls": {
            "type": "array",
            "items": TOOL_CALL_SCHEMA,
        },
        "thought": {"type": "string"},  # 可选：LLM 的思考过程
    },
    "required": ["tool_calls"],
    "additionalProperties": False,
}


def validate_tool_calls(data: dict) -> list[dict]:
    """校验工具调用响应，返回标准化的 tool_calls 列表

    Raises:
        ValueError: 校验失败时
    """
    try:
        validate(instance=data, schema=TOOL_CALLS_RESPONSE_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"工具调用格式校验失败: {e.message}") from e

    calls = data["tool_calls"]
    # 逐个校验
    for call in calls:
        try:
            validate(instance=call, schema=TOOL_CALL_SCHEMA)
        except ValidationError as e:
            raise ValueError(f"工具调用 {call.get('name', '?')} 格式无效: {e.message}") from e

    return calls


def build_tool_calls_json(name: str, params: dict) -> dict:
    """构建单个工具调用 JSON"""
    return {"name": name, "params": params}
```

#### 步骤 2：重写 parse_tool_calls

```python
# pycoder/server/services/agent_tools.py — 修改 parse_tool_calls

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_tool_calls(text: str) -> list[dict]:
    """从 LLM 输出中解析工具调用

    策略（按优先级）：
        1. Markdown ```json ... ``` 代码块 → json.loads + JSON Schema 校验
        2. 裸 JSON 对象（含 tool_calls 字段）
        3. 失败：返回空列表

    已废弃：XML 标签解析路径（脆弱，已移除）
    """
    if not text or not text.strip():
        return []

    # 策略 1：Markdown JSON 代码块
    json_block_pattern = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)
    for match in json_block_pattern.finditer(text):
        json_str = match.group(1).strip()
        calls = _try_parse_json_calls(json_str)
        if calls:
            return calls

    # 策略 2：裸 JSON 对象
    # 寻找第一个 { 与最后一个 }，尝试解析
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        json_str = text[first_brace:last_brace + 1]
        calls = _try_parse_json_calls(json_str)
        if calls:
            return calls

    logger.debug("no_tool_calls_parsed", text_preview=text[:200])
    return []


def _try_parse_json_calls(json_str: str) -> list[dict]:
    """尝试解析 JSON 并通过 Schema 校验"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.debug("json_parse_failed", error=str(e))
        return []

    if not isinstance(data, dict):
        return []

    # 兼容：LLM 可能直接返回单个工具调用 {"name": "...", "params": {...}}
    if "name" in data and "params" in data and "tool_calls" not in data:
        data = {"tool_calls": [data]}

    try:
        from pycoder.server.services.tool_schema import validate_tool_calls
        return validate_tool_calls(data)
    except ValueError as e:
        logger.warning("tool_calls_validation_failed", error=str(e))
        return []
```

#### 步骤 3：更新 Agent 系统提示词

确保提示词明确要求 JSON 格式输出（详见 P2-2 提示词优化）：

```
当你需要调用工具时，必须以如下 JSON 格式输出（包含在 ```json 代码块中）：

```json
{
  "thought": "分析当前情况，决定调用 xxx 工具",
  "tool_calls": [
    {"name": "tool_name", "params": {"key": "value"}}
  ]
}
```

禁止使用 XML 标签格式（如 <tool name="...">）。仅支持 JSON。
```

#### 步骤 4：保留 XML 兼容（可选，标记废弃）

```python
def parse_tool_calls_legacy_xml(text: str) -> list[dict]:
    """[已废弃] XML 标签解析路径

    仅为向后兼容保留，新代码不应使用。
    将在 v2.0 移除。
    """
    import warnings
    warnings.warn(
        "XML 工具调用解析已废弃，请使用 JSON 格式",
        DeprecationWarning, stacklevel=2,
    )
    # ... 原 XML 解析逻辑保留
```

### 测试方案

```python
# tests/test_tool_calls_parsing.py
import pytest
from pycoder.server.services.agent_tools import parse_tool_calls


class TestParseToolCalls:
    def test_markdown_json_block(self):
        text = '''Thought...
```json
{"tool_calls": [{"name": "read_file", "params": {"path": "/tmp/x"}}]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["params"]["path"] == "/tmp/x"

    def test_bare_json(self):
        text = '{"tool_calls": [{"name": "ls", "params": {}}]}'
        calls = parse_tool_calls(text)
        assert len(calls) == 1

    def test_single_tool_call_without_wrapper(self):
        """LLM 直接返回单个工具调用"""
        text = '{"name": "ls", "params": {}}'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_empty_text(self):
        assert parse_tool_calls("") == []
        assert parse_tool_calls("no json here") == []

    def test_invalid_json_returns_empty(self):
        assert parse_tool_calls("```json\n{invalid\n```") == []

    def test_schema_validation_rejects_missing_name(self):
        text = '```json\n{"tool_calls": [{"params": {}}]}\n```'
        calls = parse_tool_calls(text)
        assert calls == []  # 校验失败，返回空

    def test_xml_format_no_longer_supported(self):
        """XML 格式不再被解析"""
        text = '<tool name="ls"><parameter name="path">/tmp</parameter></tool>'
        calls = parse_tool_calls(text)
        assert calls == []
```

### 回滚策略

- 保留 `parse_tool_calls_legacy_xml` 函数，必要时可临时恢复 XML 支持
- 修改前 `git checkout -b fix/p1-2-json-schema`

### 风险评估

- **风险**：中 — 旧版 Agent 提示词可能仍输出 XML
- **缓解**：P2-2 同步更新提示词，并在 `parse_tool_calls` 失败时返回友好错误提示

---

## P1-3：消除所有裸 except Exception

### 问题分析

报告中多处发现裸 `except Exception` 或 `except Exception as e:` 后仅 `pass` 或简单 `return`：

| 文件 | 行号 | 当前代码 |
|------|------|----------|
| [app.py:L71](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L71) | L241 | `except Exception as e: return {"error": str(e)}` |
| [chat_handler.py:L82](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/chat_handler.py#L82) | L82 | `except Exception: pass` |
| [agent_orchestrator.py:L105](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/agent_orchestrator.py#L105) | L105 | `except Exception as e: ...` |
| [self_evolution.py:L331](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L331) | L331 | `except Exception: pass` |
| [self_evolution.py:L453](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L453) | L453 | `except Exception: pass` |
| [self_evolution.py:L600](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L600) | L600 | `except Exception: pass` |

### 修复方案

**原则**：
1. 捕获具体异常类型（如 `FileNotFoundError`、`json.JSONDecodeError`、`asyncio.TimeoutError`）
2. 无法确定具体类型时，至少记录日志 + 上下文信息
3. 不再使用 `except Exception: pass`（吞掉所有异常）

#### 模式 A：吞异常 → 改为日志记录

```python
# ── 修改前 ──────────────────────────────────────────────
try:
    content = f.read_text(encoding="utf-8")
except Exception:
    pass


# ── 修改后 ──────────────────────────────────────────────
import logging
logger = logging.getLogger(__name__)

try:
    content = f.read_text(encoding="utf-8")
except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
    logger.warning("file_read_failed", file=str(f), error=str(e))
    content = ""
```

#### 模式 B：catch-all → 改为具体异常

```python
# ── 修改前 ──────────────────────────────────────────────
try:
    result = await bridge.chat_stream(prompt)
except Exception as e:
    yield {"type": "error", "message": str(e)}


# ── 修改后 ──────────────────────────────────────────────
try:
    result = await bridge.chat_stream(prompt)
except asyncio.TimeoutError:
    yield {"type": "error", "message": "LLM 响应超时"}
except ConnectionError as e:
    yield {"type": "error", "message": f"LLM 连接失败: {e}"}
except json.JSONDecodeError as e:
    yield {"type": "error", "message": f"LLM 响应解析失败: {e}"}
```

#### 模式 C：必须 catch-all 时（如 WebSocket 错误边界）

```python
# ── 修改前 ──────────────────────────────────────────────
try:
    await handle_message(msg)
except Exception:
    pass  # ❌ 完全吞掉


# ── 修改后 ──────────────────────────────────────────────
try:
    await handle_message(msg)
except Exception as e:
    # 边界层最后兜底，但必须记录
    logger.exception("message_handler_failed", msg_preview=str(msg)[:200])
    await ws.send_json({"type": "error", "message": f"内部错误: {e}"})
```

### 修复清单（按文件）

需要逐个修改以下位置（每处单独 commit）：

1. [app.py:L241](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L241) — `list_skills` 的 except
2. [chat_handler.py:L82](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/chat_handler.py#L82)
3. [agent_orchestrator.py:L105](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/agent_orchestrator.py#L105)
4. [self_evolution.py:L331](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L331)
5. [self_evolution.py:L453](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L453)
6. [self_evolution.py:L600](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L600)
7. [self_evolution.py:L747](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L747) — ruff 失败
8. [self_evolution.py:L766](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L766) — pyflakes 失败

### 测试方案

```python
# tests/test_no_bare_except.py
"""扫描代码，确保无裸 except Exception: pass"""
import re
import pathlib
import pytest


BARE_EXCEPT_PATTERN = re.compile(
    r'except\s+Exception(\s+as\s+\w+)?\s*:\s*\n\s*pass',
    re.MULTILINE,
)


@pytest.mark.parametrize("file_path", [
    "pycoder/server/app.py",
    "pycoder/server/chat_handler.py",
    "pycoder/server/services/agent_orchestrator.py",
    "pycoder/server/self_evolution.py",
])
def test_no_bare_except_pass(file_path):
    """关键文件中不应有 except Exception: pass"""
    content = pathlib.Path(file_path).read_text(encoding="utf-8")
    matches = BARE_EXCEPT_PATTERN.findall(content)
    assert not matches, f"{file_path} 中仍存在 except Exception: pass"
```

### 回滚策略

- 每处修改单独 commit，失败时精确 revert
- 不改变函数签名与返回值，仅改异常处理

### 风险评估

- **风险**：低 — 仅改异常处理逻辑，不改业务流程
- **缓解**：保留必要的 catch-all 边界层兜底，但加日志

---

## P1-4：引入 Clean Architecture 分层

### 问题分析

当前路由层直接调用服务层，服务层直接调用 LLM Bridge / 文件系统，耦合严重，难以测试。

### 修复方案（高层规划，详细设计在 P1-4 子文档）

```
pycoder/
├── core/                    # 核心业务逻辑（无 IO 依赖）
│   ├── agent/               # Agent 编排逻辑（纯函数）
│   ├── evolution/           # 自演化逻辑（纯函数）
│   └── team/                # 团队协作逻辑
├── interfaces/              # 接口层（适配外部）
│   ├── api/                 # REST API 路由
│   ├── websocket/           # WebSocket 处理
│   └── cli/                 # CLI 命令
└── external/                # 外部层（具体实现）
    ├── llm/                 # LLM Provider 实现
    ├── storage/             # 文件系统 / DB 实现
    └── sandbox/             # 代码沙箱实现
```

**依赖方向**：`interfaces → core ← external`（core 不依赖任何具体实现）

### 实施步骤（P1-4 阶段）

1. **定义核心接口（Protocol）**：`LLMProvider`、`CodeSandbox`、`FileSystem`
2. **抽取 core 模块**：将 agent_orchestrator、self_evolution 的核心逻辑迁移至 `pycoder/core/`
3. **实现适配器**：在 `external/` 中实现具体适配器（`BridgeLLMProvider`、`SubprocessSandbox`）
4. **路由层改依赖注入**：通过 FastAPI `Depends()` 注入接口，而非直接 import 实现

### 风险评估

- **风险**：高 — 大规模重构
- **缓解**：分步进行，先抽取 1-2 个核心模块验证模式
- **工期**：7-10 天

---

## P1-5：完善 Agent 执行链路（ReAct 循环）

### 问题分析

当前 Agent 执行模式是"单轮工具调用"：LLM 输出 → 解析工具调用 → 执行 → 返回结果。缺少：
- **ReAct 循环**：观察工具结果后继续推理
- **Plan-Execute 模式**：先制定计划再分步执行
- **能力驱动任务分配**：根据 Agent 能力动态分配

### 修复方案

```python
# pycoder/server/services/agent_react_loop.py
"""ReAct (Reasoning + Acting) 循环实现"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReActStep:
    thought: str
    action: str  # tool name
    action_input: dict
    observation: str = ""


class ReActLoop:
    """ReAct 循环：思考 → 行动 → 观察 → 思考..."""

    def __init__(self, llm_provider, tool_executor, max_iterations: int = 15):
        self.llm = llm_provider
        self.tools = tool_executor
        self.max_iterations = max_iterations

    async def run(self, task: str, context: str = "") -> str:
        """执行 ReAct 循环直到完成或达到上限"""
        steps: list[ReActStep] = []
        current_context = context

        for i in range(self.max_iterations):
            # 1. 思考 + 选择工具
            llm_output = await self.llm.generate(
                self._build_react_prompt(task, steps, current_context)
            )
            thought, action, action_input = self._parse_react_step(llm_output)

            if action == "FINISH":
                return thought  # 最终答案

            # 2. 执行工具
            try:
                observation = await self.tools.execute(action, action_input)
            except Exception as e:
                observation = f"工具执行失败: {e}"

            # 3. 记录步骤
            step = ReActStep(
                thought=thought, action=action,
                action_input=action_input, observation=str(observation),
            )
            steps.append(step)
            current_context += f"\n{observation}"

        return "达到最大迭代次数，未能完成任务"

    def _build_react_prompt(self, task, steps, context):
        # ... 构建提示词
        ...

    def _parse_react_step(self, output):
        # ... 解析 LLM 输出
        ...
```

### 测试方案

```python
# tests/test_react_loop.py
@pytest.mark.asyncio
async def test_react_loop_terminates_on_finish():
    llm = MockLLM(responses=[
        'Thought: done\nAction: FINISH\nAction Input: {}',
    ])
    loop = ReActLoop(llm, MockToolExecutor())
    result = await loop.run("test task")
    assert "done" in result


@pytest.mark.asyncio
async def test_react_loop_observes_and_continues():
    """验证工具结果能反馈到下一轮推理"""
    ...
```

### 风险评估

- **风险**：中 — 需配合 P2-2 提示词优化
- **工期**：4-5 天

---

## P1 阶段验收清单

### 架构验收

- [ ] TeamOrchestrator 已拆分为 3 个独立 Orchestrator
- [ ] 旧 team_orchestrator.py 已标记废弃或删除
- [ ] 工具调用 XML 解析路径已移除
- [ ] 所有裸 `except Exception: pass` 已消除
- [ ] 核心业务逻辑与外部实现已分离（Clean Architecture）

### 功能验收

- [ ] 团队任务创建 → 调度 → 审查全流程正常
- [ ] Agent 工具调用通过 JSON 格式正常工作
- [ ] ReAct 循环能根据工具观察继续推理
- [ ] 异常处理不影响主流程

### 测试验收

- [ ] `pytest tests/test_team_orchestrator_split.py` 通过
- [ ] `pytest tests/test_tool_calls_parsing.py` 通过
- [ ] `pytest tests/test_no_bare_except.py` 通过
- [ ] `pytest tests/test_react_loop.py` 通过
- [ ] 整体测试覆盖率 ≥ 75%

### 重审验收

- [ ] 综合评分 ≥ 82 分
- [ ] HIGH 问题数 ≤ 2
- [ ] MEDIUM 问题数 ≤ 5

---

**下一步**：P0 通过验收后，请审阅本 P1 修复计划并确认实施顺序。

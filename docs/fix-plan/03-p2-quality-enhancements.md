# P2 阶段修复计划：质量提升

> **优先级**：MEDIUM — 长期质量与可维护性改进
> **工期**：4-6 周
> **目标**：测试覆盖率 ≥ 80%，完善学习闭环、提示词工程与成本控制
> **前置条件**：P0、P1 阶段全部完成并通过验收

---

## 修复清单总览

| ID | 问题 | 严重度 | 文件 | 工期 |
|----|------|--------|------|------|
| P2-1 | 测试覆盖率不足（目标 ≥ 80%） | MEDIUM | tests/ | 7-10 天 |
| P2-2 | 提示词工程优化 | MEDIUM | prompts/ | 4-5 天 |
| P2-3 | 学习系统反馈闭环完善 | MEDIUM | learning/ | 5-7 天 |
| P2-4 | 成本熔断与 Token 预算控制 | LOW | chat_bridge | 3-4 天 |
| P2-5 | CI/CD 安全扫描与回归防护 | MEDIUM | .github/workflows | 2-3 天 |

---

## P2-1：补充测试覆盖率至 80%

### 问题分析

当前测试覆盖率不足，关键模块（self_evolution、team_orchestrator、agent_orchestrator）缺乏单元测试。

### 测试覆盖目标

| 模块 | 当前覆盖率 | 目标覆盖率 | 优先级 |
|------|------------|------------|--------|
| `pycoder/server/self_evolution.py` | 未知 | ≥ 85% | 高（核心逻辑） |
| `pycoder/server/services/team_orchestrator.py` | 未知 | ≥ 80% | 高 |
| `pycoder/server/services/agent_orchestrator.py` | 未知 | ≥ 80% | 高 |
| `pycoder/server/services/agent_tools.py` | 未知 | ≥ 90% | 高（解析逻辑） |
| `pycoder/server/routers/code_exec.py` | 未知 | ≥ 85% | 中 |
| `pycoder/server/routers/files.py` | 未知 | ≥ 80% | 中 |
| 其他模块 | 未知 | ≥ 75% | 低 |

### 测试目录结构

```
tests/
├── unit/                         # 单元测试
│   ├── test_self_evolution.py
│   ├── test_team_orchestrator.py
│   ├── test_agent_orchestrator.py
│   ├── test_agent_tools.py
│   ├── test_permission_policy.py
│   └── test_tool_schema.py
├── integration/                  # 集成测试
│   ├── test_code_exec_flow.py
│   ├── test_evolution_flow.py
│   ├── test_team_flow.py
│   └── test_api_auth_flow.py
├── security/                     # 安全测试
│   ├── test_sandbox_isolation.py
│   ├── test_path_traversal.py
│   ├── test_command_injection.py
│   └── test_api_auth.py
├── e2e/                          # 端到端测试
│   └── test_full_evolution_cycle.py
└── conftest.py                   # 共享 fixtures
```

### 关键测试用例清单

#### P2-1.1：self_evolution 测试

```python
# tests/unit/test_self_evolution.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pycoder.server.self_evolution import SelfEvolutionEngine, EvolutionTask


class TestSelfEvolutionBackup:
    """备份与恢复机制"""

    def test_git_stash_backup_creates_evobak_files(self, tmp_path):
        """_git_stash_backup 应为所有 .py 文件创建 .evobak"""
        # 准备测试项目结构
        (tmp_path / "pycoder").mkdir()
        (tmp_path / "pycoder" / "test.py").write_text("print('hi')")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        backup_id = engine._git_stash_backup()

        assert backup_id  # 返回非空 ID
        assert (tmp_path / "pycoder" / "test.py.evobak").exists()

    def test_git_stash_pop_restores_files(self, tmp_path):
        """_git_stash_pop 应恢复原始内容"""
        (tmp_path / "pycoder").mkdir()
        original = "print('original')"
        (tmp_path / "pycoder" / "test.py").write_text(original)
        engine = SelfEvolutionEngine(project_root=tmp_path)

        backup_id = engine._git_stash_backup()
        # 修改文件
        (tmp_path / "pycoder" / "test.py").write_text("print('modified')")
        # 恢复
        assert engine._git_stash_pop(backup_id)
        assert (tmp_path / "pycoder" / "test.py").read_text() == original

    def test_fallback_restore_when_manifest_missing(self, tmp_path):
        """清单丢失时降级恢复"""
        (tmp_path / "pycoder").mkdir()
        (tmp_path / "pycoder" / "test.py").write_text("original")
        (tmp_path / "pycoder" / "test.py.evobak").write_text("backup")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        assert engine._fallback_restore_all_evobak()
        assert (tmp_path / "pycoder" / "test.py").read_text() == "backup"


class TestSelfEvolutionApplyFix:
    """_apply_fix 安全检查"""

    def test_rejects_self_modification(self, tmp_path):
        """拒绝修改 self_evolution.py 自身"""
        (tmp_path / "pycoder").mkdir()
        target = tmp_path / "pycoder" / "self_evolution.py"
        target.write_text("# original")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        ok, msg = engine._apply_fix({
            "file": "pycoder/self_evolution.py",
            "modified": "# malicious",
        })
        assert not ok
        assert "拒绝修改自我进化引擎" in msg

    def test_rejects_placeholder_content(self, tmp_path):
        """检测到占位符 '# ... 代码保持不变' 时拒绝"""
        (tmp_path / "pycoder").mkdir()
        (tmp_path / "pycoder" / "test.py").write_text("# original\ncode = 1\n")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        ok, msg = engine._apply_fix({
            "file": "pycoder/test.py",
            "modified": "# ... 代码保持不变\n# placeholder",
        })
        assert not ok
        assert "占位符" in msg

    def test_rejects_syntax_error(self, tmp_path):
        """修改后语法错误应拒绝"""
        (tmp_path / "pycoder").mkdir()
        (tmp_path / "pycoder" / "test.py").write_text("print('ok')\n")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        ok, msg = engine._apply_fix({
            "file": "pycoder/test.py",
            "modified": "def broken(:\n    pass",
        })
        assert not ok
        assert "语法错误" in msg

    def test_rejects_truncated_content(self, tmp_path):
        """内容长度异常缩短应拒绝"""
        (tmp_path / "pycoder").mkdir()
        original = "\n".join(f"line{i}" for i in range(100))
        (tmp_path / "pycoder" / "test.py").write_text(original)
        engine = SelfEvolutionEngine(project_root=tmp_path)

        ok, msg = engine._apply_fix({
            "file": "pycoder/test.py",
            "modified": "only 1 line",  # 100 → 1 行
        })
        assert not ok
        assert "内容长度异常" in msg

    def test_search_replace_mode(self, tmp_path):
        """search/replace 模式应只替换匹配部分"""
        (tmp_path / "pycoder").mkdir()
        (tmp_path / "pycoder" / "test.py").write_text("old_code()\n")
        engine = SelfEvolutionEngine(project_root=tmp_path)

        ok, _ = engine._apply_fix({
            "file": "pycoder/test.py",
            "search": "old_code()",
            "modified": "new_code()",
        })
        assert ok
        assert "new_code()" in (tmp_path / "pycoder" / "test.py").read_text()
```

#### P2-1.2：agent_tools 测试

```python
# tests/unit/test_agent_tools.py
class TestExecuteAgentTool:
    """工具执行入口"""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = await execute_agent_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "unknown" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_tool_timeout_handled(self):
        with patch(...) as mock_tool:
            mock_tool.side_effect = asyncio.TimeoutError()
            result = await execute_agent_tool("slow_tool", {})
            assert result["success"] is False
            assert "timeout" in result["error"].lower()
```

#### P2-1.3：安全测试

```python
# tests/security/test_sandbox_isolation.py
class TestSandboxIsolation:
    """沙箱隔离测试"""

    def test_cannot_access_main_process_globals(self):
        """沙箱代码无法访问主进程变量"""
        # 在主进程设置变量
        # 执行沙箱代码尝试访问
        # 验证失败

    def test_cannot_import_os(self):
        """os 模块被禁止"""

    def test_cannot_use_subprocess(self):
        """subprocess 被禁止"""

    def test_cannot_write_to_filesystem(self):
        """文件写入被禁止（open 函数应在白名单外）"""

    def test_cannot_make_network_request(self):
        """socket 模块被禁止"""

    def test_infinite_loop_killed_by_timeout(self):
        """死循环被超时杀死"""

    def test_memory_bomb_killed(self):
        """内存炸弹被限制"""
        # `[0] * 10**10` 应被限制
```

### 测试基础设施

#### conftest.py 共享 fixtures

```python
# tests/conftest.py
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """临时项目根目录"""
    (tmp_path / "pycoder").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.fixture
def client():
    """测试客户端（关闭认证）"""
    import os
    os.environ["PYCODER_API_KEY"] = "disabled"
    import importlib
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


@pytest.fixture
def auth_client(monkeypatch):
    """带认证的测试客户端"""
    monkeypatch.setenv("PYCODER_API_KEY", "test-secret-12345")
    import importlib
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    client = TestClient(app_module.app)
    client.headers.update({"X-API-Key": "test-secret-12345"})
    return client


@pytest.fixture
def mock_llm():
    """模拟 LLM Provider"""
    from unittest.mock import AsyncMock
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"tool_calls": [{"name": "test", "params": {}}]}')
    return llm
```

### 覆盖率配置

```ini
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=pycoder --cov-report=html --cov-report=term-missing --cov-fail-under=80"
asyncio_mode = "auto"
```

### 验收标准

- [ ] `pytest --cov=pycoder --cov-fail-under=80` 通过
- [ ] 关键模块覆盖率达标
- [ ] 安全测试全部通过
- [ ] E2E 测试覆盖核心用户流程

### 回滚策略

- 测试文件独立于源代码，失败时仅删除测试文件
- 不影响生产代码

### 风险评估

- **风险**：低 — 仅新增测试，不改源代码
- **工期**：7-10 天

---

## P2-2：提示词工程优化

### 问题分析

当前提示词存在：
- 过长导致 LLM 注意力分散
- 缺少 few-shot 示例
- 对复杂场景指令不够具体
- 仍允许 XML 格式输出（与 P1-2 冲突）

### 修复方案

#### 步骤 1：审查现有提示词

```bash
# 查找所有提示词定义
grep -rn "SYSTEM_PROMPT\|system_prompt" pycoder/server/ --include="*.py" | head -20
```

#### 步骤 2：优化原则

1. **简洁性**：每个提示词 ≤ 1500 字符（约 400 token）
2. **结构化**：使用 Markdown 分节（角色、工具、流程、约束）
3. **示例驱动**：包含 1-2 个 few-shot 示例
4. **格式强制**：明确要求 JSON 输出

#### 步骤 3：优化示例

```python
# pycoder/server/prompts/agent_system_prompt.py
"""Agent 系统提示词（优化版）"""

AGENT_SYSTEM_PROMPT = """你是一名专业 AI 代码助手，使用工具完成任务。

## 工具调用格式

当你需要调用工具时，**必须**输出以下 JSON 格式（在 ```json 代码块中）：

```json
{
  "thought": "分析当前任务，决定调用 xxx 工具因为...",
  "tool_calls": [
    {"name": "tool_name", "params": {"key": "value"}}
  ]
}
```

**禁止使用 XML 标签**（如 `<tool>`），仅支持 JSON。

## 示例

用户：读取 config.yaml 内容

```json
{
  "thought": "需要读取文件，调用 read_file 工具",
  "tool_calls": [
    {"name": "read_file", "params": {"path": "config.yaml"}}
  ]
}
```

## 约束

- 单次最多调用 1 个工具
- 工具调用失败时，分析错误并调整参数重试
- 连续失败 3 次后，停止并说明原因
- 完成任务后输出 `{"thought": "已完成", "tool_calls": []}` 表示结束
"""
```

#### 步骤 4：分角色提示词

为 PM、Architect、Developer、QA、DevOps 各自定制提示词：

```python
# pycoder/server/prompts/role_prompts.py
PM_PROMPT = """你是项目经理，负责：
1. 分析用户需求
2. 拆解为可执行子任务
3. 分配给合适角色

输出格式：JSON 任务列表
"""

ARCHITECT_PROMPT = """你是架构师，负责：
1. 选择技术方案
2. 定义模块边界
3. 输出架构设计文档
"""

DEVELOPER_PROMPT = """你是开发者，负责：
1. 实现具体代码
2. 编写单元测试
3. 修复 bug
"""

QA_PROMPT = """你是质量保证工程师，负责：
1. 审查代码质量
2. 编写测试用例
3. 验证功能正确性
"""
```

### 测试方案

```python
# tests/test_prompt_quality.py
def test_agent_prompt_mentions_json_format():
    """提示词必须明确要求 JSON 格式"""
    assert "```json" in AGENT_SYSTEM_PROMPT
    assert "tool_calls" in AGENT_SYSTEM_PROMPT

def test_agent_prompt_forbids_xml():
    """提示词应禁止 XML 格式"""
    assert "禁止使用 XML" in AGENT_SYSTEM_PROMPT or "不要使用 XML" in AGENT_SYSTEM_PROMPT

def test_prompt_length_within_limit():
    """提示词长度 ≤ 1500 字符"""
    assert len(AGENT_SYSTEM_PROMPT) <= 1500

def test_prompt_contains_example():
    """提示词应包含示例"""
    assert "示例" in AGENT_SYSTEM_PROMPT
```

### 验收标准

- [ ] 所有关键提示词长度 ≤ 1500 字符
- [ ] 所有提示词明确要求 JSON 格式
- [ ] 包含至少 1 个 few-shot 示例
- [ ] 工具调用解析成功率 ≥ 95%

### 风险评估

- **风险**：低 — 提示词修改可快速回滚
- **工期**：4-5 天

---

## P2-3：学习系统反馈闭环完善

### 问题分析

当前 `LearningEngine` 仅记录任务结果，未形成真正的反馈闭环：
- 学习数据未持久化
- 学习成果未应用于后续任务
- 缺乏评估指标追踪

### 修复方案

#### 步骤 1：实现持久化存储

```python
# pycoder/server/learning/persistence.py
"""学习数据持久化"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LearningStore:
    """学习数据持久化存储（JSON 文件）"""

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write({"records": [], "metrics": {}})

    def _read(self) -> dict:
        try:
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning("learning_store_read_failed", error=str(e))
            return {"records": [], "metrics": {}}

    def _write(self, data: dict) -> None:
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def add_record(self, record: dict) -> None:
        data = self._read()
        record["timestamp"] = datetime.now().isoformat()
        data["records"].append(record)
        # 限制记录数量
        if len(data["records"]) > 10000:
            data["records"] = data["records"][-5000:]
        self._write(data)

    def query_recent(self, task_type: str, limit: int = 10) -> list[dict]:
        data = self._read()
        records = [r for r in data["records"] if r.get("task_type") == task_type]
        return records[-limit:]

    def update_metric(self, key: str, value: float) -> None:
        data = self._read()
        metrics = data.setdefault("metrics", {})
        history = metrics.setdefault(key, [])
        history.append({"value": value, "timestamp": datetime.now().isoformat()})
        if len(history) > 100:
            history.pop(0)
        self._write(data)
```

#### 步骤 2：实现反馈应用

```python
# pycoder/server/learning/feedback.py
"""将学习成果应用于后续任务"""
from __future__ import annotations
from typing import Any
import logging

logger = logging.getLogger(__name__)


class FeedbackApplier:
    """将历史学习成果应用于新任务"""

    def __init__(self, store) -> None:
        self.store = store

    def get_similar_failures(self, task_type: str, description: str) -> list[dict]:
        """获取类似任务的失败记录，避免重复犯错"""
        recent = self.store.query_recent(task_type, limit=50)
        # 简单文本相似度匹配
        return [
            r for r in recent
            if r.get("outcome") == "failure"
            and self._text_similarity(r.get("description", ""), description) > 0.3
        ]

    def _text_similarity(self, a: str, b: str) -> float:
        """简单文本相似度（Jaccard 系数）"""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def build_context_for_task(self, task_type: str, description: str) -> str:
        """为新任务构建学习上下文"""
        failures = self.get_similar_failures(task_type, description)
        if not failures:
            return ""
        lines = ["## 历史失败教训（避免重复犯错）\n"]
        for f in failures[-3:]:  # 最近 3 个
            lines.append(f"- 失败原因: {f.get('error_msg', '未知')}")
        return "\n".join(lines)
```

#### 步骤 3：集成到 Agent 流程

```python
# 在 agent_orchestrator.py 中
class AgentOrchestrator:
    def __init__(self):
        # ...
        from pycoder.server.learning import get_learning_engine
        from pycoder.server.learning.feedback import FeedbackApplier
        self.feedback = FeedbackApplier(get_learning_engine().store)

    async def run_task(self, task: str) -> str:
        # 应用历史学习
        context = self.feedback.build_context_for_task("agent", task)
        full_prompt = f"{context}\n\n{task}" if context else task
        return await self._execute(full_prompt)
```

### 测试方案

```python
# tests/test_learning_feedback.py
def test_feedback_avoids_repeated_failures():
    store = LearningStore(tmp_path / "learn.json")
    store.add_record({
        "task_type": "test",
        "description": "implement login",
        "outcome": "failure",
        "error_msg": "missing auth check",
    })
    applier = FeedbackApplier(store)
    failures = applier.get_similar_failures("test", "implement login page")
    assert len(failures) == 1
    assert "missing auth check" in applier.build_context_for_task("test", "implement login page")
```

### 验收标准

- [ ] 学习数据持久化到磁盘
- [ ] 历史失败记录能影响后续任务上下文
- [ ] 任务成功率随时间提升
- [ ] 评估指标可追踪（成功率、平均耗时、Token 消耗）

### 风险评估

- **风险**：中 — 反馈应用可能引入噪声
- **缓解**：限制上下文长度，仅采用高相似度记录
- **工期**：5-7 天

---

## P2-4：成本熔断与 Token 预算控制

### 问题分析

报告中指出"缺乏成本熔断机制"和"缺乏 Token 预算控制"，可能导致：
- 单次任务消耗过多 Token
- 恶意用户耗尽 API 配额
- 自演化陷入死循环消耗资源

### 修复方案

```python
# pycoder/server/services/cost_control.py
"""成本控制与 Token 预算"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Token 预算配置"""
    per_request_limit: int = 100_000        # 单次请求最大 token
    per_session_limit: int = 1_000_000      # 单会话最大 token
    per_hour_limit: int = 5_000_000         # 每小时最大 token
    cost_per_1k_input: float = 0.01        # 输入每 1k token 成本（美元）
    cost_per_1k_output: float = 0.03        # 输出每 1k token 成本


@dataclass
class UsageRecord:
    used_tokens: int = 0
    used_cost: float = 0.0
    request_count: int = 0
    last_reset: datetime = field(default_factory=datetime.now)


class CostController:
    """成本熔断控制器"""

    def __init__(self, budget: TokenBudget) -> None:
        self.budget = budget
        self._session_usage = UsageRecord()
        self._hourly_usage = UsageRecord(
            last_reset=datetime.now()
        )

    def check_before_call(self, estimated_tokens: int) -> tuple[bool, str]:
        """调用前检查是否超预算"""
        # 单次请求限制
        if estimated_tokens > self.budget.per_request_limit:
            return False, f"单次请求 token {estimated_tokens} 超限 {self.budget.per_request_limit}"

        # 会话限制
        if self._session_usage.used_tokens + estimated_tokens > self.budget.per_session_limit:
            return False, f"会话累计 token {self._session_usage.used_tokens} 即将超限"

        # 小时限制
        self._maybe_reset_hourly()
        if self._hourly_usage.used_tokens + estimated_tokens > self.budget.per_hour_limit:
            return False, f"小时累计 token {self._hourly_usage.used_tokens} 即将超限"

        return True, ""

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """记录实际使用量"""
        total = input_tokens + output_tokens
        cost = (input_tokens / 1000 * self.budget.cost_per_1k_input +
                output_tokens / 1000 * self.budget.cost_per_1k_output)

        self._session_usage.used_tokens += total
        self._session_usage.used_cost += cost
        self._session_usage.request_count += 1

        self._hourly_usage.used_tokens += total
        self._hourly_usage.used_cost += cost

        logger.info(
            "token_usage_recorded",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            session_total=self._session_usage.used_tokens,
            hourly_total=self._hourly_usage.used_tokens,
        )

    def _maybe_reset_hourly(self) -> None:
        if datetime.now() - self._hourly_usage.last_reset > timedelta(hours=1):
            self._hourly_usage = UsageRecord(last_reset=datetime.now())

    def get_usage_report(self) -> dict:
        return {
            "session": {
                "tokens": self._session_usage.used_tokens,
                "cost": round(self._session_usage.used_cost, 4),
                "requests": self._session_usage.request_count,
            },
            "hourly": {
                "tokens": self._hourly_usage.used_tokens,
                "cost": round(self._hourly_usage.used_cost, 4),
                "requests": self._hourly_usage.request_count,
            },
        }
```

### 集成到 ChatBridge

```python
# 在 chat_bridge.py 中调用
class ChatBridge:
    def __init__(self):
        # ...
        self.cost_controller = CostController(TokenBudget())

    async def chat_stream(self, prompt: str):
        # 估算 token
        estimated = len(prompt) // 4  # 粗略估算
        ok, reason = self.cost_controller.check_before_call(estimated)
        if not ok:
            yield ChatEvent(event_type="error", content=f"成本超限: {reason}")
            return

        # ... 调用 LLM
        # 完成后记录实际用量
        self.cost_controller.record_usage(input_tokens=..., output_tokens=...)
```

### 测试方案

```python
# tests/test_cost_control.py
def test_per_request_limit():
    ctrl = CostController(TokenBudget(per_request_limit=1000))
    ok, _ = ctrl.check_before_call(500)
    assert ok
    ok, msg = ctrl.check_before_call(2000)
    assert not ok
    assert "单次请求" in msg

def test_hourly_limit_reset():
    ctrl = CostController(TokenBudget(per_hour_limit=1000))
    # 模拟时间流逝
    ...
```

### 验收标准

- [ ] 单次请求超限被拒绝
- [ ] 会话累计超限被拒绝
- [ ] 小时累计自动重置
- [ ] 使用量报告 API 可查询

### 风险评估

- **风险**：低
- **工期**：3-4 天

---

## P2-5：CI/CD 安全扫描与回归防护

### 问题分析

当前缺乏自动化安全扫描，问题容易回归。

### 修复方案

#### GitHub Actions 配置

```yaml
# .github/workflows/security-scan.yml
name: Security Scan

on:
  push:
    branches: [master, main]
  pull_request:
    branches: [master, main]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: |
          pip install bandit semgrep safety pytest pytest-cov

      - name: Bandit security scan
        run: bandit -r pycoder/ -f json -o bandit-report.json || true

      - name: Semgrep scan
        run: semgrep scan --config auto pycoder/ || true

      - name: Safety check dependencies
        run: safety check || true

      - name: Run tests with coverage
        run: |
          pytest --cov=pycoder --cov-report=xml --cov-fail-under=80

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        if: always()

      - name: Upload security reports
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: security-reports
          path: |
            bandit-report.json
```

#### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: '1.7.5'
    hooks:
      - id: bandit
        args: ['-ll', '-ii', '-x', 'tests/']

  - repo: https://github.com/PyCQA/flake8
    rev: '7.0.0'
    hooks:
      - id: flake8
        args: ['--select=E9,F63,F7,F82']

  - repo: local
    hooks:
      - id: no-bare-except
        name: forbid bare except Exception
        entry: bash -c 'if grep -rn "except Exception:" pycoder/ --include="*.py"; then echo "Found bare except"; exit 1; fi'
        language: system
        pass_filenames: false
```

### 验收标准

- [ ] CI 在每次 PR 时自动运行安全扫描
- [ ] 测试覆盖率 < 80% 时 CI 失败
- [ ] 检测到裸 except 时 pre-commit 阻止提交
- [ ] Bandit / Semgrep 报告可查看

### 风险评估

- **风险**：低
- **工期**：2-3 天

---

## P2 阶段验收清单

### 质量验收

- [ ] 测试覆盖率 ≥ 80%
- [ ] 所有关键模块测试通过
- [ ] 安全测试套件通过
- [ ] E2E 测试通过

### 提示词验收

- [ ] 所有关键提示词长度 ≤ 1500 字符
- [ ] 所有提示词要求 JSON 格式
- [ ] 工具调用解析成功率 ≥ 95%

### 学习系统验收

- [ ] 学习数据持久化
- [ ] 反馈应用于新任务
- [ ] 评估指标可追踪

### 成本控制验收

- [ ] Token 预算限制生效
- [ ] 超限请求被拒绝
- [ ] 使用量报告 API 可用

### CI/CD 验收

- [ ] GitHub Actions 配置完成
- [ ] Pre-commit hooks 生效
- [ ] 安全扫描报告生成

### 重审验收

- [ ] 综合评分 ≥ 88 分
- [ ] CRITICAL 问题数 = 0
- [ ] HIGH 问题数 = 0
- [ ] 测试覆盖率 ≥ 80%
- [ ] 生产就绪度 ≥ 85 分

---

## 三阶段完成后预期对比

| 指标 | 当前 | P0 后 | P1 后 | P2 后 |
|------|------|-------|-------|-------|
| 综合评分 | 63 | 75 | 82 | 88 |
| CRITICAL | 4 | 0 | 0 | 0 |
| HIGH | 6 | ≤ 4 | ≤ 2 | 0 |
| MEDIUM | 10 | ≤ 8 | ≤ 5 | ≤ 3 |
| 测试覆盖率 | 未知 | ≥ 60% | ≥ 75% | ≥ 80% |
| POST 端点通过率 | 10.7% | ≥ 90% | ≥ 95% | ≥ 98% |
| 生产就绪度 | 30 | 60 | 75 | 85 |

---

**下一步**：P0 与 P1 阶段完成后，请审阅本 P2 修复计划并确认实施顺序。完成后将执行最终的"测试+重审双重验证"。

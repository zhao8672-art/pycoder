# PyCoder v0.5 → v1.0 全面升级改进方案

> **文档版本:** v1.0  
> **生成日期:** 2026-07-11  
> **覆盖范围:** 架构债务清偿 + 竞品对标补强 + 安全加固 + 工程化升级  
> **总预计工时:** ~120 人时（约 3 周全职工期）

---

## 目录

- [一、方案总览](#一方案总览)
- [二、P0 — 架构核心重构 (v0.6)](#二p0--架构核心重构-v06)
  - [2.1 依赖注入容器](#21-依赖注入容器)
  - [2.2 端口反向注入](#22-端口反向注入)
  - [2.3 Adapter→Server 反向依赖消除](#23-adapter-server-反向依赖消除)
  - [2.4 RepoMap 代码仓库地图](#24-repomap-代码仓库地图)
- [三、P1 — 功能补强 (v0.7)](#三p1--功能补强-v07)
  - [3.1 Plan/Act 双模式](#31-planact-双模式)
  - [3.2 Memory Bank 跨会话记忆](#32-memory-bank-跨会话记忆)
  - [3.3 模型路由智能化 + 多供应商开放](#33-模型路由智能化--多供应商开放)
  - [3.4 权限系统服务端化](#34-权限系统服务端化)
- [四、P2 — 安全与兼容 (v0.8)](#四p2--安全与兼容-v08)
  - [4.1 Docker 沙箱默认启用](#41-docker-沙箱默认启用)
  - [4.2 Native Tool Use 协议](#42-native-tool-use-协议)
- [五、P3 — 数据与智能 (v0.9)](#五p3--数据与智能-v09)
  - [5.1 SQLAlchemy 统一 + Alembic 迁移](#51-sqlalchemy-统一--alembic-迁移)
  - [5.2 向量化 RAG 上下文检索](#52-向量化-rag-上下文检索)
- [六、验收标准](#六验收标准)
- [七、风险与回滚](#七风险与回滚)

---

## 一、方案总览

### 背景

经过全面测试和底层架构审查，PyCoder v0.5.0 存在以下分类问题：

| 类别 | 问题数 | 严重度 | 根因 |
|------|:------:|:------:|------|
| 架构违规 | 4 | CRITICAL | Clean Architecture 端口空洞化，DI 缺失 |
| 竞品差距 | 5 | HIGH | 缺 RepoMap / Plan-Act / MemoryBank |
| 安全漏洞 | 4 | HIGH | 客户端权限检查 / 破坏性命令白名单 |
| 模型锁定 | 3 | MEDIUM | DeepSeek 生态绑定 |
| 工程债务 | 6 | MEDIUM | Schema 迁移缺失 / ORM 不一致 |

### 版本里程碑

```
v0.5 (当前) ──P0──► v0.6 ──P1──► v0.7 ──P2──► v0.8 ──P3──► v1.0
  Ruff: 1030         DI容器      双模式      Docker      RAG
  测试: 5206/5221    RepoMap      Memory      ToolUse     SQLAlchemy
  安全: 65/65        端口注入    模型开放     权限加固    向量检索
```

---

## 二、P0 — 架构核心重构 (v0.6)

> **目标:** 清偿 Clean Architecture 债务，使端口从装饰品变为基础设施  
> **工时:** ~40h | **风险:** 中（影响面广但可控）  
> **验收:** `test_clean_architecture.py` 新增 15 个用例全部通过

### 2.1 依赖注入容器

**问题:** 项目 400KB 代码通过 `import` 硬连接依赖。没有 DI 容器，端口无法反向注入。

**方案:** 新建 `pycoder/core/di.py` — 轻量级注册表模式（不引入第三方库）

#### 新建文件: `pycoder/core/di.py`

```python
"""P0: Dependency Injection Container — 轻量级注册表

所有核心依赖通过此容器注册和解析，消除硬 import。
消费方依赖 Registry 而非具体实现。

用法:
    # 注册（启动时）
    from pycoder.core.di import registry
    registry.register(LLMProvider, BridgeLLMProvider(bridge))

    # 解析（运行时）
    llm = registry.resolve(LLMProvider)
    response = await llm.generate("Hello")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class Registry:
    """依赖注入注册表 — 按 Protocol 类型注册/解析"""

    def __init__(self) -> None:
        self._instances: dict[type, Any] = {}
        self._factories: dict[type, Callable[[], Any]] = {}

    def register(self, proto: type[T], implementation: T | None = None, *,
                 factory: Callable[[], T] | None = None) -> None:
        """注册实现。

        三种用法:
            registry.register(LLMProvider, my_llm)          # 实例
            registry.register(LLMProvider, factory=create)  # 工厂（延迟初始化）
        """
        if implementation is not None:
            self._instances[proto] = implementation
        elif factory is not None:
            self._factories[proto] = factory
        else:
            raise ValueError("必须提供 implementation 或 factory")

    def resolve(self, proto: type[T]) -> T:
        """解析依赖。先查实例，再查工厂。"""
        if proto in self._instances:
            return self._instances[proto]
        if proto in self._factories:
            instance = self._factories[proto]()
            self._instances[proto] = instance  # 缓存
            return instance
        raise LookupError(f"未注册: {proto.__name__}")

    def is_registered(self, proto: type) -> bool:
        """检查是否已注册"""
        return proto in self._instances or proto in self._factories

    def clear(self) -> None:
        """清空所有注册（测试用）"""
        self._instances.clear()
        self._factories.clear()


# 全局单例
registry = Registry()
```

#### 启动时注册（修改 `pycoder/server/app.py`）

在 `lifespan()` 函数内添加注册逻辑：

```python
# 在 app.py 的 lifespan() 中，await _init_recommendation_db() 之后添加:

from pycoder.core.di import registry
from pycoder.core.ports.llm_provider import LLMProvider
from pycoder.core.ports.code_sandbox import CodeSandbox
from pycoder.core.ports.file_system import FileSystem
from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
from pycoder.adapters.local_file_system import LocalFileSystem
from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

# 注册核心端口实现
workspace = Path(get_workspace_root())
registry.register(FileSystem, LocalFileSystem(workspace=workspace))
registry.register(CodeSandbox, SubprocessSandbox(default_timeout=30, max_timeout=120))
# LLMProvider 通过工厂延迟初始化（需要 project_dir 参数）
registry.register(LLMProvider, factory=lambda: BridgeLLMProvider(ChatBridge()))

_logger.info("DI 容器已初始化: LLMProvider, CodeSandbox, FileSystem 已注册")
```

#### 测试: `tests/architecture/test_di_container.py`

```python
"""P0: 依赖注入容器测试"""
import pytest
from pycoder.core.di import Registry, registry
from pycoder.core.ports.llm_provider import LLMProvider


class TestRegistry:
    def test_register_and_resolve_instance(self):
        r = Registry()
        r.register(LLMProvider, _MockLLM())
        assert isinstance(r.resolve(LLMProvider), _MockLLM)

    def test_register_and_resolve_factory(self):
        r = Registry()
        r.register(LLMProvider, factory=lambda: _MockLLM())
        llm1 = r.resolve(LLMProvider)
        llm2 = r.resolve(LLMProvider)
        assert llm1 is llm2  # 工厂结果应被缓存

    def test_resolve_unregistered_raises(self):
        r = Registry()
        with pytest.raises(LookupError):
            r.resolve(LLMProvider)

    def test_is_registered(self):
        r = Registry()
        assert not r.is_registered(LLMProvider)
        r.register(LLMProvider, _MockLLM())
        assert r.is_registered(LLMProvider)

    def test_clear(self):
        r = Registry()
        r.register(LLMProvider, _MockLLM())
        r.clear()
        assert not r.is_registered(LLMProvider)

    def test_global_registry_works(self):
        registry.clear()
        registry.register(LLMProvider, _MockLLM())
        assert isinstance(registry.resolve(LLMProvider), _MockLLM)
        registry.clear()


class _MockLLM:
    async def generate(self, prompt, **kw):
        from pycoder.core.ports.llm_provider import LLMResponse
        return LLMResponse(content="mock")
    def stream(self, prompt, **kw):
        yield None
    def configure(self, **kw):
        pass
```

**工时:** 4h | **风险:** 低 | **文件:** 新建 1 + 修改 2 + 新建测试 1

---

### 2.2 端口反向注入

**问题:** `autonomous_pipeline.py`、`task_decomposer.py` 等直接 `import ChatBridge`。

**方案:** 改为从 DI 容器解析 `LLMProvider` Protocol。

#### 修改 `pycoder/server/services/autonomous_pipeline.py` (第33行)

**修改前:**
```python
from pycoder.server.chat_bridge import ChatBridge
```

**修改后:**
```python
from pycoder.core.di import registry
from pycoder.core.ports.llm_provider import LLMProvider
```

在 `_run_step2_code()` 方法中（约第 132 行），将:
```python
bridge = ChatBridge()
response = await bridge.chat_stream(messages=msgs, model=model)
```
改为:
```python
llm = registry.resolve(LLMProvider)
response = await llm.generate(prompt=assembled_prompt, system_prompt=system_prompt)
```

#### 修改 `pycoder/server/services/task_decomposer.py` (第17行起)

函数签名从:
```python
async def decompose_task(
    request: str,
    chat_bridge: ChatBridge,        # ❌ 具体实现
    model: str = "deepseek-chat",
    ...
) -> DecompositionResult:
```
改为:
```python
async def decompose_task(
    request: str,
    llm: LLMProvider | None = None,  # ✅ 端口抽象
    model: str = "deepseek-chat",
    ...
) -> DecompositionResult:
    if llm is None:
        from pycoder.core.di import registry
        llm = registry.resolve(LLMProvider)
```

#### 修改 `pycoder/server/services/unified_agent.py`

`UnifiedAgentEngine.chat_stream()` 中第 76 行:
```python
# 修改前
bridge = ChatBridge()
```
改为:
```python
# 修改后
from pycoder.core.di import registry
from pycoder.core.ports.llm_provider import LLMProvider
llm = registry.resolve(LLMProvider)
```

#### 新增测试: `tests/architecture/test_port_injection.py`

```python
"""P0: 端口反向注入验证 — 确保核心模块使用 LLMProvider 而非 ChatBridge"""
import ast
from pathlib import Path


FORBIDDEN_IMPORTS = [
    "from pycoder.server.chat_bridge import ChatBridge",
    "import pycoder.server.chat_bridge",
]
ALLOWED_IN = [
    # 这些文件允许直接使用 ChatBridge（bridge 层 + adapter）
    "pycoder/server/chat_bridge.py",
    "pycoder/adapters/bridge_llm_provider.py",
    "pycoder/server/app.py",
]

CRITICAL_MODULES = [
    "pycoder/server/services/autonomous_pipeline.py",
    "pycoder/server/services/task_decomposer.py",
    "pycoder/server/services/unified_agent.py",
    "pycoder/server/services/agent_orchestrator.py",
    "pycoder/server/services/team/session_orchestrator.py",
    "pycoder/server/services/team/job_orchestrator.py",
    "pycoder/server/services/team/review_orchestrator.py",
]


def test_no_chatbridge_import_in_services():
    """关键服务模块不应直接导入 ChatBridge"""
    root = Path(__file__).parent.parent.parent
    violations = []
    for mod_path in CRITICAL_MODULES:
        full_path = root / mod_path
        if not full_path.exists():
            continue
        source = full_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if forbidden in source:
                violations.append(f"{mod_path}: 违规导入 {forbidden}")
    assert not violations, "\n".join(violations)


def test_critical_modules_use_llmprovider():
    """关键模块应使用 LLMProvider Protocol"""
    root = Path(__file__).parent.parent.parent
    found = False
    for mod_path in CRITICAL_MODULES:
        full_path = root / mod_path
        if not full_path.exists():
            continue
        source = full_path.read_text(encoding="utf-8")
        if "LLMProvider" in source:
            found = True
            break
    assert found, "至少一个关键模块应引用 LLMProvider"
```

**工时:** 8h | **风险:** 中（影响面广） | **文件:** 修改 4 + 新建测试 1

---

### 2.3 Adapter→Server 反向依赖消除

**问题:** `subprocess_sandbox.py` 第 48 行惰性导入 server 层，违反依赖反转。

**方案:** 在 server 启动时通过 DI 注入执行函数，adapter 不再 self-import server。

#### 修改 `pycoder/server/app.py` 启动注册

```python
# 在 lifespan() 中添加:
from pycoder.server.routers.code_exec import _run_in_subprocess, _sandbox_config

sandbox = SubprocessSandbox(
    run_fn=_run_in_subprocess,
    max_timeout_fn=lambda: _sandbox_config.max_timeout,
    default_timeout=30,
    max_timeout=120,
)
registry.register(CodeSandbox, sandbox)
```

#### 修改 `pycoder/adapters/subprocess_sandbox.py`

删除惰性导入代码块（第 43-55 行）中的 server 层 import，改为：

```python
def _resolve_run_fn(self) -> tuple[Callable[[str, int], object], int]:
    """解析执行函数 — 必须通过 DI 注入，不再惰性导入 server"""
    if self._run_fn is None or self._max_timeout_fn is None:
        raise RuntimeError(
            "SubprocessSandbox 未注入 run_fn/max_timeout_fn。"
            "请在启动时通过 registry.register(CodeSandbox, SubprocessSandbox(run_fn=...)) 注册。"
        )
    return self._run_fn, self._max_timeout_fn()
```

**工时:** 2h | **风险:** 低 | **文件:** 修改 2

---

### 2.4 RepoMap 代码仓库地图

**问题:** 当前只有滑窗截断，大型项目（100+ 文件）无法提供有用上下文。竞品 Aider 的 RepoMap 通过 tree-sitter + PageRank 解决了此问题。

**方案:** 新建 `pycoder/python/repomap.py`，借鉴 Aider 设计但做 Python 优先的简化实现。

#### 新建文件: `pycoder/python/repomap.py`

核心架构：

```
RepoMap
├── TagExtractor     — 用 ast 模块提取 Python 符号 (def/class/import)
├── GraphBuilder     — 构建文件→文件的有向依赖图
├── PageRankRanker   — PageRank 算法排序文件重要性
├── ContextAssembler — 按 token budget 组装上下文
└── CachingLayer     — 文件哈希缓存，避免重复解析
```

关键代码骨架：

```python
"""P0: RepoMap — 代码仓库智能上下文映射

借鉴 Aider 的 repomap.py，但面向 Python 优先优化。
使用 ast 模块 (替代 tree-sitter) 降低依赖，PageRank 算法排序文件重要性。

用法:
    from pycoder.python.repomap import RepoMap
    rmap = RepoMap(workspace=Path("/project"))
    ctx = rmap.get_repo_map(chat_files=["src/main.py"], other_files=[...])
    # ctx 不超过 max_tokens，包含最重要的文件摘要
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeTag:
    """代码符号标签"""
    fname: str          # 相对路径
    name: str           # 符号名
    kind: str           # "def" | "class" | "import" | "ref"
    line: int           # 行号 (0-indexed)


@dataclass
class FileNode:
    """依赖图中的文件节点"""
    path: str
    tags: list[CodeTag] = field(default_factory=list)
    score: float = 0.0
    content_hash: str = ""


class RepoMap:
    """仓库代码地图 — 为 LLM 提供智能上下文"""

    def __init__(self, workspace: Path, max_tokens: int = 8000) -> None:
        self._workspace = workspace
        self._max_tokens = max_tokens
        self._cache: dict[str, list[CodeTag]] = {}  # file_hash → tags

    def get_repo_map(
        self,
        chat_files: list[str],
        other_files: list[str] | None = None,
    ) -> str:
        """生成仓库地图文本，供注入 system prompt。

        Args:
            chat_files: 用户正在编辑/关注的文件
            other_files: 仓库中的其他文件（自动扫描如果未提供）
        Returns:
            token 预算内的仓库地图文本
        """
        # 1. 提取所有文件的标签
        all_tags: dict[str, list[CodeTag]] = {}
        for f in chat_files:
            all_tags[f] = self._extract_tags(Path(f))
        if other_files is None:
            other_files = self._scan_python_files()
        for f in other_files:
            if f not in all_tags:
                all_tags[f] = self._extract_tags(Path(f))

        # 2. 构建依赖图
        graph = self._build_dependency_graph(all_tags)

        # 3. PageRank 排序
        scores = self._pagerank(graph, damping=0.85, iterations=20)

        # 4. 按 token 预算组装
        return self._assemble_context(all_tags, scores, chat_files)

    # ── 标签提取 ──

    def _extract_tags(self, file_path: Path) -> list[CodeTag]:
        """使用 ast 模块提取 Python 符号定义和引用"""
        full = self._workspace / file_path
        content_hash = self._hash_file(full)
        if content_hash in self._cache:
            return self._cache[content_hash]

        try:
            source = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        tags = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    tags.append(CodeTag(
                        fname=str(file_path), name=node.name,
                        kind="def", line=node.lineno - 1
                    ))
                elif isinstance(node, ast.ClassDef):
                    tags.append(CodeTag(
                        fname=str(file_path), name=node.name,
                        kind="class", line=node.lineno - 1
                    ))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        tags.append(CodeTag(
                            fname=str(file_path), name=alias.name,
                            kind="import", line=node.lineno - 1
                        ))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        tags.append(CodeTag(
                            fname=str(file_path), name=node.module,
                            kind="import", line=node.lineno - 1
                        ))
        except SyntaxError:
            pass

        self._cache[content_hash] = tags
        return tags

    # ── 依赖图构建 ──

    def _build_dependency_graph(
        self, all_tags: dict[str, list[CodeTag]]
    ) -> dict[str, set[str]]:
        """构建文件→文件的有向依赖图"""
        graph: dict[str, set[str]] = defaultdict(set)
        for fname, tags in all_tags.items():
            graph[fname]  # 确保每个文件都有入口
            for tag in tags:
                if tag.kind == "import":
                    # 尝试将 import 模块名映射到仓库内文件
                    for other in all_tags:
                        mod_name = other.replace("/", ".").replace(".py", "")
                        if mod_name.endswith(tag.name) or tag.name in mod_name:
                            graph[fname].add(other)
        return dict(graph)

    # ── PageRank ──

    def _pagerank(
        self, graph: dict[str, set[str]],
        damping: float = 0.85, iterations: int = 20,
    ) -> dict[str, float]:
        """简化 PageRank — 文件重要性排序"""
        nodes = list(graph.keys())
        n = len(nodes)
        if n == 0:
            return {}

        scores = {node: 1.0 / n for node in nodes}
        for _ in range(iterations):
            new_scores = {node: (1 - damping) / n for node in nodes}
            for node in nodes:
                out_links = graph.get(node, set())
                if not out_links:
                    continue
                share = damping * scores[node] / len(out_links)
                for target in out_links:
                    new_scores[target] += share
            scores = new_scores
        return scores

    # ── 上下文组装 ──

    def _assemble_context(
        self,
        all_tags: dict[str, list[CodeTag]],
        scores: dict[str, float],
        chat_files: list[str],
    ) -> str:
        """按 token 预算组装可注入的仓库地图"""
        # 优先包含 chat_files
        sorted_files = sorted(
            all_tags.keys(),
            key=lambda f: (f not in chat_files, -scores.get(f, 0)),
        )

        lines = ["# Repository Map\n"]
        token_count = len(lines[0])

        for fname in sorted_files:
            tags = all_tags[fname]
            if not tags:
                continue
            # 格式化文件摘要
            def_lines = [t for t in tags if t.kind in ("def", "class")]
            if not def_lines:
                continue
            entry = f"\n## {fname}\n"
            for t in sorted(def_lines, key=lambda x: x.line)[:10]:
                indent = "  " if t.kind == "def" else ""
                entry += f"{indent}{t.kind} {t.name} (line {t.line + 1})\n"

            token_count += len(entry) // 4  # 粗略 token 估算
            if token_count > self._max_tokens:
                lines.append("\n... (truncated for token budget)")
                break
            lines.append(entry)

        return "".join(lines)

    # ── 工具方法 ──

    def _scan_python_files(self) -> list[str]:
        """扫描工作区所有 .py 文件"""
        files = []
        for py_file in self._workspace.rglob("*.py"):
            if "__pycache__" in str(py_file) or ".venv" in str(py_file):
                continue
            rel = py_file.relative_to(self._workspace)
            files.append(str(rel))
        return files

    @staticmethod
    def _hash_file(path: Path) -> str:
        try:
            return hashlib.md5(path.read_bytes()).hexdigest()
        except OSError:
            return ""


# 全局单例
_repo_map: RepoMap | None = None


def get_repo_map(workspace: Path | None = None, max_tokens: int = 8000) -> RepoMap:
    """获取或创建 RepoMap 单例"""
    global _repo_map
    if _repo_map is None:
        from pycoder.server.routers.files import get_workspace_root
        ws = workspace or Path(get_workspace_root())
        _repo_map = RepoMap(workspace=ws, max_tokens=max_tokens)
    return _repo_map
```

#### 集成到 Agent 循环（修改 `agent_react_loop.py`）

在 `run()` 方法开始处注入仓库地图：

```python
# 在 ReActLoop.run() 方法中，约第 120 行 system prompt 组装处插入:
def _build_messages(self, task: str, chat_files: list[str]) -> list[dict]:
    # 获取仓库地图
    try:
        from pycoder.python.repomap import get_repo_map
        rmap = get_repo_map()
        repo_context = rmap.get_repo_map(chat_files=chat_files)
    except Exception:
        repo_context = ""
    
    system = self._system_prompt
    if repo_context:
        system += f"\n\n{repo_context}"
    ...
```

#### 测试: `tests/test_repomap.py`

```python
"""P0: RepoMap 测试"""
import pytest
from pathlib import Path
from pycoder.python.repomap import RepoMap, CodeTag


class TestTagExtraction:
    def test_extract_tags_from_python_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("""
import os
def hello():
    return "world"
class MyClass:
    def method(self):
        pass
""")
        rmap = RepoMap(workspace=tmp_path)
        tags = rmap._extract_tags(Path("test.py"))
        names = {t.name for t in tags}
        assert "hello" in names
        assert "MyClass" in names
        assert "os" in names

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        rmap = RepoMap(workspace=tmp_path)
        tags = rmap._extract_tags(Path("test.py"))
        assert tags == []


class TestPageRank:
    def test_simple_graph(self):
        rmap = RepoMap(workspace=Path("."))
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        scores = rmap._pagerank(graph)
        assert "a" in scores
        assert scores["c"] > scores["b"] > scores["a"]  # 被引用多的排名高


class TestIntegration:
    def test_get_repo_map_returns_string(self, tmp_path):
        (tmp_path / "main.py").write_text("def main(): pass")
        (tmp_path / "utils.py").write_text("def helper(): pass")
        rmap = RepoMap(workspace=tmp_path, max_tokens=500)
        result = rmap.get_repo_map(chat_files=["main.py"])
        assert "main.py" in result
        assert isinstance(result, str)
        assert len(result) > 0
```

**工时:** 12h | **风险:** 中 | **文件:** 新建 2 + 修改 1 + 新建测试 1

---

## 三、P1 — 功能补强 (v0.7)

> **目标:** 对标 Cline/Aider 补齐 Plan/Act 双模式、Memory Bank、模型开放  
> **工时:** ~40h | **风险:** 中

### 3.1 Plan/Act 双模式

**问题:** 当前只有单一 ReAct 循环，无法在只读模式下制定计划并获得用户审批。

**方案:** 在 `UnifiedAgentEngine` 中增加 `ModeRouter`，Plan 模式下禁止写操作。

#### 修改 `pycoder/server/services/unified_agent.py`

新增 Mode 枚举和 ModeRouter：

```python
from enum import Enum

class AgentMode(Enum):
    PLAN = "plan"   # 只读：read_file, search_files, grep
    ACT = "act"     # 全量工具：write_file, execute, terminal
    AUTO = "auto"   # 自动选择（默认）

# 模式->工具白名单
MODE_TOOL_WHITELIST: dict[AgentMode, set[str]] = {
    AgentMode.PLAN: {"read_file", "list_files", "search_files", "grep", "FINISH"},
    AgentMode.ACT: set(),  # 空集 = 全部允许
}

class ModeRouter:
    """Plan/Act 模式路由器"""
    
    def __init__(self, default_mode: AgentMode = AgentMode.AUTO):
        self._mode = default_mode
    
    @property
    def mode(self) -> AgentMode:
        return self._mode
    
    def switch_to(self, mode: AgentMode) -> None:
        self._mode = mode
        log.info("mode_switched", mode=mode.value)
    
    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具在当前模式下是否允许"""
        if self._mode == AgentMode.AUTO:
            return True
        whitelist = MODE_TOOL_WHITELIST.get(self._mode, set())
        if not whitelist:
            return True  # ACT mode allows all
        return tool_name in whitelist
    
    def auto_select(self, task_complexity: str) -> AgentMode:
        """根据任务复杂度自动选择模式"""
        if task_complexity == "high":
            return AgentMode.PLAN  # 复杂任务先规划
        return AgentMode.ACT
```

**工时:** 6h | **风险:** 低 | **文件:** 修改 1 + 测试 1

---

### 3.2 Memory Bank 跨会话记忆

**问题:** SQLite 只存储会话消息，无跨会话的项目理解。竞品 Cline 的 Memory Bank 用 Markdown 文件持久化项目记忆。

**方案:** 新建 `.pycoder/memory/` 目录，维护结构化记忆文件。

#### 新建文件: `pycoder/server/memory_bank.py`

```python
"""P1: Memory Bank — 跨会话项目记忆

借鉴 Cline 的 Memory Bank 设计，自动维护项目上下文文件。

文件结构:
    .pycoder/memory/
    ├── project_brief.md     # 项目概述（自动生成+人工审阅）
    ├── architecture.md      # 架构决策记录
    ├── tech_context.md      # 技术栈和依赖
    ├── active_context.md    # 当前活跃工作
    └── progress.md          # 进度追踪

每次会话启动时，自动加载相关 memory 注入 system prompt。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MemoryBank:
    """项目记忆管理器"""
    
    MEMORY_FILES = {
        "project_brief": "project_brief.md",
        "architecture": "architecture.md",
        "tech_context": "tech_context.md",
        "active_context": "active_context.md",
        "progress": "progress.md",
    }
    
    def __init__(self, workspace: Path) -> None:
        self._memory_dir = workspace / ".pycoder" / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
    
    def load_context_for_prompt(self, max_tokens: int = 2000) -> str:
        """加载应注入 system prompt 的记忆内容。
        
        按优先级加载: project_brief > architecture > tech_context > active_context
        """
        parts = []
        token_estimate = 0
        
        for key, filename in [
            ("project_brief", "project_brief.md"),
            ("architecture", "architecture.md"),
            ("tech_context", "tech_context.md"),
        ]:
            content = self._read(filename)
            if content:
                tokens = len(content) // 4
                if token_estimate + tokens > max_tokens:
                    parts.append(content[: (max_tokens - token_estimate) * 4])
                    break
                parts.append(content)
                token_estimate += tokens
        
        if not parts:
            return ""
        
        header = "<!-- Memory Bank — 项目持久记忆 -->\n\n"
        return header + "\n\n".join(parts)
    
    def update_project_brief(self, content: str) -> None:
        """更新项目概述"""
        self._write("project_brief.md", self._with_timestamp(content))
    
    def record_architecture_decision(self, title: str, decision: str, rationale: str) -> None:
        """记录架构决策"""
        existing = self._read("architecture.md") or "# Architecture Decisions\n\n"
        entry = (
            f"## {title}\n"
            f"- **决策:** {decision}\n"
            f"- **理由:** {rationale}\n"
            f"- **日期:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
        )
        self._write("architecture.md", existing + entry)
    
    def update_progress(self, status: str, detail: str) -> None:
        """更新进度"""
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        existing = self._read("progress.md") or "# Progress Log\n\n"
        entry = f"- [{ts}] **{status}**: {detail}\n"
        self._write("progress.md", existing + entry)
    
    def set_active_context(self, description: str, files: list[str]) -> None:
        """设置当前活跃工作上下文"""
        content = f"# Active Context\n\n{description}\n\n## 相关文件\n\n"
        for f in files:
            content += f"- `{f}`\n"
        self._write("active_context.md", content)
    
    # ── 内部方法 ──
    
    def _read(self, filename: str) -> str:
        path = self._memory_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def _write(self, filename: str, content: str) -> None:
        path = self._memory_dir / filename
        path.write_text(content, encoding="utf-8")
    
    @staticmethod
    def _with_timestamp(content: str) -> str:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        if not content.startswith("<!--"):
            content = f"<!-- 自动生成于 {ts} -->\n\n{content}"
        return content


# 全局单例
_memory_bank: MemoryBank | None = None


def get_memory_bank(workspace: Path | None = None) -> MemoryBank:
    global _memory_bank
    if _memory_bank is None:
        from pycoder.server.routers.files import get_workspace_root
        ws = workspace or Path(get_workspace_root())
        _memory_bank = MemoryBank(workspace=ws)
    return _memory_bank
```

**工时:** 6h | **风险:** 低 | **文件:** 新建 1 + 修改 2（app.py + chat_handler）

---

### 3.3 模型路由智能化 + 多供应商开放

**问题:** TaskClassifier 纯关键词匹配，ModelCapabilityMatrix 静态硬编码，仅支持 DeepSeek 生态。

**方案:** 三层改造 — LLM二次分类 + 运行时反馈 + Claude/Gemini 适配。

#### 3.3.1 修改 `pycoder/server/services/model_router.py`

在 TaskClassifier 中增加 LLM 二次分类：

```python
# 新增方法
class TaskClassifier:
    async def classify_with_llm(self, task: str, llm: LLMProvider) -> str:
        """使用 LLM 进行语义分类 — 比关键词匹配更准确"""
        prompt = (
            "分析以下编程任务，输出单一类别名称:\n"
            f"任务: {task}\n\n"
            "类别选项:\n"
            "- code_gen: 生成新代码或功能\n"
            "- fix: 修复 bug 或错误\n"
            "- refactor: 重构改进代码\n"
            "- review: 代码审查\n"
            "- test: 测试相关\n"
            "- docs: 文档生成\n"
            "- architecture: 架构设计\n"
            "- deployment: 部署运维\n"
            "- general: 通用咨询\n\n"
            "只输出类别名称，不要解释。"
        )
        try:
            resp = await llm.generate(prompt, max_tokens=10)
            return resp.content.strip().lower()
        except Exception:
            return self._keyword_classify(task)
```

#### 3.3.2 新增 Claude/Gemini 适配器

新建 `pycoder/adapters/anthropic_provider.py`:

```python
"""P1: AnthropicProvider — 适配 Claude API 到 LLMProvider Protocol"""
from pycoder.core.ports.llm_provider import LLMProvider, LLMEvent, LLMResponse
from collections.abc import AsyncIterator

class AnthropicProvider:
    """通过 Anthropic SDK 实现 LLMProvider"""
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key
        self._model = model
    
    async def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 4096) -> LLMResponse:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        msg = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt or "You are a helpful coding assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        return LLMResponse(
            content=msg.content[0].text,
            model=self._model,
            usage=dict(msg.usage) if msg.usage else {},
            finish_reason=msg.stop_reason or "",
        )
    
    async def stream(self, prompt: str, system_prompt: str = "", max_tokens: int = 4096) -> AsyncIterator[LLMEvent]:
        # ... streaming implementation
        yield LLMEvent(event_type="done")
    
    def configure(self, **kwargs) -> None:
        if "model" in kwargs:
            self._model = kwargs["model"]
```

**工时:** 10h | **风险:** 中 | **文件:** 修改 1 + 新建 2

---

### 3.4 权限系统服务端化

**问题:** 权限检查是客户端纯代码判断，Agent 可绕过。ALLOWED_COMMANDS 包含 `rm`/`del`/`mv`。

**方案:** 引入服务端 ACL 引擎 + 自主模式自动降权。

#### 修改 `pycoder/server/permission_policy.py`

```python
# 在 PermissionPolicy 类中新增:

@dataclass  
class PermissionPolicy:
    # ... 现有字段 ...
    
    # P1 新增: 操作级细粒度权限
    dangerous_commands: list[str] = field(
        default_factory=lambda: ["rm", "rmdir", "del", "format", "mkfs", "dd"]
    )
    always_forbidden: list[str] = field(
        default_factory=lambda: [
            "rm -rf /", "rm -rf /*", "del /S /Q C:\\", "format C:",
            "> /dev/sda", "dd if=", "mkfs.",
        ]
    )
    require_confirmation_for: list[str] = field(
        default_factory=lambda: ["rm ", "del ", "rmdir ", "mv ", "chmod 777"]
    )
    
    def check_shell(self, command: str, context: dict | None = None) -> tuple[bool, str]:
        """服务端权限检查 — 返回 (allowed, reason)
        
        P1: 强制执行危险命令拦截。即使 Agent 调用 check_shell 返回 ask，
        自主模式下也会被强制 deny。
        """
        # L1: 全局禁止
        for pattern in self.always_forbidden:
            if pattern in command:
                return False, f"永久禁止: 匹配危险模式 '{pattern}'"
        
        # L2: 危险命令 + 自主模式 = 自动拒绝
        is_autonomous = (context or {}).get("autonomous", False)
        cmd_base = command.strip().split()[0] if command.strip() else ""
        if is_autonomous and cmd_base in self.dangerous_commands:
            return False, f"自主模式禁止危险命令: {cmd_base}"
        
        # L3: 需要确认
        for pattern in self.require_confirmation_for:
            if command.startswith(pattern):
                if is_autonomous:
                    return False, f"自主模式需要确认: {pattern}"
                return True, f"需要确认: {command[:80]}"
        
        # L4: Shell 级别策略
        if self.shell == PermissionLevel.DENY:
            return False, "Shell 操作已全局禁止"
        
        return True, ""
```

#### 修改 `pycoder/server/services/autonomous_pipeline.py`

在命令执行处加入上下文：

```python
# 在 _execute_command() 附近:
from pycoder.server.permission_policy import get_permission_policy
policy = get_permission_policy()
allowed, reason = policy.check_shell(cmd, context={"autonomous": True})
if not allowed:
    log.warning("command_blocked", command=cmd, reason=reason)
    return {"error": reason}
```

**工时:** 6h | **风险:** 低 | **文件:** 修改 2 + 测试 1

---

## 四、P2 — 安全与兼容 (v0.8)

> **目标:** Docker 沙箱默认 + Native Tool Use  
> **工时:** ~24h | **风险:** 低

### 4.1 Docker 沙箱默认启用

修改 `pycoder/adapters/subprocess_sandbox.py` → `pycoder/adapters/docker_sandbox.py`：

```python
"""P2: DockerSandbox — 容器化代码执行（默认实现）"""
import asyncio
import tempfile
from pathlib import Path
from pycoder.core.ports.code_sandbox import CodeSandbox, CodeExecutionResult

class DockerSandbox:
    """Docker 容器沙箱 — 完全隔离的代码执行"""
    
    IMAGE = "python:3.12-slim"
    
    async def execute(self, code: str, timeout: int = 30) -> CodeExecutionResult:
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write(code)
            tmp_path = f.name
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm",
                "--network=none",           # 网络隔离
                "--memory=512m",            # 内存限制
                "--cpus=1",                 # CPU 限制
                "--read-only",              # 只读文件系统
                f"--tmpfs=/tmp:size=100m",  # 临时写空间
                "-v", f"{tmp_path}:/code.py:ro",
                self.IMAGE,
                "python", "/code.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return CodeExecutionResult(
                success=proc.returncode == 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                execution_time=0.0,
            )
        except asyncio.TimeoutError:
            return CodeExecutionResult(
                success=False, error_type="TimeoutError",
                error_message=f"执行超时 ({timeout}s)",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
```

**工时:** 8h | **风险:** 低 | **文件:** 新建 1 + 修改 2

---

### 4.2 Native Tool Use 协议

在 `agent_react_loop.py` 中增加 OpenAI/Anthropic function calling 支持：

```python
# 在 _call_llm() 方法中:

async def _call_llm(self, messages: list[dict]) -> dict:
    """调用 LLM — 根据模型类型选择调用方式"""
    model = self._llm_config.get("model", "")
    
    # OpenAI function calling
    if "gpt-" in model and self._llm.supports_tools():
        return await self._call_openai_tools(messages)
    
    # Anthropic tool_use
    if "claude" in model and self._llm.supports_tools():
        return await self._call_anthropic_tools(messages)
    
    # 回退: ReAct JSON
    return await self._call_react_json(messages)
```

**工时:** 8h | **风险:** 中 | **文件:** 修改 1 + 测试 1

---

## 五、P3 — 数据与智能 (v0.9)

> **目标:** 数据层现代化 + 向量化检索  
> **工时:** ~24h | **风险:** 低

### 5.1 SQLAlchemy 统一 + Alembic 迁移

**步骤:**

1. **安装依赖:** `pip install alembic`
2. **初始化:** `alembic init alembic` 在项目根目录
3. **迁移 `unified_db.py` — 将所有 sqlite3 操作改为 SQLAlchemy ORM**
4. **迁移 `recommendation/engine.py` — 统一 Session 管理**
5. **配置 `alembic/env.py` — 指向 `pycoder.db`**

```python
# alembic/env.py 关键配置:
from pycoder.server.unified_db import get_db_path, Base
target_metadata = Base.metadata
sqlalchemy.url = f"sqlite:///{get_db_path()}"
```

**工时:** 8h | **风险:** 中（数据迁移需谨慎）| **文件:** 修改 3 + 新建 alembic 配置

---

### 5.2 向量化 RAG 上下文检索

新建 `pycoder/server/services/rag_retriever.py`:

```python
"""P3: RAG — 基于向量检索的智能上下文查找

使用 ChromaDB 或 lanceDB 做 embedding 存储。
Agent 可以语义搜索相关代码片段，替代滑窗+全文搜索。
"""

class RAGRetriever:
    def __init__(self, workspace: Path):
        import chromadb
        self._client = chromadb.PersistentClient(
            path=str(workspace / ".pycoder" / "chroma")
        )
        self._collection = self._client.get_or_create_collection("pycoder_code")
        self._workspace = workspace
    
    def index_file(self, file_path: str) -> None:
        """索引单个文件（切片 + embedding）"""
        ...
    
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """语义搜索相关代码片段"""
        ...
```

**工时:** 16h | **风险:** 中（新增 ChromaDB 依赖）| **文件:** 新建 2

---

## 六、验收标准

每个版本的验收门槛:

### v0.6 验收

- [ ] `test_di_container.py` — 6 个测试全部通过
- [ ] `test_port_injection.py` — 违规导入检测通过，关键模块引用 LLMProvider
- [ ] `test_repomap.py` — 标签提取 + PageRank + 集成测试通过
- [ ] `autonomous_pipeline.py` / `task_decomposer.py` / `unified_agent.py` 不直接 import ChatBridge
- [ ] `subprocess_sandbox.py` 不 import server 层
- [ ] RepoMap 在 100+ 文件项目中返回有效上下文（不超过 token 预算）
- [ ] 全量测试套件通过（排除 test_learning_system）

### v0.7 验收

- [ ] Plan 模式下无法执行 write_file/terminal/execute 工具
- [ ] Memory Bank 文件自动创建，重启后内容保留
- [ ] TaskClassifier 支持 LLM 二次分类（至少 80% 准确率）
- [ ] Claude/Gemini 模型可注册并使用
- [ ] 自主模式下 `rm -rf /path` 被拦截
- [ ] 危险命令永久禁止模式不依赖客户端判断

### v0.8 验收

- [ ] Docker 沙箱执行代码，容器无网络访问
- [ ] OpenAI tool calling 格式 LLM 正确响应
- [ ] Anthropic tool_use 格式 LLM 正确响应
- [ ] 子进程沙箱仍然可用（回退方案）

### v0.9 验收

- [ ] Alembic `upgrade head` 成功创建所有表
- [ ] 所有 sqlite3 操作改为 SQLAlchemy ORM
- [ ] RAG 检索返回语义相关的代码片段
- [ ] 向量索引增量更新，不阻塞

---

## 七、风险与回滚

### 高风险项

| 项 | 风险 | 缓解 |
|----|------|------|
| DI 容器全局状态 | 多线程测试可能互相污染 | `registry.clear()` + pytest fixture |
| RepoMap 大项目性能 | 1000+ 文件扫描可能慢 | 文件哈希缓存 + 增量更新 |
| Alembic 数据迁移 | SQLite schema 变更可能破坏数据 | 迁移前自动备份 pycoder.db |
| 模型路由 LLM 分类 | LLM 不可用时回退 | 三层 fallback: LLM→关键词→默认 |

### 回滚方案

每个版本的修改都在独立分支上开发：
```bash
git checkout -b feat/v0.6-di-arch
git checkout -b feat/v0.7-plan-memory
git checkout -b feat/v0.8-docker-tools
git checkout -b feat/v0.9-data-rag
```

任一版本测试不通过，直接放弃该分支，不影响其他工作。

---

## 附录: 文件变更清单

| 文件 | 操作 | 版本 | 工时 |
|------|:----:|:----:|:----:|
| `pycoder/core/di.py` | 新建 | v0.6 | 4h |
| `pycoder/core/ports/llm_provider.py` | 修改 | v0.6 | 2h |
| `pycoder/server/app.py` | 修改 | v0.6 | 3h |
| `pycoder/server/services/autonomous_pipeline.py` | 修改 | v0.6 | 4h |
| `pycoder/server/services/task_decomposer.py` | 修改 | v0.6 | 3h |
| `pycoder/server/services/unified_agent.py` | 修改 | v0.6+v0.7 | 6h |
| `pycoder/adapters/subprocess_sandbox.py` | 修改 | v0.6 | 2h |
| `pycoder/python/repomap.py` | 新建 | v0.6 | 12h |
| `pycoder/server/memory_bank.py` | 新建 | v0.7 | 6h |
| `pycoder/server/services/model_router.py` | 修改 | v0.7 | 6h |
| `pycoder/adapters/anthropic_provider.py` | 新建 | v0.7 | 4h |
| `pycoder/server/permission_policy.py` | 修改 | v0.7 | 6h |
| `pycoder/adapters/docker_sandbox.py` | 新建 | v0.8 | 8h |
| `pycoder/server/services/agent_react_loop.py` | 修改 | v0.8 | 8h |
| `pycoder/server/unified_db.py` | 修改 | v0.9 | 4h |
| `alembic/` 配置 | 新建 | v0.9 | 4h |
| `pycoder/server/services/rag_retriever.py` | 新建 | v0.9 | 16h |
| **新增测试文件** (5个) | 新建 | 全版本 | 10h |
| **总计** | 11 新建 + 10 修改 | — | **~108h** |

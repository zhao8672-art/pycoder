# PyCoder 七大局限性完美升级方案

> 版本: 2.0 | 日期: 2026-07-17 | 对应: PyCoder v0.5.0

---

## 总览

本文针对 PyCoder 当前明确的 7 项局限性，给出**可落地、可验证、渐进式**的完美升级方案。每项包含技术架构、实施路径、代码示例和预期效果。

### 升级优先级

| 优先级 | 局限性 | 用户价值 | 预估工时 | 技术难度 |
|--------|--------|---------|---------|---------|
| **P0** | 🌐 无联网能力 | 极高 | ✅ 已实现 | - |
| **P0** | ⏳ 上下文窗口有限 | 高 | ✅ 已实现 | - |
| **P1** | 📁 文件系统局限 | 高 | 1 天 | 低 |
| **P1** | 🖼️ 没有图形界面 | 中 | 1 天 | 中 |
| **P2** | 🔄 非实时性 | 中 | 2 天 | 中 |
| **P2** | 📦 依赖环境准确性 | 中 | 1 天 | 低 |
| **P3** | 📚 知识截止 | 低 | 0.5 天 | 低 |

---

## P0: 🌐 无联网能力 ✅ （已完成）

### 现状

PyCoder 已具备完整的联网能力：

| 能力 | 状态 | 方式 |
|------|------|------|
| 网页抓取 | ✅ 已实现 | `FetchEngine` — httpx 直连 + Playwright 降级 |
| 联网搜索 | ✅ 已实现 | `SearchIntegration` — DuckDuckGo / SearXNG / Tavily |
| 内容提取 | ✅ 已实现 | `ContentExtractor` — HTML→Markdown |
| 网页截图 | ✅ 已实现 | Playwright 完整页面截图 |
| AI 工具 | ✅ 已实现 | `web_fetch` / `web_search` / `web_screenshot` |
| REST API | ✅ 已实现 | `POST /api/web/fetch|search|screenshot` |

### 如何使用

```
AI 对话中直接说:
  "搜索一下最新的 Python 3.14 特性"
  "帮我抓取这个网页的内容: https://... "
  "搜索 DeepSeek API 的最新价格"
```

---

## P0: ⏳ 上下文窗口有限 ✅ （已完成）

### 现状

| 能力 | 状态 | 方式 |
|------|------|------|
| 精确 Token 计数 | ✅ 已实现 | `TokenCounter` — tiktoken (cl100k_base) |
| 消息滑窗截断 | ✅ 已实现 | `max_history_messages=20` 可配置 |
| 记忆压缩 | ✅ 已实现 | AgentMemoryManager — 事实提取 + 摘要 |
| 上下文锚点 | ✅ 已实现 | ContextOrchestrator — 任务目标/进度注入 |
| Token 预算预警 | ✅ 已实现 | 超过 60K token 自动警告 |

---

## P1: 📁 文件系统局限（1 天）

### 目标

让 AI 能访问和操作**工作区之外的目录**（用户授权的沙箱路径）。

### 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                FileSystemManager                            │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  Mapped Paths     │  │  Permission      │               │
│  │  ├─ 工作区(默认)   │  │  ├─ 只读/读写    │               │
│  │  ├─ 用户映射路径  │  │  ├─ 路径白名单   │               │
│  │  └─ 临时目录      │  │  └─ 大小限制     │               │
│  └────────┬──────────┘  └────────┬─────────┘               │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  Unified File Operations                   │              │
│  │  ├─ read_file(path)     → 任意授权路径     │              │
│  │  ├─ write_file(path)    → 仅授权写入路径   │              │
│  │  ├─ list_dir(path)      → 任意授权路径     │              │
│  │  ├─ search_files(glob)  → 递归搜索         │              │
│  │  └─ get_file_info(path) → 元数据           │              │
│  └──────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

### 新增文件

| 文件 | 职责 |
|------|------|
| `pycoder/fs/__init__.py` | 模块入口 |
| `pycoder/fs/path_mapper.py` | 路径映射管理（注册授权路径 + 沙箱化） |
| `pycoder/fs/permission_policy.py` | 权限策略（读写/只读/白名单/大小限制） |
| `pycoder/fs/unified_ops.py` | 统一文件操作（跨路径的读写/搜索/元数据） |
| `pycoder/server/routers/fs_routes.py` | REST API（路径映射管理 + 文件操作） |
| `settings` 面板扩展 | 前端 UI 管理映射路径 |

### 关键实现

```python
# fs/path_mapper.py
class PathMapper:
    """路径映射管理器 — 将用户授权路径映射为 AI 可访问路径"""

    def __init__(self):
        self._mappings: dict[str, PathEntry] = {}
        self._load_from_config()

    def register(self, alias: str, real_path: str, permission: str = "read") -> bool:
        """注册一个授权路径

        Args:
            alias: 路径别名 (如 "documents")
            real_path: 真实路径 (如 "C:\\Users\\xxx\\Documents")
            permission: "read" | "write" | "deny"
        """
        if not os.path.exists(real_path):
            return False
        self._mappings[alias] = PathEntry(
            alias=alias, real_path=real_path, permission=permission,
        )
        self._save_to_config()
        return True

    def resolve(self, ai_path: str) -> str | None:
        """将 AI 请求的路径解析为真实路径（含安全检查）"""
        # ai_path 格式: "fs://documents/project/main.py"
        # 或 "/documents/project/main.py"
        if ai_path.startswith("fs://"):
            alias = ai_path[5:].split("/")[0]
            relative = "/".join(ai_path[5:].split("/")[1:])
        else:
            parts = ai_path.strip("/").split("/")
            alias = parts[0] if parts else ""
            relative = "/".join(parts[1:]) if len(parts) > 1 else ""

        entry = self._mappings.get(alias)
        if not entry:
            return None

        real = os.path.normpath(os.path.join(entry.real_path, relative))
        # 安全检查：防止路径穿越
        if not real.startswith(os.path.normpath(entry.real_path)):
            return None
        return real


# fs/unified_ops.py
class UnifiedFileOps:
    """统一文件操作 — 跨路径的读写/搜索/元数据"""

    def __init__(self, mapper: PathMapper):
        self._mapper = mapper

    async def read_file(self, path: str) -> dict:
        """读取文件（自动解析 fs:// 路径）"""
        real_path = self._resolve(path)
        if not real_path:
            return {"success": False, "error": "路径未授权"}
        try:
            with open(real_path, encoding="utf-8") as f:
                content = f.read()
            return {"success": True, "path": real_path, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_files(self, pattern: str, root: str = "") -> list[str]:
        """递归搜索文件（跨路径）"""
        results = []
        roots = [root] if root else [e.real_path for e in self._mapper.list()]
        for r in roots:
            for match in glob.glob(os.path.join(r, "**", pattern), recursive=True):
                results.append(match)
        return results
```

### AI 工具注册

```python
FS_TOOLS = [
    {
        "name": "fs_read_file",
        "description": "读取文件（支持 fs:// 别名路径和工作区外授权路径）",
        "parameters": {
            "path": {"type": "string", "description": "文件路径，如 fs://documents/readme.md"},
        },
    },
    {
        "name": "fs_list_dir",
        "description": "列出目录内容",
        "parameters": {
            "path": {"type": "string"},
        },
    },
    {
        "name": "fs_search",
        "description": "按模式搜索文件，如 **/*.py",
        "parameters": {
            "pattern": {"type": "string"},
        },
    },
]
```

---

## P1: 🖼️ 没有图形界面（1 天）

### 目标

让 AI 能生成并展示可视化内容，而不只是输出文本或 HTML 文件。

### 架构

```
┌────────────────────────────────────────────────────────────┐
│                Visualization Engine                         │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  Chart Generator  │  │  Dashboard       │               │
│  │  ├─ matplotlib    │  │  ├─ HTML 模板     │               │
│  │  ├─ plotly        │  │  ├─ 实时数据绑定  │               │
│  │  └─ mermaid       │  │  └─ 导出 PDF     │               │
│  └────────┬──────────┘  └────────┬─────────┘               │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  Inline Preview Protocol                   │              │
│  │  ├─ AI → WebSocket → 前端渲染              │              │
│  │  ├─ 支持: SVG / Plotly JSON / Mermaid     │              │
│  │  └─ 前端组件: ChartPreview + MermaidView  │              │
│  └──────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

### 关键实现

```python
# ai/visual/engine.py
class VisualizationEngine:
    """可视化引擎 — 让 AI 能生成并展示图表"""

    async def render_mermaid(self, mermaid_code: str) -> str:
        """渲染 Mermaid 图表 → Base64 SVG"""
        try:
            from pycoder.server.services.mermaid_renderer import render
            svg = await render(mermaid_code)
            return f"data:image/svg+xml;base64,{base64.b64encode(svg).decode()}"
        except ImportError:
            return ""

    async def render_plotly(self, figure_json: dict) -> str:
        """渲染 Plotly 图表 → 内联 HTML"""
        import plotly
        html = plotly.offline.plot(figure_json, output_type="div", include_plotlyjs=False)
        return html

    async def render_matplotlib(self, code: str) -> str:
        """执行 Python 代码生成 matplotlib 图表 → Base64 PNG"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        local_vars = {"plt": plt}
        exec(code, local_vars)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150)
        plt.close()
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
```

### 前端集成

在 AI 回复中嵌入特殊标记，Electron 前端自动渲染：

```
AI 回复中包含:
  <!--mermaid-->
  graph TD; A-->B; B-->C;
  <!--/mermaid-->

  或:
  <!--plotly-->
  {"data": [{"x": [1,2,3], "y": [4,5,6], "type": "scatter"}]}
  <!--/plotly-->
```

### AI 工具注册

```python
VIZ_TOOLS = [
    {
        "name": "viz_mermaid",
        "description": "生成 Mermaid 图表（流程图/时序图/类图）",
        "parameters": {
            "code": {"type": "string", "description": "Mermaid 代码"},
        },
    },
    {
        "name": "viz_chart",
        "description": "生成数据图表（柱状图/折线图/饼图）",
        "parameters": {
            "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "scatter"]},
            "data": {"type": "array"},
            "title": {"type": "string"},
        },
    },
]
```

---

## P2: 🔄 非实时性（2 天）

### 目标

赋予 PyCoder 文件监听、定时任务、事件驱动的能力。

### 架构

```
┌────────────────────────────────────────────────────────────┐
│                Event & Watch System                         │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  File Watcher     │  │  Task Scheduler  │               │
│  │  ├─ watchdog      │  │  ├─ 定时执行      │               │
│  │  ├─ 文件变化事件  │  │  ├─ 间隔执行      │               │
│  │  └─ 目录递归监控  │  │  └─ CRON 表达式  │               │
│  └────────┬──────────┘  └────────┬─────────┘               │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  Event Bus                                │              │
│  │  ├─ file_changed → 自动分析差异           │              │
│  │  ├─ timer_trigger → 执行预定义动作         │              │
│  │  └─ notification → WebSocket 推送到前端    │              │
│  └──────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

### 关键实现

```python
# services/watch_service.py
class WatchService:
    """文件监控服务 — 文件变化自动触发 AI 分析"""

    def __init__(self):
        self._watchers: dict[str, object] = {}
        self._handlers: dict[str, list] = {}

    async def watch_directory(self, path: str,
                              on_change: callable = None,
                              pattern: str = "*.py") -> bool:
        """监控目录变化"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class AIHandler(FileSystemEventHandler):
                def on_modified(self, event):
                    if event.is_directory:
                        return
                    asyncio.create_task(on_change(event.src_path))

            observer = Observer()
            handler = AIHandler()
            observer.schedule(handler, path, recursive=True)
            observer.start()
            self._watchers[path] = observer
            return True
        except ImportError:
            return False

    async def stop_watching(self, path: str):
        if path in self._watchers:
            self._watchers[path].stop()
            del self._watchers[path]


# services/scheduler_service.py
class SchedulerService:
    """轻量任务调度器 — 定时/间隔触发 AI 操作"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    async def schedule(self, name: str, cron_expr: str, action: callable):
        """注册定时任务"""
        # 使用简单间隔（后续可升级为 croniter）
        self._tasks[name] = asyncio.create_task(self._loop(name, cron_expr, action))

    async def _loop(self, name: str, interval_sec: int, action: callable):
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await action()
            except Exception as e:
                logger.error(f"定时任务 {name} 失败: {e}")
```

### AI 工具注册

```python
WATCH_TOOLS = [
    {
        "name": "watch_file",
        "description": "监控文件变化，变化时自动分析",
        "parameters": {
            "path": {"type": "string"},
            "pattern": {"type": "string", "description": "文件匹配模式, 如 *.py"},
        },
    },
    {
        "name": "schedule_task",
        "description": "创建定时任务，定期执行某个操作",
        "parameters": {
            "name": {"type": "string"},
            "interval_seconds": {"type": "integer"},
            "action_description": {"type": "string"},
        },
    },
]
```

---

## P2: 📦 依赖环境准确性（1 天）

### 目标

AI 能自动检测并安装缺失的依赖，确保代码可执行。

### 架构

```
┌────────────────────────────────────────────────────────────┐
│              Dependency Manager                              │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐                                     │
│  │  Auto Detect      │                                     │
│  │  ├─ 扫描代码中import │                                   │
│  │  ├─ 对比已安装包   │                                     │
│  │  └─ 生成缺失列表    │                                     │
│  └────────┬──────────┘                                     │
│           │                                                  │
│           ▼                                                  │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  Install Strategy │  │  Verification    │               │
│  │  ├─ pip install   │  │  ├─ import 验证   │               │
│  │  ├─ 分步安装      │  │  ├─ 版本兼容检查  │               │
│  │  └─ 失败回滚      │  │  └─ 耗时约束      │               │
│  └───────────────────┘  └──────────────────┘               │
└────────────────────────────────────────────────────────────┘
```

### 关键实现

```python
# services/dep_checker.py
class DependencyChecker:
    """自动依赖检测与安装"""

    COMMON_MAP = {
        "pandas": "pandas",
        "numpy": "numpy",
        "matplotlib": "matplotlib",
        "PIL": "pillow",
        "cv2": "opencv-python",
        "requests": "requests",
        "flask": "flask",
        "fastapi": "fastapi",
        "tensorflow": "tensorflow",
        "torch": "torch",
        "sklearn": "scikit-learn",
        "selenium": "selenium",
        "playwright": "playwright",
    }

    async def check_code(self, code: str) -> list[str]:
        """分析代码中的 import 语句，返回缺失的包名"""
        import ast
        tree = ast.parse(code)
        missing = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = self._resolve_package(alias.name)
                    if pkg and not self._is_installed(pkg):
                        missing.append(pkg)
            elif isinstance(node, ast.ImportFrom):
                pkg = self._resolve_package(node.module or "")
                if pkg and not self._is_installed(pkg):
                    missing.append(pkg)
        return list(set(missing))

    def _resolve_package(self, module_name: str) -> str | None:
        """模块名 → pip 包名"""
        return self.COMMON_MAP.get(module_name.split(".")[0])

    def _is_installed(self, package: str) -> bool:
        try:
            import importlib.metadata
            importlib.metadata.distribution(package)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False

    async def auto_install(self, packages: list[str]) -> dict:
        """自动安装缺失依赖"""
        results = {}
        for pkg in packages:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pip", "install", pkg,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                results[pkg] = {"success": proc.returncode == 0}
            except Exception as e:
                results[pkg] = {"success": False, "error": str(e)}
        return results
```

### AI 工具

```python
DEP_TOOLS = [
    {
        "name": "check_deps",
        "description": "检查代码依赖是否完整，自动安装缺失包",
        "parameters": {
            "code": {"type": "string", "description": "要检查的代码"},
        },
    },
]
```

---

## P3: 📚 知识截止（0.5 天）

### 目标

让 AI 的知识包（Skills）保持最新。

### 方案

```python
# services/skills_updater.py
class SkillsAutoUpdater:
    """知识包自动刷新"""

    async def refresh_if_stale(self, max_age_hours: int = 24):
        """检查知识包时效，超过 24 小时自动刷新"""
        registry_path = Path.home() / ".pycoder" / "skills_registry.json"
        if registry_path.exists():
            age = time.time() - registry_path.stat().st_mtime
            if age > max_age_hours * 3600:
                await self._refresh()

    async def _refresh(self):
        from pycoder.server.app import get_v2_engine
        v2 = get_v2_engine()
        if v2:
            await v2.registry.call("tools_marketplace_skills_sync", {})
```

### 升级建议

在 `start_backend.bat` 或 `app.py` 启动时加入：

```python
# app.py 启动时
asyncio.create_task(SkillsAutoUpdater().refresh_if_stale())
```

---

## 实施路线图

| 阶段 | 时间 | 内容 | 交付物 |
|------|------|------|--------|
| **Phase 0** | ✅ 已完成 | 联网搜索 + 长上下文 | `pycoder/web/` + `TokenCounter` |
| **Phase 1** | 第 1 天 | 📁 文件系统扩展 | `pycoder/fs/` — 路径映射 + 跨目录访问 |
| **Phase 1** | 第 1 天 | 🖼️ 可视化引擎 | `pycoder/ai/visual/` — Mermaid/Plotly/matplotlib 内联渲染 |
| **Phase 2** | 第 2-3 天 | 🔄 文件监听 + 定时任务 | `WatchService` + `SchedulerService` |
| **Phase 2** | 第 2 天 | 📦 依赖自动检测 | `DependencyChecker` — 扫描→安装→验证 |
| **Phase 3** | 第 0.5 天 | 📚 知识包自动刷新 | `SkillsAutoUpdater` |

### 预计新增代码

| 模块 | 文件数 | 代码行数 |
|------|--------|---------|
| `pycoder/fs/` | ~5 | ~600 |
| `pycoder/ai/visual/` | ~3 | ~400 |
| Watch + Scheduler | ~3 | ~500 |
| Dependency Checker | ~2 | ~300 |
| Skills Updater | ~1 | ~80 |
| **总计** | **~14** | **~1880** |

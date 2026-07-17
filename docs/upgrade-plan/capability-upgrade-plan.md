# PyCoder 能力升级方案 — 突破六大局限性

> 版本: 1.0 | 日期: 2026-07-17 | 对应版本: PyCoder v0.5.0

---

## 总览

本文档系统性地提出了**6 项核心局限性的升级方案**，每项包含技术选型、架构设计、实施计划和预期效果。

### 升级优先级矩阵

| 优先级 | 能力 | 用户价值 | 实施难度 | 预估工时 |
|--------|------|---------|---------|---------|
| **P0** | 🌐 联网搜索 | 极高 | 低 | 1 天 |
| **P1** | 🖼️ 多模态（图像） | 高 | 中 | 2 天 |
| **P1** | 📏 长上下文优化 | 高 | 低 | 1 天 |
| **P2** | ⏱️ 并行任务执行 | 中 | 中 | 2 天 |
| **P2** | 🔌 MCP 工具生态 | 中 | 中 | 2 天 |
| **P3** | 📡 实时流式场景 | 低 | 高 | 3 天 |

---

## P0: 🌐 联网搜索（1 天）

### 目标

让 PyCoder 具备实时获取互联网信息的能力，不再局限于训练数据的知识截止日期。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `pycoder/browser/browser_pool.py` | 高 | Playwright 浏览器池，支持预热/回收/并发 |
| `pycoder/browser/access_control.py` | 高 | URL 白名单/黑名单，速率限制 |
| `pycoder/net/client.py` | 高 | 共享 httpx.AsyncClient 连接池 |
| `pycoder/server/services/browser_inspector.py` | 中 | 浏览器检查工具，需要扩展为通用抓取 |
| `pycoder/server/mcp_tools.py` | 中 | MCP 客户端管理器可连接外部抓取服务 |

### 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                    WebSearchEngine                          │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  Layer 1: HTTP  │  │  Layer 2: Head- │                  │
│  │  Fetch (httpx)  │──│  less Browser   │                  │
│  │  ● 通用URL抓取  │  │  (Playwright)   │                  │
│  │  ● 响应式+静态  │  │  ● JS渲染页面   │                  │
│  │  ● 超时/重试    │  │  ● 截图+HTML   │                  │
│  └────────┬────────┘  └────────┬────────┘                  │
│           │                     │                           │
│           ▼                     ▼                           │
│  ┌─────────────────────────────────────────┐               │
│  │      Content Extractor                   │               │
│  │  ● HTML → Markdown (html2text/markitdown)│              │
│  │  ● 正文提取 (Readability/trafilatura)   │               │
│  │  ● 结构化输出 (标题/正文/链接/表格)     │               │
│  └───────────────────┬─────────────────────┘               │
│                      │                                      │
│                      ▼                                      │
│  ┌─────────────────────────────────────────┐               │
│  │      Search Integration                  │               │
│  │  ● SearXNG (自建元搜索)                   │               │
│  │  ● DuckDuckGo (免费API)                  │               │
│  │  ● Tavily (专为AI优化的搜索API)           │               │
│  └─────────────────────────────────────────┘               │
└────────────────────────────────────────────────────────────┘
```

### 新增文件

| 文件 | 职责 | 预估行数 |
|------|------|---------|
| `pycoder/web/__init__.py` | 模块入口 | 20 |
| `pycoder/web/fetch_engine.py` | HTTP 抓取引擎（httpx + Playwright 自动降级） | 250 |
| `pycoder/web/content_extractor.py` | 内容提取（HTML→Markdown 转换） | 200 |
| `pycoder/web/search_integration.py` | 搜索引擎集成（DuckDuckGo/SearXNG/Tavily） | 200 |
| `pycoder/web/browser_agent.py` | AI 驱动的浏览器操作代理 | 300 |
| `pycoder/web/tool_definitions.py` | AI 可调用的工具注册表 | 100 |
| `pycoder/server/routers/web_routes.py` | REST API 端点 | 100 |

**总计: 约 1170 行**

### 关键实现

```python
# web/fetch_engine.py - 核心抓取引擎
class FetchEngine:
    """双层抓取引擎 — HTTP 直连 + Headless Browser 降级"""

    async def fetch(self, url: str, timeout: int = 15) -> FetchResult:
        # Layer 1: httpx 快速直连
        try:
            return await self._http_fetch(url, timeout)
        except (httpx.TimeoutException, NeedJSError):
            # Layer 2: Playwright 降级（需要 JS 渲染）
            return await self._browser_fetch(url, timeout)

    async def _http_fetch(self, url: str, timeout: int) -> FetchResult:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as c:
            resp = await c.get(url, headers={"User-Agent": self._ua})
            resp.raise_for_status()
            return FetchResult(url=url, html=resp.text, status=resp.status_code)

    async def _browser_fetch(self, url: str, timeout: int) -> FetchResult:
        page = await self._browser_pool.get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        html = await page.content()
        screenshot = await page.screenshot(full_page=True)
        return FetchResult(url=url, html=html, screenshot=screenshot)

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        """通过搜索引擎获取实时信息"""
        return await self._search.search(query, num_results)


# web/tool_definitions.py - AI 工具注册
WEB_TOOLS = [
    {
        "name": "web_fetch",
        "description": "获取网页内容（自动处理 JS 渲染和内容提取）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标 URL"},
                "extract_text": {"type": "boolean", "description": "是否提取纯文本"},
            },
        },
    },
    {
        "name": "web_search",
        "description": "联网搜索获取最新信息",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "num_results": {"type": "integer", "description": "返回结果数量"},
            },
        },
    },
    {
        "name": "web_screenshot",
        "description": "对网页截图（用于视觉分析页面布局）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标 URL"},
            },
        },
    },
]
```

### 测试计划

| 测试 | 类型 | 说明 |
|------|------|------|
| `test_fetch_static_page` | 单元 | 抓取 GitHub 静态页面 |
| `test_fetch_dynamic_page` | 集成 | 抓取 SPA 页面（需 Playwright） |
| `test_content_extraction` | 单元 | HTML→Markdown 转换正确性 |
| `test_search_integration` | 集成 | DuckDuckGo API 搜索 |
| `test_browser_screenshot` | 集成 | 网页截图功能 |

---

## P1: 🖼️ 多模态（图像）— 2 天

### 目标

让 PyCoder 能"看懂"图片内容，支持 OCR 文字识别、图像语义分析、UI 截图理解。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `pycoder/server/services/multimodal_perception.py` | 高 | `ImageAnalyzer`、`VisionModelClient` 基本可用 |
| `pycoder/providers/registry.py` | 高 | 已定义 `supports_vision` 模型标记 |
| `pycoder/gateway/adapters/` | 中 | 支持 `image` 消息类型 |

### 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                   MultimodalEngine                          │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  OCR Engine     │  │  Vision LLM     │                  │
│  │  ├─ Tesseract   │  │  ├─ DeepSeekVL  │                  │
│  │  ├─ PaddleOCR   │  │  ├─ GPT-4V      │                  │
│  │  └─ LLM 回退    │  │  └─ Qwen-VL     │                  │
│  └───────┬─────────┘  └───────┬─────────┘                  │
│          │                     │                             │
│          ▼                     ▼                             │
│  ┌─────────────────────────────────────────┐               │
│  │      Image Analysis Pipeline              │               │
│  │  ● MetaData → EXIF → Color → Composition │              │
│  │  ● Screenshot → UI Detection → Action    │              │
│  │  ● Chart → Data Extraction               │              │
│  └─────────────────────────────────────────┘               │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │      AI 工具注册                          │               │
│  │  image_analyze / image_ocr / screenshot  │              │
│  └─────────────────────────────────────────┘               │
└────────────────────────────────────────────────────────────┘
```

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `pycoder/multimodal/__init__.py` | 模块入口 |
| `pycoder/multimodal/ocr_engine.py` | 统一 OCR 引擎（Tesseract + PaddleOCR + LLM 回退） |
| `pycoder/multimodal/vision_client.py` | 从 `multimodal_perception.py` 提取并注册为 V2 能力 |
| `pycoder/multimodal/image_analyzer.py` | 图像分析管线（元数据/颜色/构成/图表） |
| `pycoder/multimodal/tool_definitions.py` | AI 可调用工具注册 |
| `pycoder/server/routers/media_routes.py` | REST API 端点 |
| `pycoder/server/services/multimodal_perception.py` | 重构：委托给 `pycoder/multimodal/` 新模块 |

### 关键实现

```python
# multimodal/ocr_engine.py
class OCREngine:
    """多层 OCR 引擎 — Tesseract → PaddleOCR → LLM 视觉回退"""

    def __init__(self):
        self._tesseract = self._try_init_tesseract()
        self._paddle = self._try_init_paddle()
        self._vision_client = None  # 延迟初始化

    async def extract_text(self, image: Image.Image) -> str:
        # Layer 1: Tesseract (最快, 0.5-2s)
        if self._tesseract:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            if text.strip():
                return text
        # Layer 2: PaddleOCR (更准确, 1-3s)
        if self._paddle:
            result = self._paddle.ocr(np.array(image))
            text = "\n".join([line[1][0] for block in result for line in block])
            if text.strip():
                return text
        # Layer 3: LLM 视觉模型 (最准确, 3-8s)
        return await self._vision_llm_ocr(image)

    async def _vision_llm_ocr(self, image: Image.Image) -> str:
        if not self._vision_client:
            from pycoder.multimodal.vision_client import VisionClient
            self._vision_client = VisionClient()
        return await self._vision_client.ocr(image)
```

---

## P1: 📏 长上下文优化（1 天）

### 目标

解决多轮对话后丢失早期信息的问题，实现精确 token 计数的滑动窗口。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `chat_bridge.py:_get_effective_messages()` | 高 | 已实现消息截断 + 记忆压缩框架 |
| `agent_memory.py:AgentMemoryManager` | 高 | 三层记忆（事实提取/摘要/持久化） |
| `context_orchestrator.py` | 中 | 上下文锚点需要进一步集成 |

### 架构设计

```
当前消息列表 (N 条)
    │
    ├─ Token 精确计数 (tiktoken)
    │
    ├─ 小于上下文窗口 70%?
    │   └─ ✅ 全部保留，无需截断
    │
    ├─ 大于 70%?
    │   ├─ Step 1: 压缩旧消息为摘要 (LLM-driven)
    │   ├─ Step 2: 保留最近 K 条完整消息
    │   └─ Step 3: 注入上下文锚点 (任务目标 + 进度)
    │
    └─ 大于 100%?
        ├─ Step 1: 紧急摘要 (全量压缩)
        ├─ Step 2: 保留最关键的最近 N 条
        └─ Step 3: 发出 "上下文将满" 提示
```

### 修改文件

| 文件 | 变更 |
|------|------|
| `pycoder/server/chat_bridge.py` | 替换 `len//3` 估算为 tiktoken 精确计数；增加三级压缩策略 |
| `pycoder/server/services/agent_memory.py` | 增加 LLM 驱动的语义摘要（当前仅规则提取） |
| `pycoder/requirements/requirements.in` | 添加 `tiktoken>=0.7.0` |

### 关键实现

```python
# 在 chat_bridge.py 中新增 TokenCounter
class TokenCounter:
    """精确 Token 计数器 — 使用 tiktoken"""

    _encoders: dict[str, object] = {}

    @classmethod
    def count(cls, text: str, model: str = "deepseek-chat") -> int:
        try:
            encoding = cls._get_encoding(model)
            return len(encoding.encode(text))
        except (ImportError, KeyError, ValueError):
            return len(text) // 3  # 降级估算

    @classmethod
    def truncate(cls, text: str, max_tokens: int, model: str = "deepseek-chat") -> str:
        try:
            encoding = cls._get_encoding(model)
            tokens = encoding.encode(text)
            return encoding.decode(tokens[:max_tokens])
        except (ImportError, KeyError):
            return text[:max_tokens * 3]  # 降级截断

    @classmethod
    def _get_encoding(cls, model: str):
        if model not in cls._encoders:
            import tiktoken
            cls._encoders[model] = tiktoken.encoding_for_model(
                "gpt-4"  # DeepSeek 兼容 cl100k_base
            )
        return cls._encoders[model]


# 三级压缩策略
async def _compress_old_messages_v2(self, messages: list[dict]) -> list[dict]:
    total_tokens = TokenCounter.count(json.dumps(messages))
    max_context = self.config.max_context_tokens or 65536
    threshold_70 = int(max_context * 0.7)

    if total_tokens <= threshold_70:
        return messages  # Level 0: 无需压缩

    if total_tokens <= max_context:
        # Level 1: 压缩最旧的 50% 为摘要
        split = len(messages) // 2
        old_part = messages[:split]
        recent_part = messages[split:]
        summary = await self._summary_llm(old_part)
        return [{"role": "system", "content": f"上文摘要: {summary}"}] + recent_part

    # Level 2: 紧急压缩 — 全量摘要 + 仅保留最后 5 条
    summary = await self._summary_llm(messages[:-5])
    return [{"role": "system", "content": f"全量摘要: {summary}"}] + messages[-5:]
```

---

## P2: ⏱️ 并行任务执行（2 天）

### 目标

让 PyCoder 能"同时"处理多个独立任务，大幅提升大型重构/多文件分析/批量测试等场景的效率。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `brain/dag_scheduler.py` | 高 | DAG 并行引擎 + 拓扑排序 |
| `brain/adaptive_executor.py` | 高 | 自适应迭代循环 |
| `brain/agent_swarm.py` | 高 | 多 Agent 并行协作 |
| `brain/intelligent_router.py` | 中 | `max_concurrent_tools: int = 5` |

### 架构设计

```
用户请求 (如: "重构整个项目")
    │
    ▼
TaskDecomposer (AI 驱动)
    │  "这个重构需要修改 8 个文件，分成 3 个独立步骤"
    │
    ▼
DAG Builder (依赖分析)
    ├─ Group 1: [分析模块A, 分析模块B] ← 可并行
    ├─ Group 2: [重构A(依赖A结果), 重构B(依赖B结果)]
    └─ Group 3: [集成测试A+B] ← 需等待全部完成
    │
    ▼
DAG Executor (并行执行)
    ├─ asyncio.gather(Group 1) → 2 个任务并行
    ├─ asyncio.gather(Group 2) → 2 个任务并行
    └─ Group 3 → 1 个任务
    │
    ▼
Result Merger
    ├─ 冲突检测
    └─ 结果整合
```

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `pycoder/brain/task_decomposer.py` | **新**: AI 驱动的自然语言→DAG 任务分解 |
| `pycoder/brain/dag_scheduler.py` | **改**: 增加动态优先级调整、进度回调 |
| `pycoder/brain/adaptive_executor.py` | **改**: 集成 DAG 调度器作为执行后端 |

### 关键实现

```python
# brain/task_decomposer.py
class TaskDecomposer:
    """AI 驱动的任务分解 — 自然语言 → 可并行 DAG"""

    async def decompose(self, task: str, context: dict) -> DAGPlan:
        """将自然语言任务分解为 DAG 并行计划"""
        prompt = f"""将以下任务分解为可并行执行的子任务：

任务: {task}

请按 JSON 格式输出 DAG 计划:
```json
{{
  "nodes": [
    {{"id": "task1", "description": "...", "deps": []}},
    {{"id": "task2", "description": "...", "deps": []}},
    {{"id": "task3", "description": "...", "deps": ["task1", "task2"]}}
  ]
}}
```

"""
        response = await self._call_llm(prompt)
        plan = self._parse_json(response)
        plan.parallel_groups = self._calculate_groups(plan.nodes)
        plan.estimated_speedup = self._estimate_speedup(plan)
        return plan

    def _calculate_groups(self, nodes: list[DAGNode]) -> list[list[str]]:
        """Kahn 拓扑排序 → BFS 并行分组"""
        in_degree = {n.id: len(n.deps) for n in nodes}
        adj = {n.id: [] for n in nodes}
        for n in nodes:
            for dep in n.deps:
                if dep in adj:
                    adj[dep].append(n.id)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        groups = []
        while queue:
            groups.append(list(queue))
            next_queue = []
            for nid in queue:
                for neighbor in adj.get(nid, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue
        return groups

```

---

## P2: 🔌 MCP 工具生态（2 天）

### 目标

让 MCP 外部工具连接实现自动化、可视化、持久化，降低用户的配置门槛。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `mcp_tools.py:MCPClientManager` | 高 | stdio/SSE 连接管理 |
| `ws_handler.py` | 高 | mcp_list/mcp_call/mcp_connect/mcp_disconnect |
| `capabilities/tools/` | 高 | 11 个工具模块已注册到 V2 总线 |

### 升级项

```

┌────────────────────────────────────────────────────────────┐
│              MCP Ecosystem Manager                          │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  Auto Connect     │  │  Health Check    │               │
│  │  ├─ 从config加载   │  │  ├─ 周期性ping    │               │
│  │  ├─ 启动时自动连接 │  │  ├─ 断开自动重连  │               │
│  │  └─ 重连策略      │  │  └─ 状态通知      │               │
│  └────────┬──────────┘  └────────┬─────────┘               │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  MCP Store (SQLite)                       │              │
│  │  ├─ 服务器配置持久化                       │              │
│  │  ├─ 工具调用历史审计日志                   │              │
│  │  └─ 连接状态追踪                          │              │
│  └──────────────────────────────────────────┘              │
│                                                             │
│  ┌──────────────────────────────────────────┐              │
│  │  MCP Marketplace                          │              │
│  │  ├─ 内置模板: GitHub / DB / Files / Calc  │              │
│  │  ├─ 一键连接向导                          │              │
│  │  └─ 社区模板仓库                          │              │
│  └──────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘

```

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `pycoder/server/mcp_store.py` | **新**: MCP 服务器配置和调用审计的 SQLite 存储 |
| `pycoder/server/mcp_marketplace.py` | **新**: MCP 模板市场（内置模板 + 社区仓库） |
| `pycoder/server/mcp_tools.py` | **改**: 增加自动重连、健康检查 |
| `pycoder/server/routers/mcp_routes.py` | **新**: REST API（配置管理、市场查询） |

### 关键实现

```python
# mcp_store.py - MCP 配置持久化
class MCPStore:
    """MCP 服务器配置持久化"""

    def __init__(self):
        self._db = sqlite3.connect(Path.home() / ".pycoder" / "mcp_servers.db")
        self._init_tables()

    def _init_tables(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS mcp_servers (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,  -- stdio / sse
                command TEXT,
                url TEXT,
                env_vars TEXT,       -- JSON
                auto_connect INTEGER DEFAULT 0,
                created_at REAL,
                last_connected_at REAL,
                status TEXT DEFAULT 'disconnected'
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS mcp_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server TEXT,
                tool TEXT,
                params_summary TEXT,
                success INTEGER,
                duration_ms REAL,
                created_at REAL
            )
        """)

    def get_auto_connect_servers(self) -> list[dict]:
        """获取需要自动连接的服务器列表"""
        rows = self._db.execute(
            "SELECT * FROM mcp_servers WHERE auto_connect=1 AND status!='connected'"
        ).fetchall()
        return [dict(row) for row in rows]


# mcp_marketplace.py - MCP 模板市场
MCP_MARKETPLACE = {
    "github": {
        "name": "GitHub",
        "description": "管理 Issues, PRs, Code Review",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_vars": ["GITHUB_TOKEN"],
    },
    "postgres": {
        "name": "PostgreSQL",
        "description": "数据库查询与 Schema 管理",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-postgres"],
        "env_vars": ["POSTGRES_CONNECTION_STRING"],
    },
    "filesystem": {
        "name": "文件系统",
        "description": "安全的文件读写操作（沙箱化）",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "env_vars": [],
    },
}
```

---

## P3: 📡 实时/流式场景（3 天）

### 目标

让 PyCoder 能处理实时数据流（WebSocket 行情、日志流、消息队列），从"一次性查询"模式扩展到"持续监控"模式。

### 现有基础设施

| 模块 | 可复用程度 | 说明 |
|------|-----------|------|
| `server/ws_handler.py` | 高 | 已有 WebSocket 事件循环框架 |
| `server/chat_bridge.py` | 高 | 流式 SSE 解析 |
| `gateway/adapters/` | 中 | 消息网关支持多平台 |

### 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                  StreamProcessor                              │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐  ┌──────────────────┐               │
│  │  Stream Source    │  │  Data Pipeline   │               │
│  │  ├─ WebSocket     │  │  ├─ 过滤/清洗     │               │
│  │  ├─ SSE           │  │  ├─ 聚合/窗口     │               │
│  │  ├─ Redis Pub/Sub │  │  ├─ 异常检测     │               │
│  │  └─ File Tail     │  │  └─ 告警触发     │               │
│  └────────┬──────────┘  └────────┬─────────┘               │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  AI Stream Consumer                        │              │
│  │  ├─ 周期性汇总 (每 N 条/每 T 秒触发)      │              │
│  │  ├─ 异常实时告警                           │              │
│  │  └─ 趋势分析报告生成                       │              │
│  └──────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

### 新增文件

| 文件 | 说明 |
|------|------|
| `pycoder/stream/__init__.py` | 模块入口 |
| `pycoder/stream/sources.py` | 多种流式数据源（WebSocket/SSE/Redis/File） |
| `pycoder/stream/processor.py` | 数据流处理器（过滤/聚合/窗口） |
| `pycoder/stream/ai_consumer.py` | AI 驱动的流消费引擎 |

---

## 实施路线图

| 阶段 | 时间 | 内容 | 交付物 |
|------|------|------|--------|
| **Phase 1** | 第 1 天 | P0: 联网搜索 | `web_fetch` + `web_search` 工具可用 |
| **Phase 2** | 第 2-3 天 | P1: 多模态 + 长上下文 | OCR 可用 + 精确 Token 计数 |
| **Phase 3** | 第 4-5 天 | P2: 并行任务 + MCP | 任务自动分解 + 自动连接 MCP |
| **Phase 4** | 第 6-8 天 | P3: 实时流式 + 综合测试 | 流式数据中心 + E2E 测试 |

---

## 技术债务与风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Playwright 浏览器实例内存占用高 | 中 | 中 | 实例池上限 4，空闲 60s 自动回收 |
| tiktoken 不是 DeepSeek 官方库 | 低 | 低 | DeepSeek 兼容 cl100k_base，降级方案已准备 |
| DuckDuckGo 搜索结果可能不稳定 | 中 | 中 | 支持多引擎切换（SearXNG/Tavily） |
| PaddleOCR 依赖大（~500MB） | 高 | 中 | 可选安装，默认 Tesseract + LLM 回退 |
| DAG 任务分解的 LLM 调用增加 Token 消耗 | 低 | 低 | 仅复杂任务触发，简单任务规则分解 |

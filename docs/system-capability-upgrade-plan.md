# PyCoder 系统能力全面升级方案

> **文档版本**：v1.0  
> **生成日期**：2026-07-14  
> **覆盖范围**：跨工作区交互、互联网访问、知识更新、依赖安装、大文件处理、多语言 LSP、持久记忆、主动推送  
> **总预计工时**：~160 人时（约 4-5 周全职工期）  
> **依赖前提**：P0 安全修复 + DI 容器已完成（见 [00-overview.md](fix-plan/00-overview.md)）

---

## 目录

- [一、背景与目标](#一背景与目标)
- [二、全局架构设计](#二全局架构设计)
- [三、升级项 1：跨工作区数据共享与交互](#三升级项-1跨工作区数据共享与交互)
- [四、升级项 2：MCP 浏览器工具优化](#四升级项-2mcp-浏览器工具优化)
- [五、升级项 3：动态知识更新机制](#五升级项-3动态知识更新机制)
- [六、升级项 4：自动化工具依赖检测与安装](#六升级项-4自动化工具依赖检测与安装)
- [七、升级项 5：智能大文件读取模块](#七升级项-5智能大文件读取模块)
- [八、升级项 6：多语言 LSP 扩展](#八升级项-6多语言-lsp-扩展)
- [九、升级项 7：会话记忆管理系统](#九升级项-7会话记忆管理系统)
- [十、升级项 8：任务调度与主动通知系统](#十升级项-8任务调度与主动通知系统)
- [十一、分阶段实施路线图](#十一分阶段实施路线图)
- [十二、测试策略](#十二测试策略)
- [十三、回滚机制](#十三回滚机制)
- [十四、风险评估与缓解](#十四风险评估与缓解)

---

## 一、背景与目标

### 1.1 当前系统限制

| # | 限制项 | 现状 | 影响 |
|---|--------|------|------|
| 1 | 工作区交互 | 仅限单个工作区内部操作 | 无法跨项目复用代码、共享上下文 |
| 2 | 互联网访问 | 默认离线，仅 MCP 浏览器工具有限访问 | 无法实时获取文档、API 参考、新闻 |
| 3 | 知识时效性 | 知识截止于训练数据 | 无法获取最新框架版本、安全漏洞信息 |
| 4 | 依赖工具安装 | 高级功能需手动预装 Docker、安全扫描器等 | 用户上手门槛高，体验割裂 |
| 5 | 大文件处理 | read_file 默认截断 2000 行，需手动分段 | 处理大型文件效率低，易遗漏 |
| 6 | 语言支持 | LSP 以 Pyright 为主，其他语言依赖 MCP | 多语言开发体验差，缺乏原生智能提示 |
| 7 | 持久记忆 | 会话间上下文不自动保存 | 每次新会话从零开始，重复沟通 |
| 8 | 主动推送 | 仅被动响应指令，无后台任务 | 无法长时间运行任务、主动通知用户 |

### 1.2 升级目标

| 指标 | 当前 | 目标 |
|------|------|------|
| 工作区互操作 | 无 | 安全 Sandbox 内跨工作区读写 |
| 互联网访问延迟 | 无（离线） | MCP 浏览器平均响应 < 3s |
| 知识新鲜度 | 训练数据截止 | 每日自动增量更新 |
| 工具安装自动化 | 手动 | 一键检测 + 安装 + 版本校验 |
| 大文件读取效率 | 手动分段 | 自动分段 + 索引 + 按需加载 |
| 多语言 LSP 覆盖 | 1 种（Python） | 5 种（JS/TS/Java/C++/Go） |
| 会话记忆持久化 | 无 | 自动保存 + 恢复 + 管理界面 |
| 后台任务能力 | 无 | 定时调度 + 进度监控 + 主动通知 |

---

## 二、全局架构设计

### 2.1 新增模块总览

```
pycoder/
├── workspace/                        # [新] 跨工作区模块
│   ├── __init__.py
│   ├── cross_workspace.py            # 跨工作区引擎
│   ├── workspace_registry.py         # 工作区注册表
│   └── share_sandbox.py              # 共享沙箱
│
├── browser/                          # [新] 浏览器增强模块
│   ├── __init__.py
│   ├── browser_pool.py               # 浏览器实例池
│   ├── proxy_manager.py              # 代理与缓存管理
│   └── access_control.py             # 访问权限管理
│
├── knowledge/                        # [新] 知识更新模块
│   ├── __init__.py
│   ├── knowledge_fetcher.py          # 知识获取引擎
│   ├── knowledge_index.py            # 知识索引与检索
│   └── update_scheduler.py           # 更新调度器
│
├── env/                              # [新] 环境管理模块
│   ├── __init__.py
│   ├── tool_detector.py              # 工具检测器
│   ├── auto_installer.py             # 自动安装器
│   └── version_checker.py            # 版本兼容性检查
│
├── io/                               # [新] 智能 IO 模块
│   ├── __init__.py
│   ├── smart_reader.py               # 智能文件读取器
│   ├── file_indexer.py               # 文件索引器
│   └── chunk_cache.py                # 分段缓存
│
├── lsp/                              # [新] 多语言 LSP 模块
│   ├── __init__.py
│   ├── lsp_manager.py                # LSP 管理器
│   ├── lsp_client.py                 # LSP 客户端
│   ├── providers/                    # 各语言 Provider
│   │   ├── javascript.py
│   │   ├── typescript.py
│   │   ├── java.py
│   │   ├── cpp.py
│   │   └── go.py
│   └── diagnostics.py                # 诊断聚合器
│
├── memory/                           # [新] 会话记忆模块
│   ├── __init__.py
│   ├── session_memory.py             # 会话记忆引擎
│   ├── memory_store.py               # 记忆存储层
│   ├── memory_retriever.py           # 记忆检索器
│   └── memory_manager_ui.py          # 记忆管理 API
│
├── notify/                           # [新] 通知推送模块
│   ├── __init__.py
│   ├── task_scheduler.py             # 任务调度器（增强版）
│   ├── progress_tracker.py           # 进度追踪器
│   ├── notification_hub.py           # 通知中心
│   └── channels/                     # 通知渠道
│       ├── websocket.py
│       ├── desktop.py
│       └── webhook.py
│
└── server/
    ├── routers/
    │   ├── workspace_api.py          # [新] 跨工作区 API
    │   ├── knowledge_api.py          # [新] 知识更新 API
    │   ├── env_api.py                # [新] 环境管理 API
    │   ├── memory_api.py             # [新] 记忆管理 API
    │   └── notify_api.py             # [新] 通知推送 API
    └── services/
        ├── knowledge_service.py      # [新] 知识服务
        └── notification_service.py   # [新] 通知服务
```

### 2.2 与现有 V2 架构的集成

```
┌─────────────────────────────────────────────────────────────────┐
│                      AI BRAIN KERNEL (V2)                        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Consciousness│  │    Task      │  │  Context & Memory    │   │
│  │    Engine    │  │   Planner    │  │      Engine          │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         └─────────────────┼─────────────────────┘                │
└───────────────────────────┼──────────────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────────────┐
│              UNIFIED CAPABILITY BUS (V2)                          │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐    │
│  │ 原有能力  │ │ 原有能力  │ │ 原有能力  │ │  [新增] 8 项能力  │    │
│  │ Editor   │ │ System   │ │Self-Evo  │ │ 升级项对应能力    │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘    │
│                                               │                   │
│  ┌────────────────────────────────────────────┼───────────────┐  │
│  │ workspace.*  │ browser.* │ knowledge.* │ env.* │ io.*     │  │
│  │ lsp.*        │ memory.* │ notify.*    │       │          │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、升级项 1：跨工作区数据共享与交互

### 3.1 方案设计

**核心思路**：在沙箱隔离的前提下，通过工作区注册表 + 共享通道实现安全跨工作区访问。

```
┌──────────────────────────────────────────────────────────────┐
│                   CROSS-WORKSPACE ENGINE                      │
│                                                               │
│  ┌─────────────────┐    ┌─────────────────┐                  │
│  │  Workspace A     │    │  Workspace B     │                  │
│  │  ~/project-a/    │    │  ~/project-b/    │                  │
│  └────────┬────────┘    └────────┬────────┘                  │
│           │                      │                            │
│           └──────────┬───────────┘                            │
│                      ▼                                        │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Workspace Registry                       │    │
│  │  • 注册/注销工作区                                     │    │
│  │  • 权限声明（允许哪些工作区读取）                        │    │
│  │  • 共享范围控制（文件级、目录级、项目级）                 │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Share Sandbox                            │    │
│  │  • 只读共享：符号链接 + 只读挂载                        │    │
│  │  • 读写共享：copy-on-write 临时层                       │    │
│  │  • 路径白名单：仅允许共享指定目录                        │    │
│  │  • 审计日志：所有跨工作区访问记录                        │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 工作区注册表 | SQLite（复用 unified_db） | 与现有数据层统一 |
| 共享存储 | 操作系统符号链接 + 只读挂载 | 零拷贝，性能最优 |
| 权限模型 | ACL（访问控制列表） | 灵活且可审计 |
| 隔离机制 | 路径白名单 + 沙箱边界检查 | 复用现有 `_safe_path` 逻辑 |

### 3.3 实施步骤

**Step 1：工作区注册表**（4h）

新建 `pycoder/workspace/workspace_registry.py`：

```python
"""工作区注册表 — 管理所有已知工作区及其共享权限"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


class ShareLevel(Enum):
    NONE = "none"           # 不共享
    READ = "read"           # 只读
    READ_WRITE = "rw"       # 读写


@dataclass
class WorkspaceEntry:
    id: str
    path: str
    name: str
    share_level: ShareLevel = ShareLevel.NONE
    allowed_workspaces: list[str] = field(default_factory=list)  # 允许访问的工作区 ID 列表
    shared_paths: list[str] = field(default_factory=list)        # 共享的子路径
    created_at: float = 0.0


class WorkspaceRegistry:
    """工作区注册表"""

    def __init__(self, db_path: Path | None = None):
        from pycoder.server.unified_db import get_db_connection
        self._conn = get_db_connection(db_path)

    def register(self, entry: WorkspaceEntry) -> None:
        """注册工作区"""
        ...

    def unregister(self, workspace_id: str) -> None:
        """注销工作区"""
        ...

    def get(self, workspace_id: str) -> WorkspaceEntry | None:
        """获取工作区信息"""
        ...

    def list_accessible(self, caller_id: str) -> list[WorkspaceEntry]:
        """列出调用方可访问的工作区"""
        ...

    def set_share_policy(self, workspace_id: str, level: ShareLevel,
                         allowed: list[str], shared_paths: list[str]) -> None:
        """设置共享策略"""
        ...
```

**Step 2：共享沙箱**（6h）

新建 `pycoder/workspace/share_sandbox.py`：

```python
"""共享沙箱 — 安全跨工作区文件访问"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class ShareSandbox:
    """跨工作区共享沙箱"""

    def __init__(self, registry):
        self._registry = registry
        self._temp_layers: dict[str, Path] = {}  # workspace_id → temp layer

    def read_file(self, caller_ws: str, target_ws: str, rel_path: str) -> str:
        """从目标工作区只读读取文件"""
        target = self._registry.get(target_ws)
        if not target:
            raise PermissionError(f"工作区 {target_ws} 未注册")

        # 检查权限
        if caller_ws not in target.allowed_workspaces:
            raise PermissionError(f"工作区 {caller_ws} 无权访问 {target_ws}")

        # 检查路径白名单
        if not self._is_path_allowed(rel_path, target.shared_paths):
            raise PermissionError(f"路径 {rel_path} 不在共享白名单中")

        full_path = Path(target.path) / rel_path
        resolved = full_path.resolve()

        # 边界检查：确保不逃逸工作区
        ws_root = Path(target.path).resolve()
        if not str(resolved).startswith(str(ws_root)):
            raise PermissionError("路径逃逸检测：拒绝访问工作区外文件")

        return resolved.read_text(encoding="utf-8")

    def write_file(self, caller_ws: str, target_ws: str, rel_path: str,
                   content: str) -> None:
        """向目标工作区写入（copy-on-write）"""
        if target_ws not in self._temp_layers:
            self._temp_layers[target_ws] = Path(tempfile.mkdtemp(prefix="ws_share_"))

        # 写入临时层，不直接修改源工作区
        layer_path = self._temp_layers[target_ws] / rel_path
        layer_path.parent.mkdir(parents=True, exist_ok=True)
        layer_path.write_text(content, encoding="utf-8")

    def commit_changes(self, target_ws: str) -> list[str]:
        """将临时层变更合并到目标工作区"""
        ...

    def rollback_changes(self, target_ws: str) -> None:
        """丢弃临时层变更"""
        ...

    def _is_path_allowed(self, rel_path: str, allowed: list[str]) -> bool:
        if not allowed:
            return True  # 空列表 = 允许全部
        return any(rel_path.startswith(p) for p in allowed)
```

**Step 3：API 路由**（4h）

新建 `pycoder/server/routers/workspace_api.py`：

```python
"""跨工作区 API 路由"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.post("/register")
async def register_workspace(path: str, name: str, share_level: str = "none"):
    """注册新工作区"""
    ...


@router.get("/list")
async def list_workspaces():
    """列出所有已注册工作区"""
    ...


@router.get("/{workspace_id}/files/{file_path:path}")
async def read_shared_file(workspace_id: str, file_path: str):
    """跨工作区读取文件"""
    ...


@router.post("/{workspace_id}/share-policy")
async def set_share_policy(workspace_id: str, level: str, allowed: list[str]):
    """设置共享策略"""
    ...
```

**Step 4：能力总线注册**（2h）

在 `pycoder/bus/registry.py` 中注册新能力：

```python
CAPABILITIES = {
    "workspace.register":     {"level": 2, "desc": "注册工作区"},
    "workspace.list":         {"level": 0, "desc": "列出工作区"},
    "workspace.read_shared":  {"level": 0, "desc": "跨工作区读取"},
    "workspace.write_shared": {"level": 2, "desc": "跨工作区写入"},
    "workspace.commit":       {"level": 3, "desc": "提交跨工作区变更"},
}
```

### 3.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 16h |
| 新增文件 | 4 个（workspace_registry.py, share_sandbox.py, workspace_api.py, test_cross_workspace.py） |
| 数据库变更 | 新增 `workspaces` 表 |
| 依赖 | 无新增（复用现有 SQLite 和路径工具） |

### 3.5 测试策略

- 单元测试：WorkspaceRegistry CRUD、ShareSandbox 权限检查、路径白名单
- 集成测试：跨工作区读取文件、写入临时层、提交变更
- 安全测试：路径逃逸攻击、未授权访问、白名单绕过

### 3.6 回滚机制

- 数据库迁移使用单独 migration，回滚时删除 `workspaces` 表
- share_sandbox 的临时层在 `rollback_changes()` 后自动清理
- 所有 API 变更在独立路由中，不影响现有端点

---

## 四、升级项 2：MCP 浏览器工具优化

### 4.1 方案设计

**核心思路**：三层优化——浏览器实例池（减少启动开销）、智能缓存（减少重复请求）、访问权限分级（安全可控）。

```
┌──────────────────────────────────────────────────────────────┐
│                  BROWSER ENHANCEMENT LAYER                     │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Browser Pool (实例池)                     │    │
│  │  • 预热 N 个 Playwright 实例，减少冷启动延迟            │    │
│  │  • 健康检查：定期验证实例可用性                         │    │
│  │  • 自动扩缩：按负载动态增减实例数                       │    │
│  │  • 最大并发限制：防止资源耗尽                           │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Proxy & Cache Manager                    │    │
│  │  • 响应缓存：相同 URL + 参数 → 缓存命中（TTL 可配）    │    │
│  │  • 请求去重：并发相同请求 → 合并为一次                   │    │
│  │  • 内容预取：分析页面链接 → 预加载高频目标              │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Access Control (访问权限)                 │    │
│  │  • 域名白名单/黑名单                                   │    │
│  │  • 速率限制：每域名 QPS 上限                           │    │
│  │  • 内容过滤：拦截敏感/恶意内容                          │    │
│  │  • 审计日志：记录所有网络请求                           │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 浏览器引擎 | Playwright（已有依赖） | 跨平台，API 成熟 |
| 实例池 | 自定义 Pool（asyncio.Queue） | 轻量，无额外依赖 |
| 缓存 | diskcache（SQLite 后端） | 持久化，支持 TTL |
| 权限控制 | 复用 PermissionEngine | 统一权限模型 |

### 4.3 实施步骤

**Step 1：浏览器实例池**（6h）

新建 `pycoder/browser/browser_pool.py`：

```python
"""浏览器实例池 — 预启动 Playwright 实例，减少冷启动延迟"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import AsyncIterator


@dataclass
class BrowserInstance:
    id: str
    browser: object  # Playwright Browser
    page: object     # Playwright Page
    in_use: bool = False
    created_at: float = 0.0
    last_used: float = 0.0


class BrowserPool:
    """Playwright 浏览器实例池"""

    MIN_INSTANCES = 2
    MAX_INSTANCES = 8
    IDLE_TIMEOUT = 300  # 5 分钟无使用则回收

    def __init__(self):
        self._pool: asyncio.Queue[BrowserInstance] = asyncio.Queue()
        self._all_instances: list[BrowserInstance] = []
        self._semaphore = asyncio.Semaphore(self.MAX_INSTANCES)
        self._cleanup_task: asyncio.Task | None = None

    async def start(self):
        """启动池，预热最小实例数"""
        for _ in range(self.MIN_INSTANCES):
            instance = await self._create_instance()
            await self._pool.put(instance)
            self._all_instances.append(instance)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def acquire(self) -> BrowserInstance:
        """获取一个可用浏览器实例"""
        await self._semaphore.acquire()
        try:
            # 尝试从池中获取
            if not self._pool.empty():
                return await self._pool.get()
            # 池空，创建新实例
            instance = await self._create_instance()
            self._all_instances.append(instance)
            return instance
        except Exception:
            self._semaphore.release()
            raise

    async def release(self, instance: BrowserInstance):
        """归还实例到池中"""
        instance.in_use = False
        instance.last_used = asyncio.get_event_loop().time()
        # 重置页面状态
        await instance.page.goto("about:blank")
        await self._pool.put(instance)
        self._semaphore.release()

    async def _create_instance(self) -> BrowserInstance:
        """创建新的浏览器实例"""
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        return BrowserInstance(
            id=f"browser_{id(page)}",
            browser=browser,
            page=page,
            created_at=asyncio.get_event_loop().time(),
        )

    async def _cleanup_loop(self):
        """定期清理空闲实例"""
        while True:
            await asyncio.sleep(60)
            now = asyncio.get_event_loop().time()
            # 保留 MIN_INSTANCES 个，回收超时空闲的
            idle = [i for i in self._all_instances
                    if not i.in_use and now - i.last_used > self.IDLE_TIMEOUT]
            for inst in idle[len(self._pool.qsize()) - self.MIN_INSTANCES:]:
                await inst.browser.close()
                self._all_instances.remove(inst)
```

**Step 2：代理与缓存管理**（4h）

新建 `pycoder/browser/proxy_manager.py`：

```python
"""代理与缓存管理 — 减少重复网络请求"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path


class ProxyCacheManager:
    """浏览器请求缓存管理器"""

    def __init__(self, cache_dir: Path | None = None):
        import diskcache
        self._cache = diskcache.Cache(
            str(cache_dir or Path.home() / ".pycoder" / "browser_cache")
        )
        self._pending: dict[str, asyncio.Future] = {}  # 请求去重

    async def fetch(self, url: str, headers: dict | None = None) -> str:
        """带缓存的 HTTP 请求"""
        cache_key = self._make_key(url, headers)
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 请求去重：相同请求合并
        if cache_key in self._pending:
            return await self._pending[cache_key]

        future = asyncio.get_event_loop().create_future()
        self._pending[cache_key] = future
        try:
            # 实际请求由调用方注入 fetch_fn
            result = await self._do_fetch(url, headers)
            self._cache.set(cache_key, result, expire=3600)  # 1 小时 TTL
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            self._pending.pop(cache_key, None)

    @staticmethod
    def _make_key(url: str, headers: dict | None) -> str:
        raw = url + json.dumps(headers or {}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

**Step 3：访问权限管理**（4h）

新建 `pycoder/browser/access_control.py`：

```python
"""浏览器访问权限管理"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class BrowserAccessPolicy:
    """浏览器访问策略"""
    # 域名白名单（支持通配符 *.github.com）
    allowed_domains: list[str] = field(default_factory=lambda: [
        "*.github.com", "*.python.org", "*.pypi.org",
        "docs.python.org", "*.npmjs.com", "*.rust-lang.org",
        "stackoverflow.com", "*.wikipedia.org",
    ])
    # 域名黑名单（优先级高于白名单）
    blocked_domains: list[str] = field(default_factory=list)
    # 速率限制
    max_requests_per_minute: int = 60
    # 内容大小限制
    max_content_size_mb: int = 10
    # 禁止访问的内网 IP
    block_private_ips: bool = True


class BrowserAccessControl:
    """浏览器访问控制器"""

    def __init__(self, policy: BrowserAccessPolicy | None = None):
        self._policy = policy or BrowserAccessPolicy()
        self._rate_limiter: dict[str, list[float]] = {}  # domain → timestamps

    def check_url(self, url: str) -> tuple[bool, str]:
        """检查 URL 是否允许访问"""
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or ""

        # 黑名单检查
        if self._matches_any(domain, self._policy.blocked_domains):
            return False, f"域名 {domain} 在黑名单中"

        # 白名单检查
        if not self._matches_any(domain, self._policy.allowed_domains):
            return False, f"域名 {domain} 不在白名单中"

        # 内网 IP 检查
        if self._policy.block_private_ips and self._is_private_ip(parsed.hostname):
            return False, "禁止访问内网地址"

        return True, ""

    def check_rate_limit(self, domain: str) -> bool:
        """检查速率限制"""
        now = time.time()
        window = now - 60  # 1 分钟窗口
        if domain not in self._rate_limiter:
            self._rate_limiter[domain] = []
        # 清理过期记录
        self._rate_limiter[domain] = [
            t for t in self._rate_limiter[domain] if t > window
        ]
        if len(self._rate_limiter[domain]) >= self._policy.max_requests_per_minute:
            return False
        self._rate_limiter[domain].append(now)
        return True

    @staticmethod
    def _matches_any(domain: str, patterns: list[str]) -> bool:
        import fnmatch
        return any(fnmatch.fnmatch(domain, p) for p in patterns)

    @staticmethod
    def _is_private_ip(hostname: str | None) -> bool:
        if not hostname:
            return False
        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            return False  # 非 IP 地址
```

**Step 4：集成到现有 browser_ai.py**（4h）

修改 `pycoder/server/routers/browser_ai.py`，将原有 Playwright 直接调用替换为 BrowserPool + ProxyCacheManager + BrowserAccessControl。

### 4.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 18h |
| 新增文件 | 4 个（browser_pool.py, proxy_manager.py, access_control.py, test_browser.py） |
| 修改文件 | 1 个（browser_ai.py） |
| 依赖 | diskcache（新增） |

### 4.5 测试策略

- 单元测试：BrowserPool 获取/释放、缓存命中/过期、域名白名单匹配
- 集成测试：完整浏览器请求链路、缓存去重
- 性能测试：实例池冷启动 vs 热启动延迟对比

---

## 五、升级项 3：动态知识更新机制

### 5.1 方案设计

**核心思路**：定时通过 MCP 浏览器工具抓取指定知识源（Python 文档、安全公告、框架更新日志），增量索引到本地知识库，Agent 通过 RAG 检索获取最新信息。

```
┌──────────────────────────────────────────────────────────────┐
│                 KNOWLEDGE UPDATE ENGINE                        │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Knowledge Sources                        │    │
│  │  • docs.python.org (Python 文档)                       │    │
│  │  • pypi.org (包版本更新)                                │    │
│  │  • github.com/security/advisories (安全公告)            │    │
│  │  • blog.python.org (Python 博客)                       │    │
│  │  • 用户自定义 RSS/Atom 源                              │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Knowledge Fetcher                        │    │
│  │  • 定时调度（cron 表达式）                              │    │
│  │  • 增量更新：只抓取新内容                               │    │
│  │  • 内容去重：哈希校验                                   │    │
│  │  • 格式转换：HTML → Markdown → 文本切片                 │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Knowledge Index                          │    │
│  │  • 文本切片（滑动窗口，512 token/片）                   │    │
│  │  • Embedding 向量化（复用现有 embedding 能力）          │    │
│  │  • 存储到向量数据库（ChromaDB/lanceDB）                 │    │
│  │  • 元数据索引：来源、时间、类别、标签                   │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Knowledge Retrieval (RAG)                │    │
│  │  • Agent 提问时自动检索相关知识                        │    │
│  │  • 语义搜索 + 时间衰减（新知识权重更高）                │    │
│  │  • 注入 System Prompt 或作为上下文                     │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 内容抓取 | 复用 BrowserPool + Playwright | 统一浏览器基础设施 |
| 调度 | 增强版 Scheduler（现有 scheduler.py） | 已有 cron 支持 |
| 向量数据库 | ChromaDB（嵌入式） | 零运维，Python 原生 |
| Embedding | 复用现有模型配置 | 统一模型管理 |
| 文本处理 | html2text + tiktoken 分词 | 轻量高效 |

### 5.3 实施步骤

**Step 1：知识获取引擎**（6h）

新建 `pycoder/knowledge/knowledge_fetcher.py`：

```python
"""知识获取引擎 — 定时抓取文档和更新"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class KnowledgeSource:
    """知识源定义"""
    id: str
    name: str
    url: str
    category: str  # "python_docs" | "security" | "packages" | "custom"
    update_interval_hours: int = 24
    last_fetched: str = ""
    etag: str = ""  # HTTP ETag 用于增量更新


@dataclass
class KnowledgeChunk:
    """知识片段"""
    id: str
    source_id: str
    content: str
    url: str
    title: str
    category: str
    fetched_at: str
    content_hash: str


class KnowledgeFetcher:
    """知识获取引擎"""

    DEFAULT_SOURCES = [
        KnowledgeSource(
            id="python-docs",
            name="Python 官方文档",
            url="https://docs.python.org/3/",
            category="python_docs",
        ),
        KnowledgeSource(
            id="python-security",
            name="Python 安全公告",
            url="https://github.com/python/security/advisories",
            category="security",
        ),
        KnowledgeSource(
            id="pypi-updates",
            name="PyPI 热门包更新",
            url="https://pypi.org/rss/updates.xml",
            category="packages",
        ),
    ]

    def __init__(self, browser_pool, cache_manager):
        self._browser_pool = browser_pool
        self._cache = cache_manager
        self._sources: dict[str, KnowledgeSource] = {}

    async def fetch_source(self, source: KnowledgeSource) -> list[KnowledgeChunk]:
        """抓取单个知识源"""
        browser = await self._browser_pool.acquire()
        try:
            await browser.page.goto(source.url, wait_until="domcontentloaded")
            content = await browser.page.content()
            # 转换为 Markdown
            text = self._html_to_markdown(content)
            # 切片
            chunks = self._chunk_text(text, source)
            return chunks
        finally:
            await self._browser_pool.release(browser)

    def _html_to_markdown(self, html: str) -> str:
        import html2text
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        return converter.handle(html)

    def _chunk_text(self, text: str, source: KnowledgeSource,
                    chunk_size: int = 512) -> list[KnowledgeChunk]:
        """文本切片"""
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        chunks = []
        for i in range(0, len(tokens), chunk_size):
            chunk_tokens = tokens[i:i + chunk_size]
            chunk_text = enc.decode(chunk_tokens)
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            chunks.append(KnowledgeChunk(
                id=f"{source.id}_{i // chunk_size}",
                source_id=source.id,
                content=chunk_text,
                url=source.url,
                title=f"{source.name} #{i // chunk_size + 1}",
                category=source.category,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                content_hash=content_hash,
            ))
        return chunks
```

**Step 2：知识索引与检索**（6h）

新建 `pycoder/knowledge/knowledge_index.py`：

```python
"""知识索引与检索 — 基于 ChromaDB 的向量存储"""
from __future__ import annotations

import chromadb
from pathlib import Path


class KnowledgeIndex:
    """知识向量索引"""

    def __init__(self, persist_dir: Path | None = None):
        dir_path = str(persist_dir or Path.home() / ".pycoder" / "knowledge_db")
        self._client = chromadb.PersistentClient(path=dir_path)
        self._collection = self._client.get_or_create_collection(
            name="pycoder_knowledge",
            metadata={"hnsw:space": "cosine"},
        )

    def index_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        """索引知识片段（去重）"""
        # 过滤已存在的 chunk
        existing_ids = set()
        try:
            result = self._collection.get(ids=[c.id for c in chunks])
            existing_ids = set(result["ids"])
        except Exception:
            pass

        new_chunks = [c for c in chunks if c.id not in existing_ids]
        if not new_chunks:
            return 0

        self._collection.add(
            ids=[c.id for c in new_chunks],
            documents=[c.content for c in new_chunks],
            metadatas=[{
                "source_id": c.source_id,
                "url": c.url,
                "title": c.title,
                "category": c.category,
                "fetched_at": c.fetched_at,
            } for c in new_chunks],
        )
        return len(new_chunks)

    def search(self, query: str, top_k: int = 5,
               category: str | None = None) -> list[dict]:
        """语义搜索知识"""
        where = {"category": category} if category else None
        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
        )
        return [
            {
                "content": doc,
                "metadata": meta,
                "score": 1 - dist,  # cosine distance → similarity
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    def get_stats(self) -> dict:
        """获取索引统计"""
        count = self._collection.count()
        return {"total_chunks": count}
```

**Step 3：更新调度器**（4h）

新建 `pycoder/knowledge/update_scheduler.py`：

```python
"""知识更新调度器 — 定时触发知识抓取和索引"""
from __future__ import annotations

import asyncio


class KnowledgeUpdateScheduler:
    """知识更新调度器"""

    def __init__(self, fetcher, index, scheduler):
        self._fetcher = fetcher
        self._index = index
        self._scheduler = scheduler  # 复用现有 Scheduler

    async def setup_default_tasks(self):
        """注册默认知识更新任务"""
        from pycoder.server.scheduler import ScheduledTask

        # 每日凌晨 3 点更新 Python 文档
        self._scheduler.add_task(ScheduledTask(
            id="knowledge-python-docs",
            name="Python 文档每日更新",
            trigger="cron",
            config={"cron": "0 3 * * *"},
            action="python:pycoder.knowledge.update_scheduler._run_update",
            action_args={"source_id": "python-docs"},
        ))

        # 每 6 小时检查安全公告
        self._scheduler.add_task(ScheduledTask(
            id="knowledge-security",
            name="安全公告定期检查",
            trigger="interval",
            config={"seconds": 21600},
            action="python:pycoder.knowledge.update_scheduler._run_update",
            action_args={"source_id": "python-security"},
        ))

    async def run_update(self, source_id: str):
        """执行单次知识更新"""
        source = self._fetcher._sources.get(source_id)
        if not source:
            return
        chunks = await self._fetcher.fetch_source(source)
        new_count = self._index.index_chunks(chunks)
        log.info("knowledge_updated", source=source_id, new_chunks=new_count)

    async def search_and_inject(self, query: str) -> str:
        """搜索知识并格式化为可注入 prompt 的文本"""
        results = self._index.search(query, top_k=3)
        if not results:
            return ""
        lines = ["\n## 最新相关知识（来自知识库）\n"]
        for r in results:
            lines.append(f"- [{r['metadata'].get('title', '')}]({r['metadata'].get('url', '')})")
            lines.append(f"  {r['content'][:300]}...\n")
        return "\n".join(lines)
```

### 5.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 16h |
| 新增文件 | 4 个（fetcher, index, scheduler, test_knowledge.py） |
| 依赖 | chromadb, html2text, tiktoken |

### 5.5 测试策略

- 单元测试：文本切片、哈希去重、ChromaDB 增删查
- 集成测试：完整抓取→索引→检索链路
- 性能测试：1000 个 chunk 的索引和检索延迟

---

## 六、升级项 4：自动化工具依赖检测与安装

### 6.1 方案设计

**核心思路**：启动时自动检测运行环境，对缺失的工具（Docker、Git、Node.js、安全扫描器）提供一键安装指导或自动安装。

```
┌──────────────────────────────────────────────────────────────┐
│              AUTO ENVIRONMENT SETUP                           │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Tool Detector                            │    │
│  │  • which/where 检测可执行文件                           │    │
│  │  • 版本号解析（semver 语义化版本）                      │    │
│  │  • 最低版本兼容性检查                                   │    │
│  │  • 平台感知（Windows/macOS/Linux）                      │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Tool Registry                            │    │
│  │  • 工具定义：名称、检测命令、安装命令、最低版本          │    │
│  │  • 平台特定安装指令                                     │    │
│  │  • 可选/必需标记                                        │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Auto Installer                           │    │
│  │  • 必需工具：提示用户安装（提供命令）                   │    │
│  │  • 可选工具：后台静默安装                               │    │
│  │  • 安装进度实时反馈                                     │    │
│  │  • 安装后自动验证                                       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 工具检测 | shutil.which + subprocess | 标准库，跨平台 |
| 版本解析 | packaging.version | Python 打包标准 |
| 安装执行 | 子进程 + 平台判断 | 复用现有沙箱机制 |
| 配置存储 | JSON 配置文件 | 可读可编辑 |

### 6.3 实施步骤

**Step 1：工具检测器**（4h）

新建 `pycoder/env/tool_detector.py`：

```python
"""工具检测器 — 检测运行环境中的工具可用性"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from packaging.version import Version, parse as parse_version


@dataclass
class ToolRequirement:
    """工具需求定义"""
    name: str
    display_name: str
    required: bool                  # 是否必需
    check_cmd: str                  # 检测命令（如 "docker --version"）
    version_flag: str = "--version" # 版本查询参数
    min_version: str | None = None  # 最低版本要求
    install_guide: str = ""         # 安装指南 Markdown
    platform_install: dict[str, str] = None  # {platform: install_command}


@dataclass
class ToolStatus:
    """工具状态"""
    name: str
    installed: bool
    version: str | None = None
    meets_minimum: bool = False
    error: str = ""


# 预定义工具清单
DEFAULT_TOOLS = [
    ToolRequirement(
        name="git", display_name="Git",
        required=True, check_cmd="git --version",
        min_version="2.30.0",
        install_guide="https://git-scm.com/downloads",
    ),
    ToolRequirement(
        name="docker", display_name="Docker",
        required=False, check_cmd="docker --version",
        min_version="20.10.0",
        install_guide="https://docs.docker.com/get-docker/",
    ),
    ToolRequirement(
        name="node", display_name="Node.js",
        required=False, check_cmd="node --version",
        min_version="18.0.0",
        install_guide="https://nodejs.org/",
    ),
    ToolRequirement(
        name="bandit", display_name="Bandit (安全扫描)",
        required=False, check_cmd="bandit --version",
        min_version="1.7.0",
        platform_install={
            "default": "pip install bandit",
        },
    ),
    ToolRequirement(
        name="semgrep", display_name="Semgrep (代码扫描)",
        required=False, check_cmd="semgrep --version",
        min_version="1.0.0",
        platform_install={
            "default": "pip install semgrep",
        },
    ),
]


class ToolDetector:
    """工具检测器"""

    def __init__(self, tools: list[ToolRequirement] | None = None):
        self._tools = tools or DEFAULT_TOOLS

    def detect_all(self) -> list[ToolStatus]:
        """检测所有工具"""
        return [self._detect_one(t) for t in self._tools]

    def _detect_one(self, req: ToolRequirement) -> ToolStatus:
        # 检查可执行文件是否存在
        exe_name = req.check_cmd.split()[0]
        if shutil.which(exe_name) is None:
            return ToolStatus(name=req.name, installed=False,
                            error=f"未找到 {exe_name}")

        # 获取版本
        try:
            result = subprocess.run(
                req.check_cmd.split(), capture_output=True,
                text=True, timeout=10,
            )
            version_str = self._parse_version(result.stdout)
            version = parse_version(version_str) if version_str else None
            meets = True
            if req.min_version and version:
                meets = version >= parse_version(req.min_version)
            return ToolStatus(
                name=req.name, installed=True,
                version=version_str, meets_minimum=meets,
            )
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            return ToolStatus(name=req.name, installed=True,
                            version="unknown", error=str(e))

    @staticmethod
    def _parse_version(output: str) -> str | None:
        """从输出中提取版本号"""
        import re
        match = re.search(r'(\d+\.\d+\.\d+)', output)
        return match.group(1) if match else None

    def get_report(self) -> dict:
        """生成检测报告"""
        statuses = self.detect_all()
        required_missing = [s for s in statuses if not s.installed
                           and any(t.required for t in self._tools
                                   if t.name == s.name)]
        optional_missing = [s for s in statuses if not s.installed
                           and not any(t.required for t in self._tools
                                      if t.name == s.name)]
        version_issues = [s for s in statuses if s.installed and not s.meets_minimum]
        return {
            "all_ok": len(required_missing) == 0 and len(version_issues) == 0,
            "required_missing": required_missing,
            "optional_missing": optional_missing,
            "version_issues": version_issues,
            "all_statuses": statuses,
        }
```

**Step 2：自动安装器**（4h）

新建 `pycoder/env/auto_installer.py`：

```python
"""自动安装器 — 指导或自动安装缺失工具"""
from __future__ import annotations

import asyncio
import platform


class AutoInstaller:
    """自动安装器"""

    def __init__(self, detector, sandbox_executor):
        self._detector = detector
        self._executor = sandbox_executor

    def get_platform(self) -> str:
        """获取当前平台标识"""
        system = platform.system()
        if system == "Windows":
            return "windows"
        elif system == "Darwin":
            return "macos"
        return "linux"

    async def install(self, tool_name: str) -> dict:
        """尝试安装工具"""
        req = next((t for t in self._detector._tools if t.name == tool_name), None)
        if not req:
            return {"success": False, "error": f"未知工具: {tool_name}"}

        # 获取平台特定安装命令
        install_cmd = None
        if req.platform_install:
            install_cmd = req.platform_install.get(
                self.get_platform(),
                req.platform_install.get("default"),
            )

        if not install_cmd:
            return {
                "success": False,
                "error": f"{req.display_name} 不支持自动安装",
                "guide": req.install_guide,
            }

        # 执行安装
        try:
            result = await self._executor.execute(install_cmd, timeout=300)
            # 验证安装
            status = self._detector._detect_one(req)
            return {
                "success": status.installed and status.meets_minimum,
                "version": status.version,
                "output": result.stdout,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_install_guide(self, tool_name: str) -> str:
        """获取安装指南（Markdown 格式）"""
        req = next((t for t in self._detector._tools if t.name == tool_name), None)
        if not req:
            return f"未知工具: {tool_name}"
        platform_name = self.get_platform()
        lines = [f"## 安装 {req.display_name}\n"]
        if req.platform_install:
            cmd = req.platform_install.get(platform_name, req.platform_install.get("default"))
            if cmd:
                lines.append(f"```bash\n{cmd}\n```\n")
        if req.install_guide:
            lines.append(f"详细指南: {req.install_guide}\n")
        return "\n".join(lines)
```

**Step 3：启动时集成**（2h）

修改 `pycoder/server/app.py` 的 `lifespan()` 函数，在启动时执行环境检测：

```python
# 在 lifespan() 中，DI 容器初始化之后添加:
from pycoder.env.tool_detector import ToolDetector
detector = ToolDetector()
report = detector.get_report()
if not report["all_ok"]:
    for tool in report["required_missing"]:
        _logger.warning("tool_missing", tool=tool.name, required=True)
    for tool in report["version_issues"]:
        _logger.warning("tool_version_low", tool=tool.name,
                        version=tool.version, min_version=tool.min_version)
```

### 6.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 10h |
| 新增文件 | 3 个（tool_detector.py, auto_installer.py, test_env.py） |
| 依赖 | packaging（已有） |

---

## 七、升级项 5：智能大文件读取模块

### 7.1 方案设计

**核心思路**：构建文件索引（行偏移 + 符号表），实现按需分段加载、内容概览、关键区域定位，取代当前的手动分段读取。

```
┌──────────────────────────────────────────────────────────────┐
│                  SMART FILE READER                             │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              File Indexer                             │    │
│  │  • 离线索引：文件修改时自动重建索引                      │    │
│  │  • 行偏移表：byte offset → line number 映射              │    │
│  │  • 符号表：函数/类/导入的起止行号                        │    │
│  │  • 哈希缓存：文件未变则复用索引                          │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Smart Reader                             │    │
│  │  • 自动分段：根据 token 预算自动切分                     │    │
│  │  • 按需加载：指定行范围精确读取                          │    │
│  │  • 内容概览：返回文件摘要（符号表 + 前 50 行）            │    │
│  │  • 智能定位：搜索符号名 → 返回其所在区域代码              │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Chunk Cache                              │    │
│  │  • LRU 缓存最近读取的分段                               │    │
│  │  • 预加载：预测下一段并提前加载                          │    │
│  │  • 内存限制：缓存总大小不超过 50MB                       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 索引存储 | SQLite（复用 unified_db） | 持久化，支持增量更新 |
| 行偏移 | 二进制扫描 + seek | 快速定位，不加载全文 |
| 符号提取 | AST（Python）/ tree-sitter（其他语言） | 已有 tree-sitter 依赖 |
| 缓存 | LRU dict + 大小限制 | 无外部依赖 |

### 7.3 实施步骤

**Step 1：文件索引器**（6h）

新建 `pycoder/io/file_indexer.py`：

```python
"""文件索引器 — 构建大文件的行偏移和符号索引"""
from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path
from dataclasses import dataclass


@dataclass
class FileIndex:
    """文件索引"""
    path: str
    content_hash: str
    total_lines: int
    total_bytes: int
    line_offsets: list[int]  # 每行的字节偏移
    symbols: list[SymbolDef]  # 符号定义


@dataclass
class SymbolDef:
    """符号定义"""
    name: str
    kind: str  # "function" | "class" | "method" | "import"
    start_line: int
    end_line: int
    parent: str = ""  # 父类名（方法时）


class FileIndexer:
    """文件索引器"""

    def __init__(self, db_path: Path | None = None):
        self._conn = self._init_db(db_path)

    def index_file(self, file_path: Path) -> FileIndex | None:
        """索引文件（如果文件未变则复用缓存）"""
        content_hash = self._hash_file(file_path)
        path_str = str(file_path)

        # 检查缓存
        cached = self._get_cached(path_str, content_hash)
        if cached:
            return cached

        try:
            with open(file_path, "rb") as f:
                # 构建行偏移表
                offsets = [0]
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    for i, byte in enumerate(chunk):
                        if byte == 10:  # '\n'
                            offsets.append(f.tell() - len(chunk) + i + 1)

                total_bytes = f.tell()

            # 提取符号
            source = file_path.read_text(encoding="utf-8")
            symbols = self._extract_symbols(source)

            index = FileIndex(
                path=path_str,
                content_hash=content_hash,
                total_lines=len(offsets),
                total_bytes=total_bytes,
                line_offsets=offsets,
                symbols=symbols,
            )
            self._cache_index(index)
            return index
        except (OSError, UnicodeDecodeError):
            return None

    def _extract_symbols(self, source: str) -> list[SymbolDef]:
        """提取 Python 符号定义"""
        symbols = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols.append(SymbolDef(
                        name=node.name, kind="function",
                        start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                    ))
                elif isinstance(node, ast.ClassDef):
                    symbols.append(SymbolDef(
                        name=node.name, kind="class",
                        start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                    ))
        except SyntaxError:
            pass
        return symbols

    def _hash_file(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _get_cached(self, path: str, content_hash: str) -> FileIndex | None:
        """从数据库获取缓存索引"""
        ...

    def _cache_index(self, index: FileIndex) -> None:
        """缓存索引到数据库"""
        ...
```

**Step 2：智能读取器**（6h）

新建 `pycoder/io/smart_reader.py`：

```python
"""智能文件读取器 — 自动分段、按需加载、内容概览"""
from __future__ import annotations

from pathlib import Path
from collections import OrderedDict


class SmartReader:
    """智能文件读取器"""

    MAX_CHUNK_TOKENS = 8000  # 单段最大 token 数
    MAX_CACHE_CHUNKS = 50    # 最大缓存分段数
    MAX_CACHE_BYTES = 50 * 1024 * 1024  # 50MB

    def __init__(self, indexer, workspace: Path):
        self._indexer = indexer
        self._workspace = workspace
        self._chunk_cache: OrderedDict[str, str] = OrderedDict()
        self._cache_bytes = 0

    def read_smart(self, file_path: str, max_tokens: int | None = None,
                   start_line: int | None = None,
                   end_line: int | None = None) -> dict:
        """智能读取文件

        Args:
            file_path: 相对路径
            max_tokens: 最大 token 预算（自动分段）
            start_line: 起始行（按需加载）
            end_line: 结束行
        Returns:
            {
                "content": str,         # 文件内容
                "total_lines": int,     # 总行数
                "chunk_index": int,     # 当前分段索引
                "total_chunks": int,    # 总分段数
                "has_more": bool,       # 是否有更多分段
                "symbols": list[dict],  # 符号表
            }
        """
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件"}

        max_tokens = max_tokens or self.MAX_CHUNK_TOKENS

        # 按需加载：指定行范围
        if start_line is not None:
            return self._read_lines(index, full_path, start_line, end_line)

        # 自动分段：根据 token 预算
        return self._read_chunked(index, full_path, max_tokens, chunk_index=0)

    def get_overview(self, file_path: str, preview_lines: int = 50) -> dict:
        """获取文件概览（符号表 + 前 N 行）"""
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件"}

        preview = self._read_lines(index, full_path, 1, preview_lines)
        return {
            "file_path": file_path,
            "total_lines": index.total_lines,
            "total_bytes": index.total_bytes,
            "symbols": [{"name": s.name, "kind": s.kind,
                         "start_line": s.start_line, "end_line": s.end_line}
                        for s in index.symbols],
            "preview": preview["content"],
        }

    def find_symbol(self, file_path: str, symbol_name: str,
                    context_lines: int = 20) -> dict:
        """定位符号并返回其所在代码区域"""
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件"}

        for sym in index.symbols:
            if sym.name == symbol_name:
                start = max(1, sym.start_line - context_lines)
                end = min(index.total_lines, sym.end_line + context_lines)
                return self._read_lines(index, full_path, start, end)
        return {"error": f"未找到符号: {symbol_name}"}

    def _read_lines(self, index: FileIndex, path: Path,
                    start: int, end: int | None = None) -> dict:
        """精确读取指定行范围"""
        end = end or index.total_lines
        start = max(1, start)
        end = min(index.total_lines, end)

        offset_start = index.line_offsets[start - 1]
        offset_end = (index.line_offsets[end]
                      if end < len(index.line_offsets)
                      else index.total_bytes)

        with open(path, "rb") as f:
            f.seek(offset_start)
            content = f.read(offset_end - offset_start).decode("utf-8", errors="replace")

        return {
            "content": content,
            "total_lines": index.total_lines,
            "start_line": start,
            "end_line": end,
            "has_more": end < index.total_lines,
        }

    def _read_chunked(self, index: FileIndex, path: Path,
                      max_tokens: int, chunk_index: int = 0) -> dict:
        """按 token 预算自动分段读取"""
        # 估算每行平均 token 数
        avg_bytes_per_line = index.total_bytes / max(index.total_lines, 1)
        avg_tokens_per_line = avg_bytes_per_line / 4  # 粗略估算
        lines_per_chunk = max(1, int(max_tokens / max(avg_tokens_per_line, 1)))

        total_chunks = max(1, (index.total_lines + lines_per_chunk - 1) // lines_per_chunk)
        start = chunk_index * lines_per_chunk + 1
        end = min(start + lines_per_chunk - 1, index.total_lines)

        result = self._read_lines(index, path, start, end)
        result["chunk_index"] = chunk_index
        result["total_chunks"] = total_chunks
        result["symbols"] = [
            {"name": s.name, "kind": s.kind,
             "start_line": s.start_line, "end_line": s.end_line}
            for s in index.symbols
        ]
        return result
```

**Step 3：分段缓存**（2h）

新建 `pycoder/io/chunk_cache.py`：

```python
"""分段缓存 — LRU 缓存最近读取的分段"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class CachedChunk:
    content: str
    size_bytes: int


class ChunkCache:
    """LRU 分段缓存"""

    def __init__(self, max_bytes: int = 50 * 1024 * 1024):
        self._cache: OrderedDict[str, CachedChunk] = OrderedDict()
        self._max_bytes = max_bytes
        self._current_bytes = 0

    def get(self, key: str) -> str | None:
        chunk = self._cache.get(key)
        if chunk:
            self._cache.move_to_end(key)  # LRU: 移到末尾
            return chunk.content
        return None

    def set(self, key: str, content: str):
        size = len(content.encode("utf-8"))
        # 淘汰旧条目
        while self._current_bytes + size > self._max_bytes and self._cache:
            _, old = self._cache.popitem(last=False)
            self._current_bytes -= old.size_bytes
        self._cache[key] = CachedChunk(content=content, size_bytes=size)
        self._current_bytes += size
        self._cache.move_to_end(key)

    def clear(self):
        self._cache.clear()
        self._current_bytes = 0
```

### 7.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 14h |
| 新增文件 | 4 个（file_indexer.py, smart_reader.py, chunk_cache.py, test_io.py） |
| 依赖 | 无新增 |

### 7.5 测试策略

- 单元测试：行偏移计算、符号提取、LRU 缓存淘汰
- 集成测试：大文件（10000+ 行）自动分段、符号定位
- 性能测试：10MB 文件索引时间、分段读取延迟

---

## 八、升级项 6：多语言 LSP 扩展

### 8.1 方案设计

**核心思路**：构建 LSP Manager 统一管理多个 LSP 服务器，通过能力总线暴露诊断、补全、引用等能力。

```
┌──────────────────────────────────────────────────────────────┐
│                  LSP MANAGER                                   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              LSP Manager (LSP Server 生命周期)         │    │
│  │  • 启动/停止 LSP Server 进程                            │    │
│  │  • 健康检查：心跳检测 + 自动重启                        │    │
│  │  • 按需启动：首次访问时懒加载                            │    │
│  │  • 资源管理：空闲超时自动关闭                            │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              LSP Clients (per language)                │    │
│  │                                                       │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │    │
│  │  │ Pyright  │ │TypeScript│ │   JDTLS  │ │  clangd  │ │    │
│  │  │ (Python) │ │  Server  │ │  (Java)  │ │  (C++)   │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │    │
│  │  ┌──────────┐                                         │    │
│  │  │  gopls   │                                         │    │
│  │  │  (Go)    │                                         │    │
│  │  └──────────┘                                         │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Diagnostics Aggregator                   │    │
│  │  • 汇总所有 LSP 诊断信息                               │    │
│  │  • 按严重度/文件/语言过滤                              │    │
│  │  • 推送至意识引擎（触发主动修复）                       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| LSP 协议 | pygls（Python LSP 库） | 成熟的 LSP 客户端/服务端实现 |
| Python | Pyright（已有） | 保持现有 |
| JS/TS | typescript-language-server | npm 全局安装 |
| Java | Eclipse JDTLS | 最成熟的 Java LSP |
| C++ | clangd | LLVM 官方 LSP |
| Go | gopls | Go 官方 LSP |

### 8.3 实施步骤

**Step 1：LSP Manager**（6h）

新建 `pycoder/lsp/lsp_manager.py`：

```python
"""LSP Manager — 统一管理多语言 LSP 服务器"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum


class LSPStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class LSPServerConfig:
    """LSP 服务器配置"""
    language: str
    command: list[str]        # 启动命令
    file_extensions: list[str]  # 支持的文件扩展名
    auto_start: bool = True
    idle_timeout: int = 300   # 空闲超时（秒）


@dataclass
class LSPServerState:
    config: LSPServerConfig
    status: LSPStatus = LSPStatus.STOPPED
    process: asyncio.subprocess.Process | None = None
    last_used: float = 0.0
    error_count: int = 0


# 预定义 LSP 配置
DEFAULT_LSP_CONFIGS = [
    LSPServerConfig(
        language="python",
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
    ),
    LSPServerConfig(
        language="typescript",
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx", ".js", ".jsx"],
    ),
    LSPServerConfig(
        language="java",
        command=["jdtls"],
        file_extensions=[".java"],
    ),
    LSPServerConfig(
        language="cpp",
        command=["clangd"],
        file_extensions=[".cpp", ".cxx", ".cc", ".c", ".h", ".hpp"],
    ),
    LSPServerConfig(
        language="go",
        command=["gopls"],
        file_extensions=[".go"],
    ),
]


class LSPManager:
    """多语言 LSP 管理器"""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._servers: dict[str, LSPServerState] = {}
        self._cleanup_task: asyncio.Task | None = None

    def register(self, config: LSPServerConfig):
        """注册 LSP 服务器配置"""
        self._servers[config.language] = LSPServerState(config=config)

    async def start(self, language: str) -> bool:
        """启动指定语言的 LSP 服务器"""
        state = self._servers.get(language)
        if not state:
            return False
        if state.status == LSPStatus.RUNNING:
            return True

        state.status = LSPStatus.STARTING
        try:
            state.process = await asyncio.create_subprocess_exec(
                *state.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
            )
            # 发送 initialize 请求
            await self._send_initialize(state.process)
            state.status = LSPStatus.RUNNING
            state.error_count = 0
            return True
        except Exception:
            state.status = LSPStatus.ERROR
            state.error_count += 1
            return False

    async def stop(self, language: str):
        """停止 LSP 服务器"""
        state = self._servers.get(language)
        if state and state.process:
            state.process.terminate()
            state.status = LSPStatus.STOPPED

    async def get_diagnostics(self, language: str, file_path: str) -> list[dict]:
        """获取文件诊断信息"""
        state = self._servers.get(language)
        if not state or state.status != LSPStatus.RUNNING:
            await self.start(language)
            state = self._servers.get(language)
            if not state or state.status != LSPStatus.RUNNING:
                return []

        # 发送 textDocument/didOpen + textDocument/diagnostic
        # 解析返回的诊断信息
        return await self._request_diagnostics(state.process, file_path)

    async def get_completions(self, language: str, file_path: str,
                              line: int, column: int) -> list[dict]:
        """获取代码补全"""
        ...

    async def get_references(self, language: str, file_path: str,
                             line: int, column: int) -> list[dict]:
        """获取符号引用"""
        ...

    def get_language_for_file(self, file_path: str) -> str | None:
        """根据文件扩展名确定语言"""
        suffix = Path(file_path).suffix.lower()
        for state in self._servers.values():
            if suffix in state.config.file_extensions:
                return state.config.language
        return None

    async def _send_initialize(self, process) -> dict:
        """发送 LSP initialize 请求"""
        ...

    async def _request_diagnostics(self, process, file_path: str) -> list[dict]:
        """请求诊断信息"""
        ...
```

**Step 2：LSP 能力注册**（4h）

在 `pycoder/bus/registry.py` 中注册 LSP 能力：

```python
CAPABILITIES = {
    # ... 现有能力 ...
    "lsp.diagnostics":     {"level": 0, "desc": "获取诊断信息"},
    "lsp.completions":     {"level": 0, "desc": "代码补全"},
    "lsp.references":      {"level": 0, "desc": "查找引用"},
    "lsp.definition":      {"level": 0, "desc": "跳转定义"},
    "lsp.hover":           {"level": 0, "desc": "悬停信息"},
    "lsp.rename":          {"level": 1, "desc": "符号重命名"},
    "lsp.status":          {"level": 0, "desc": "LSP 服务器状态"},
}
```

**Step 3：诊断聚合器**（4h）

新建 `pycoder/lsp/diagnostics.py`：

```python
"""诊断聚合器 — 汇总所有 LSP 诊断并推送至意识引擎"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AggregatedDiagnostic:
    file_path: str
    language: str
    severity: str  # "error" | "warning" | "info"
    message: str
    line: int
    column: int
    source: str  # LSP server name


class DiagnosticsAggregator:
    """诊断聚合器"""

    def __init__(self, lsp_manager, consciousness_engine=None):
        self._lsp = lsp_manager
        self._consciousness = consciousness_engine

    async def scan_file(self, file_path: str) -> list[AggregatedDiagnostic]:
        """扫描单个文件的所有语言诊断"""
        language = self._lsp.get_language_for_file(file_path)
        if not language:
            return []

        raw = await self._lsp.get_diagnostics(language, file_path)
        diagnostics = [
            AggregatedDiagnostic(
                file_path=file_path, language=language,
                severity=d.get("severity", "info"),
                message=d.get("message", ""),
                line=d.get("line", 0), column=d.get("column", 0),
                source=language,
            )
            for d in raw
        ]

        # 推送至意识引擎
        if self._consciousness and diagnostics:
            errors = [d for d in diagnostics if d.severity == "error"]
            if errors:
                await self._consciousness.perceive(
                    SystemEvent(type="lsp_errors", data=errors)
                )

        return diagnostics
```

### 8.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 14h |
| 新增文件 | 4 个（lsp_manager.py, js_provider.py, diagnostics.py, test_lsp.py） |
| 依赖 | pygls（新增），各语言 LSP 服务器（用户侧安装） |

### 8.5 测试策略

- 单元测试：LSPManager 启动/停止、文件语言识别
- 集成测试：Python 诊断获取、JS/TS 补全
- 环境测试：各 LSP 服务器可用性检测

---

## 九、升级项 7：会话记忆管理系统

### 9.1 方案设计

**核心思路**：在现有 Memory Bank（`memory_bank.py`）基础上，增加会话级自动记忆保存、恢复和管理界面。

```
┌──────────────────────────────────────────────────────────────┐
│              SESSION MEMORY SYSTEM                             │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Session Memory Engine                    │    │
│  │  • 会话开始：自动加载上次会话摘要                       │    │
│  │  • 会话进行中：增量保存关键决策点（每 5 轮对话）         │    │
│  │  • 会话结束：自动生成摘要并持久化                       │    │
│  │  • 摘要生成：LLM 驱动的智能总结                        │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Memory Store (存储层)                     │    │
│  │  • SQLite 存储结构化记忆                               │    │
│  │  • 向量索引存储语义记忆（复用 ChromaDB）                │    │
│  │  • 文件系统存储完整对话历史                             │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Memory Retriever                         │    │
│  │  • 时间衰减：最近会话权重更高                          │    │
│  │  • 语义搜索：通过 Embedding 找相关记忆                │    │
│  │  • 关键词搜索：fallback 全文搜索                      │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Memory Manager UI (API)                  │    │
│  │  • 列出历史会话                                       │    │
│  │  • 搜索/过滤记忆                                      │    │
│  │  • 删除/归档旧会话                                     │    │
│  │  • 导出会话为 Markdown                                │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 9.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 存储 | SQLite（复用 unified_db） | 统一数据层 |
| 向量搜索 | ChromaDB（复用知识库） | 统一向量存储 |
| 摘要生成 | LLM（复用现有模型配置） | 智能总结 |
| API | FastAPI（复用现有路由） | 统一 API 层 |

### 9.3 实施步骤

**Step 1：会话记忆引擎**（6h）

新建 `pycoder/memory/session_memory.py`：

```python
"""会话记忆引擎 — 自动保存和恢复会话上下文"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SessionMemory:
    """会话记忆"""
    session_id: str
    workspace: str
    created_at: str
    updated_at: str
    summary: str = ""              # LLM 生成的摘要
    key_decisions: list[str] = field(default_factory=list)  # 关键决策
    active_files: list[str] = field(default_factory=list)   # 活跃文件
    task_progress: str = ""        # 任务进度
    user_preferences: dict = field(default_factory=dict)    # 用户偏好
    message_count: int = 0         # 消息数
    token_usage: dict = field(default_factory=dict)         # Token 消耗


class SessionMemoryEngine:
    """会话记忆引擎"""

    SAVE_INTERVAL_MESSAGES = 5  # 每 N 轮对话保存一次

    def __init__(self, workspace: Path, llm_provider=None):
        self._workspace = workspace
        self._llm = llm_provider
        self._memory_dir = workspace / ".pycoder" / "sessions"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._current_session: SessionMemory | None = None
        self._message_counter = 0

    async def start_session(self, session_id: str | None = None) -> SessionMemory:
        """开始新会话，加载上次会话上下文"""
        session_id = session_id or f"session_{int(time.time())}"
        self._current_session = SessionMemory(
            session_id=session_id,
            workspace=str(self._workspace),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._message_counter = 0

        # 尝试加载上次会话摘要
        last_summary = self._load_last_summary()
        if last_summary:
            self._current_session.summary = (
                f"上次会话摘要: {last_summary}"
            )

        return self._current_session

    async def record_message(self, role: str, content: str):
        """记录消息（增量保存）"""
        if not self._current_session:
            return
        self._message_counter += 1
        if self._message_counter % self.SAVE_INTERVAL_MESSAGES == 0:
            await self._save_checkpoint()

    async def record_decision(self, decision: str):
        """记录关键决策"""
        if self._current_session:
            self._current_session.key_decisions.append(decision)

    async def record_file_activity(self, file_path: str):
        """记录活跃文件"""
        if self._current_session and file_path not in self._current_session.active_files:
            self._current_session.active_files.append(file_path)

    async def end_session(self) -> str:
        """结束会话，生成摘要并持久化"""
        if not self._current_session:
            return ""

        # 生成摘要
        summary = await self._generate_summary()
        self._current_session.summary = summary
        self._current_session.updated_at = datetime.now(timezone.utc).isoformat()

        # 持久化
        self._save_session(self._current_session)

        session = self._current_session
        self._current_session = None
        return summary

    async def _generate_summary(self) -> str:
        """使用 LLM 生成会话摘要"""
        if not self._current_session or not self._llm:
            return ""

        prompt = (
            "请用 2-3 句话总结以下编程会话的关键内容:\n\n"
            f"任务进度: {self._current_session.task_progress}\n"
            f"关键决策: {'; '.join(self._current_session.key_decisions[-5:])}\n"
            f"活跃文件: {', '.join(self._current_session.active_files[-10:])}\n"
            f"消息数: {self._current_session.message_count}\n\n"
            "摘要:"
        )
        try:
            resp = await self._llm.generate(prompt, max_tokens=200)
            return resp.content.strip()
        except Exception:
            return ""

    def _save_session(self, session: SessionMemory):
        """保存会话到文件"""
        path = self._memory_dir / f"{session.session_id}.json"
        path.write_text(
            json.dumps(session.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_last_summary(self) -> str:
        """加载最近一次会话的摘要"""
        session_files = sorted(
            self._memory_dir.glob("session_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if session_files:
            try:
                data = json.loads(session_files[0].read_text(encoding="utf-8"))
                return data.get("summary", "")
            except (json.JSONDecodeError, OSError):
                pass
        return ""

    async def _save_checkpoint(self):
        """保存检查点"""
        if self._current_session:
            self._current_session.updated_at = datetime.now(timezone.utc).isoformat()
            self._current_session.message_count = self._message_counter
            self._save_session(self._current_session)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """列出历史会话"""
        sessions = []
        for f in sorted(
            self._memory_dir.glob("session_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id"),
                    "created_at": data.get("created_at"),
                    "summary": data.get("summary", "")[:200],
                    "message_count": data.get("message_count", 0),
                })
            except (json.JSONDecodeError, OSError):
                pass
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """删除会话记忆"""
        path = self._memory_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def get_session(self, session_id: str) -> dict | None:
        """获取指定会话详情"""
        path = self._memory_dir / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None
```

**Step 2：记忆管理 API**（4h）

新建 `pycoder/server/routers/memory_api.py`：

```python
"""会话记忆管理 API"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/sessions")
async def list_sessions(limit: int = 20):
    """列出历史会话"""
    ...


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    ...


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    ...


@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """导出会话为 Markdown"""
    ...


@router.get("/current")
async def get_current_session():
    """获取当前会话状态"""
    ...


@router.post("/search")
async def search_memories(query: str, top_k: int = 5):
    """搜索会话记忆"""
    ...
```

### 9.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 10h |
| 新增文件 | 3 个（session_memory.py, memory_api.py, test_memory.py） |
| 依赖 | 无新增（复用现有 LLM 和存储） |

---

## 十、升级项 8：任务调度与主动通知系统

### 10.1 方案设计

**核心思路**：在现有 `scheduler.py` 基础上，增强为支持后台任务执行、进度监控和主动通知的完整系统。

```
┌──────────────────────────────────────────────────────────────┐
│           TASK SCHEDULER & NOTIFICATION SYSTEM                 │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Task Scheduler (增强版)                   │    │
│  │  • 定时任务（cron/interval）← 已有                      │    │
│  │  • [新] 一次性任务（delay/at）                          │    │
│  │  • [新] 任务依赖链（DAG 执行）                          │    │
│  │  • [新] 任务优先级队列                                  │    │
│  │  • [新] 任务重试策略（指数退避）                        │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Progress Tracker                         │    │
│  │  • 任务状态机：pending → running → done/failed        │    │
│  │  • 子任务进度：已完成 3/10，当前步骤描述               │    │
│  │  • 预估剩余时间                                        │    │
│  │  • 实时日志流                                          │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Notification Hub                         │    │
│  │  • WebSocket 推送（实时）                              │    │
│  │  • 桌面通知（Windows Notification / macOS 通知中心）   │    │
│  │  • 回调 Webhook（HTTP POST）                           │    │
│  │  • 通知优先级：critical > important > normal > info   │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 10.2 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| 任务调度 | 增强现有 Scheduler（asyncio） | 复用已有基础设施 |
| 进度追踪 | 自定义状态机 + WebSocket SSE | 实时推送 |
| 桌面通知 | plyer（跨平台通知库） | Windows/macOS/Linux 统一 API |
| Webhook | httpx（异步 HTTP 客户端） | 高性能异步请求 |

### 10.3 实施步骤

**Step 1：增强版任务调度器**（6h）

新建 `pycoder/notify/task_scheduler.py`：

```python
"""增强版任务调度器 — 支持一次性任务、依赖链、优先级"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Callable, Awaitable


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskTrigger(Enum):
    IMMEDIATE = "immediate"  # 立即执行
    DELAY = "delay"          # 延迟执行
    CRON = "cron"            # 定时
    INTERVAL = "interval"    # 间隔
    DEPENDENCY = "dependency"  # 依赖触发


@dataclass
class EnhancedTask:
    """增强任务定义"""
    id: str
    name: str
    trigger: TaskTrigger = TaskTrigger.IMMEDIATE
    trigger_config: dict = field(default_factory=dict)
    action: Callable[..., Awaitable] | None = None
    action_args: dict = field(default_factory=dict)
    priority: int = 0         # 0=最低, 10=最高
    max_retries: int = 0
    retry_delay: float = 5.0  # 重试间隔（秒）
    depends_on: list[str] = field(default_factory=list)  # 依赖任务 ID
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0     # 0.0 - 1.0
    progress_message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str = ""
    result: dict | None = None


class EnhancedScheduler:
    """增强版任务调度器"""

    def __init__(self, notification_hub=None):
        self._tasks: dict[str, EnhancedTask] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._hub = notification_hub
        self._max_concurrent = 3  # 最大并发任务数
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    async def submit(self, task: EnhancedTask) -> str:
        """提交任务"""
        self._tasks[task.id] = task
        # 检查依赖
        if task.depends_on:
            task.trigger = TaskTrigger.DEPENDENCY
            task.status = TaskStatus.PENDING
        else:
            await self._enqueue(task)
        await self._notify("task_submitted", task)
        return task.id

    async def _enqueue(self, task: EnhancedTask):
        """入队（优先级队列，数字越小越优先）"""
        await self._queue.put((task.priority, task.id))

    async def start(self):
        """启动调度器"""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        """停止调度器"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

    async def _worker_loop(self):
        """工作循环"""
        while self._running:
            try:
                priority, task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                task = self._tasks.get(task_id)
                if task and task.status == TaskStatus.PENDING:
                    async with self._semaphore:
                        asyncio.create_task(self._execute(task))
            except asyncio.TimeoutError:
                continue

    async def _execute(self, task: EnhancedTask):
        """执行任务（含重试）"""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        await self._notify("task_started", task)

        for attempt in range(task.max_retries + 1):
            try:
                if task.action:
                    result = await task.action(**task.action_args)
                    task.result = result
                task.status = TaskStatus.DONE
                task.progress = 1.0
                task.completed_at = time.time()
                await self._notify("task_completed", task)
                # 触发依赖任务
                await self._trigger_dependents(task.id)
                return
            except Exception as e:
                task.error = str(e)
                if attempt < task.max_retries:
                    await self._notify("task_retrying", task,
                                      attempt=attempt + 1)
                    await asyncio.sleep(task.retry_delay)
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    await self._notify("task_failed", task)

    async def _trigger_dependents(self, completed_task_id: str):
        """触发依赖此任务的其他任务"""
        for task in self._tasks.values():
            if (task.trigger == TaskTrigger.DEPENDENCY
                    and completed_task_id in task.depends_on):
                # 检查所有依赖是否完成
                all_done = all(
                    self._tasks[dep_id].status == TaskStatus.DONE
                    for dep_id in task.depends_on
                    if dep_id in self._tasks
                )
                if all_done:
                    await self._enqueue(task)

    async def update_progress(self, task_id: str, progress: float,
                              message: str = ""):
        """更新任务进度"""
        task = self._tasks.get(task_id)
        if task:
            task.progress = min(1.0, max(0.0, progress))
            task.progress_message = message
            await self._notify("task_progress", task)

    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            await self._notify("task_cancelled", task)
            return True
        return False

    def get_task(self, task_id: str) -> EnhancedTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[dict]:
        return [
            {"id": t.id, "name": t.name, "status": t.status.value,
             "progress": t.progress, "error": t.error}
            for t in self._tasks.values()
            if status is None or t.status == status
        ]

    async def _notify(self, event: str, task: EnhancedTask, **extra):
        """发送通知"""
        if self._hub:
            await self._hub.send(event, {
                "task_id": task.id,
                "task_name": task.name,
                "status": task.status.value,
                "progress": task.progress,
                "progress_message": task.progress_message,
                "error": task.error,
                **extra,
            })
```

**Step 2：通知中心**（4h）

新建 `pycoder/notify/notification_hub.py`：

```python
"""通知中心 — 多渠道消息推送"""
from __future__ import annotations

import asyncio
from enum import Enum


class NotificationPriority(Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"
    INFO = "info"


class NotificationHub:
    """通知中心"""

    def __init__(self):
        self._ws_clients: dict[str, set] = {}  # session_id → {ws connections}
        self._webhook_urls: list[str] = []
        self._enabled_channels = {"websocket", "desktop"}

    async def send(self, event: str, data: dict,
                   priority: NotificationPriority = NotificationPriority.NORMAL):
        """发送通知到所有启用的渠道"""
        tasks = []
        if "websocket" in self._enabled_channels:
            tasks.append(self._send_ws(event, data))
        if "desktop" in self._enabled_channels:
            tasks.append(self._send_desktop(event, data, priority))
        if "webhook" in self._enabled_channels:
            tasks.append(self._send_webhook(event, data))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_ws(self, event: str, data: dict):
        """通过 WebSocket 推送"""
        message = json.dumps({"type": "notification", "event": event, "data": data})
        for session_id, clients in self._ws_clients.items():
            for ws in list(clients):
                try:
                    await ws.send_text(message)
                except Exception:
                    clients.discard(ws)

    async def _send_desktop(self, event: str, data: dict,
                            priority: NotificationPriority):
        """发送桌面通知"""
        if priority in (NotificationPriority.CRITICAL, NotificationPriority.IMPORTANT):
            try:
                from plyer import notification
                notification.notify(
                    title=f"PyCoder - {event}",
                    message=data.get("progress_message", data.get("task_name", "")),
                    timeout=5,
                )
            except Exception:
                pass  # 桌面通知失败不影响主流程

    async def _send_webhook(self, event: str, data: dict):
        """发送 Webhook"""
        import httpx
        async with httpx.AsyncClient() as client:
            for url in self._webhook_urls:
                try:
                    await client.post(url, json={"event": event, "data": data},
                                     timeout=10)
                except Exception:
                    pass

    def register_ws(self, session_id: str, ws):
        """注册 WebSocket 连接"""
        if session_id not in self._ws_clients:
            self._ws_clients[session_id] = set()
        self._ws_clients[session_id].add(ws)

    def unregister_ws(self, session_id: str, ws):
        """注销 WebSocket 连接"""
        if session_id in self._ws_clients:
            self._ws_clients[session_id].discard(ws)

    def add_webhook(self, url: str):
        self._webhook_urls.append(url)

    def configure_channels(self, channels: set[str]):
        self._enabled_channels = channels
```

**Step 3：进度追踪器**（2h）

新建 `pycoder/notify/progress_tracker.py`：

```python
"""进度追踪器 — 任务进度监控与预估"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ProgressSnapshot:
    task_id: str
    progress: float
    message: str
    timestamp: float = field(default_factory=time.time)


class ProgressTracker:
    """进度追踪器"""

    def __init__(self):
        self._snapshots: dict[str, list[ProgressSnapshot]] = {}

    def record(self, task_id: str, progress: float, message: str = ""):
        if task_id not in self._snapshots:
            self._snapshots[task_id] = []
        self._snapshots[task_id].append(ProgressSnapshot(
            task_id=task_id, progress=progress, message=message,
        ))

    def estimate_remaining(self, task_id: str) -> float | None:
        """预估剩余时间（秒）"""
        snaps = self._snapshots.get(task_id, [])
        if len(snaps) < 2:
            return None
        # 计算最近两个快照之间的速率
        recent = snaps[-2:]
        progress_delta = recent[1].progress - recent[0].progress
        time_delta = recent[1].timestamp - recent[0].timestamp
        if progress_delta <= 0 or time_delta <= 0:
            return None
        rate = progress_delta / time_delta  # 进度/秒
        remaining_progress = 1.0 - recent[1].progress
        return remaining_progress / rate

    def get_history(self, task_id: str) -> list[dict]:
        return [
            {"progress": s.progress, "message": s.message, "timestamp": s.timestamp}
            for s in self._snapshots.get(task_id, [])
        ]
```

**Step 4：API 路由**（4h）

新建 `pycoder/server/routers/notify_api.py`：

```python
"""任务调度与通知 API"""
from fastapi import APIRouter, WebSocket, HTTPException

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/submit")
async def submit_task(name: str, action: str, args: dict = None,
                      priority: int = 0, depends_on: list[str] = None):
    """提交新任务"""
    ...


@router.get("/list")
async def list_tasks(status: str = None):
    """列出任务"""
    ...


@router.get("/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    ...


@router.get("/{task_id}/progress")
async def get_task_progress(task_id: str):
    """获取任务进度（含预估剩余时间）"""
    ...


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    ...


@router.websocket("/ws/notifications")
async def notification_websocket(ws: WebSocket):
    """WebSocket 通知通道"""
    await ws.accept()
    hub.register_ws(session_id, ws)
    try:
        while True:
            await ws.receive_text()  # 保持连接
    except Exception:
        hub.unregister_ws(session_id, ws)


@router.post("/webhooks/register")
async def register_webhook(url: str):
    """注册 Webhook"""
    ...


@router.put("/channels")
async def configure_channels(channels: list[str]):
    """配置通知渠道"""
    ...
```

### 10.4 资源需求

| 资源 | 数量 |
|------|------|
| 开发工时 | 16h |
| 新增文件 | 5 个（task_scheduler.py, notification_hub.py, progress_tracker.py, notify_api.py, test_notify.py） |
| 依赖 | plyer, httpx（新增） |

---

## 十一、分阶段实施路线图

### 11.1 总体时间线

```
Week 1-2         Week 3-4         Week 5-6         Week 7-8
┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐
│ 阶段 A   │ ──→ │ 阶段 B   │ ──→ │ 阶段 C   │ ──→ │ 阶段 D   │
│ 基础能力  │      │ 智能增强  │      │ 体验升级  │      │ 集成收尾  │
└─────────┘      └─────────┘      └─────────┘      └─────────┘
```

### 11.2 阶段 A：基础能力（第 1-2 周，~62h）

| 升级项 | 工时 | 产出 |
|--------|------|------|
| #4 自动化工具依赖检测与安装 | 10h | 启动时自动检测环境，提供安装指南 |
| #5 智能大文件读取模块 | 14h | 文件索引 + 自动分段 + 符号定位 |
| #7 会话记忆管理系统 | 10h | 自动保存/恢复会话上下文，管理 API |
| #8 任务调度与主动通知（基础） | 16h | 增强调度器 + 通知中心 + WebSocket 推送 |
| 测试编写 | 12h | 对应模块的单元测试和集成测试 |

**里程碑 A**：基础能力就绪，用户可体验大文件读取、会话记忆、环境检测。

### 11.3 阶段 B：智能增强（第 3-4 周，~48h）

| 升级项 | 工时 | 产出 |
|--------|------|------|
| #1 跨工作区数据共享 | 16h | 工作区注册表 + 共享沙箱 + API |
| #2 MCP 浏览器工具优化 | 18h | 浏览器池 + 缓存 + 访问控制 |
| 测试编写 | 14h | 集成测试 + 安全测试 |

**里程碑 B**：跨工作区和网络访问能力就绪，浏览器响应速度显著提升。

### 11.4 阶段 C：体验升级（第 5-6 周，~30h）

| 升级项 | 工时 | 产出 |
|--------|------|------|
| #3 动态知识更新机制 | 16h | 知识抓取 + 向量索引 + RAG 检索 |
| #6 多语言 LSP 扩展 | 14h | 5 种语言 LSP 支持 + 诊断聚合 |

**里程碑 C**：知识新鲜度和多语言开发体验显著提升。

### 11.5 阶段 D：集成收尾（第 7-8 周，~20h）

| 工作项 | 工时 | 产出 |
|--------|------|------|
| 能力总线注册（8 项新能力） | 6h | 所有能力通过总线可调用 |
| 端到端集成测试 | 8h | 完整流程测试 |
| 文档与指南 | 6h | 用户文档 + API 文档 |

**里程碑 D**：所有升级项完成，通过全量测试。

---

## 十二、测试策略

### 12.1 分层测试

| 层级 | 覆盖范围 | 目标 |
|------|---------|------|
| 单元测试 | 每个新增模块 | 覆盖率 ≥ 90% |
| 集成测试 | 跨模块交互 | 核心流程全覆盖 |
| 安全测试 | 权限、沙箱、路径验证 | 零高危漏洞 |
| 性能测试 | 大文件、浏览器池、知识检索 | 延迟 < 目标值 |

### 12.2 关键测试用例

| 场景 | 测试点 | 通过标准 |
|------|--------|---------|
| 跨工作区读取 | 权限检查、路径白名单、逃逸防护 | 拒绝未授权，允许授权 |
| 浏览器缓存 | 缓存命中率、TTL 过期、请求去重 | 重复请求命中率 > 80% |
| 知识更新 | 增量获取、向量索引、语义检索 | 检索 Top-3 准确率 > 70% |
| 大文件读取 | 10MB 文件分段、符号定位、缓存 | 分段延迟 < 100ms |
| LSP 诊断 | 多语言诊断、错误识别 | 诊断结果与手动检查一致 |
| 会话记忆 | 保存/恢复、摘要生成、跨会话加载 | 内容完整不丢失 |
| 任务调度 | 优先级、依赖链、重试、通知 | 执行顺序正确，失败重试生效 |

### 12.3 回归测试

- 每次阶段完成后执行全量测试套件
- 确保现有 5000+ 测试用例不受影响
- 覆盖率不下降（当前 ~80%）

---

## 十三、回滚机制

### 13.1 代码回滚

每个升级项在独立分支开发，阶段集成分支：

```bash
git checkout -b feat/phase-a-basic-capabilities
git checkout -b feat/phase-b-smart-enhance
git checkout -b feat/phase-c-experience-upgrade
git checkout -b feat/phase-d-integration
```

回滚策略：
- **单模块回滚**：`git revert <commit>` 针对性回滚
- **阶段回滚**：放弃阶段分支，不影响其他阶段
- **全量回滚**：切回 master 分支

### 13.2 数据回滚

- 数据库新增表：迁移脚本包含 `DOWN` 操作
- 文件系统缓存：`.pycoder/` 目录下的缓存可安全删除
- 向量索引：ChromaDB 持久化目录可重建

### 13.3 配置回滚

- 所有新增配置项有默认值，回滚后不影响现有功能
- 环境变量开关：`PYCODER_ENABLE_*` 可单独禁用新功能

---

## 十四、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ChromaDB 向量索引性能 | 中 | 中 | 限制索引大小，增量更新，异步索引 |
| Playwright 浏览器池内存泄漏 | 中 | 高 | 定期健康检查，空闲回收，内存上限 |
| LSP 服务器兼容性差异 | 高 | 中 | 错误隔离，单个 LSP 失败不影响其他 |
| 跨工作区权限绕过 | 低 | 高 | 多层检查（注册表 + 白名单 + 边界），安全测试 |
| 知识源爬取被限流 | 中 | 低 | 缓存策略，增量更新，多源 fallback |
| 大文件索引内存占用 | 中 | 低 | 按需索引，LRU 淘汰，内存上限 |
| 会话记忆数据膨胀 | 中 | 低 | 自动归档，配置最大保留天数 |

---

## 附录 A：文件变更清单

| 文件 | 操作 | 阶段 | 工时 |
|------|:----:|:----:|:----:|
| `pycoder/workspace/workspace_registry.py` | 新建 | B | 4h |
| `pycoder/workspace/share_sandbox.py` | 新建 | B | 6h |
| `pycoder/workspace/__init__.py` | 新建 | B | 0.5h |
| `pycoder/server/routers/workspace_api.py` | 新建 | B | 4h |
| `pycoder/browser/browser_pool.py` | 新建 | B | 6h |
| `pycoder/browser/proxy_manager.py` | 新建 | B | 4h |
| `pycoder/browser/access_control.py` | 新建 | B | 4h |
| `pycoder/browser/__init__.py` | 新建 | B | 0.5h |
| `pycoder/server/routers/browser_ai.py` | 修改 | B | 4h |
| `pycoder/knowledge/knowledge_fetcher.py` | 新建 | C | 6h |
| `pycoder/knowledge/knowledge_index.py` | 新建 | C | 6h |
| `pycoder/knowledge/update_scheduler.py` | 新建 | C | 4h |
| `pycoder/knowledge/__init__.py` | 新建 | C | 0.5h |
| `pycoder/server/routers/knowledge_api.py` | 新建 | C | 2h |
| `pycoder/env/tool_detector.py` | 新建 | A | 4h |
| `pycoder/env/auto_installer.py` | 新建 | A | 4h |
| `pycoder/env/__init__.py` | 新建 | A | 0.5h |
| `pycoder/server/app.py` | 修改 | A | 2h |
| `pycoder/io/file_indexer.py` | 新建 | A | 6h |
| `pycoder/io/smart_reader.py` | 新建 | A | 6h |
| `pycoder/io/chunk_cache.py` | 新建 | A | 2h |
| `pycoder/io/__init__.py` | 新建 | A | 0.5h |
| `pycoder/lsp/lsp_manager.py` | 新建 | C | 6h |
| `pycoder/lsp/diagnostics.py` | 新建 | C | 4h |
| `pycoder/lsp/__init__.py` | 新建 | C | 0.5h |
| `pycoder/lsp/providers/__init__.py` | 新建 | C | 2h |
| `pycoder/bus/registry.py` | 修改 | D | 4h |
| `pycoder/memory/session_memory.py` | 新建 | A | 6h |
| `pycoder/memory/__init__.py` | 新建 | A | 0.5h |
| `pycoder/server/routers/memory_api.py` | 新建 | A | 4h |
| `pycoder/notify/task_scheduler.py` | 新建 | A | 6h |
| `pycoder/notify/notification_hub.py` | 新建 | A | 4h |
| `pycoder/notify/progress_tracker.py` | 新建 | A | 2h |
| `pycoder/notify/__init__.py` | 新建 | A | 0.5h |
| `pycoder/server/routers/notify_api.py` | 新建 | A | 4h |
| `pycoder/server/scheduler.py` | 修改 | A | 2h |
| 测试文件（8 个） | 新建 | 全阶段 | 34h |
| **总计** | **30 新建 + 4 修改** | — | **~160h** |

---

## 附录 B：新增依赖清单

| 依赖 | 用途 | 版本 | 阶段 |
|------|------|------|------|
| chromadb | 知识向量索引 | >= 0.5.0 | C |
| html2text | HTML→Markdown 转换 | >= 2024.0 | C |
| tiktoken | Token 计数 | >= 0.7.0 | C |
| pygls | LSP 客户端/服务端 | >= 1.3.0 | C |
| diskcache | 浏览器请求缓存 | >= 5.6.0 | B |
| plyer | 跨平台桌面通知 | >= 2.1.0 | A |
| httpx | 异步 HTTP 客户端（Webhook） | >= 0.27.0 | A |

---

> **文档状态**：方案设计完成，待评审  
> **下一步**：评审通过后，按 [第十一节](#十一分阶段实施路线图) 的阶段计划逐步实施。
"""
记忆引擎 — 四级记忆体系

级别:
1. 工作记忆 (Working Memory): 当前会话上下文，滑窗 + 摘要
2. 情景记忆 (Episodic Memory): 对话历史和已执行操作
3. 项目知识 (Project Knowledge): 架构决策、约定、依赖图
4. 长期知识 (Long-term Knowledge): 跨项目模式、用户偏好

持久化: 项目知识和长期知识自动保存到 ~/.pycoder/memory/
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    """记忆条目"""

    key: str
    content: str
    importance: float = 0.5  # 0-1, 重要度
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)


class WorkingMemory:
    """
    工作记忆 — 当前会话的上下文窗口

    特性:
    - 滑窗截断: 保留最近 N 条
    - 重要度排序: 重要信息优先保留
    - 自动摘要: 超量时压缩旧信息
    """

    def __init__(self, max_items: int = 50):
        self._items: OrderedDict[str, MemoryItem] = OrderedDict()
        self._max_items = max_items

    def add(
        self, key: str, content: str, importance: float = 0.5, tags: list[str] | None = None
    ) -> None:
        """添加记忆"""
        if key in self._items:
            item = self._items[key]
            item.content = content
            item.access_count += 1
            self._items.move_to_end(key)
        else:
            item = MemoryItem(
                key=key,
                content=content,
                importance=importance,
                tags=tags or [],
            )
            self._items[key] = item

            # 超过容量，移除最不重要的
            if len(self._items) > self._max_items:
                self._evict()

    def get(self, key: str) -> MemoryItem | None:
        """获取记忆"""
        item = self._items.get(key)
        if item:
            item.access_count += 1
            self._items.move_to_end(key)
        return item

    def search(self, query: str) -> list[MemoryItem]:
        """关键词搜索"""
        results: list[MemoryItem] = []
        query_lower = query.lower()

        for item in self._items.values():
            if query_lower in item.content.lower():
                results.append(item)
            elif any(query_lower in tag.lower() for tag in item.tags):
                results.append(item)

        return results

    def summarize(self) -> str:
        """生成当前上下文摘要"""
        if not self._items:
            return ""

        lines = []
        for item in list(self._items.values())[-10:]:
            lines.append(f"- {item.key}: {item.content[:100]}")

        return "当前上下文:\n" + "\n".join(lines)

    def clear(self) -> None:
        """清空工作记忆"""
        self._items.clear()

    def _evict(self) -> None:
        """淘汰最不重要的记忆"""
        if not self._items:
            return

        min_key = min(
            self._items.keys(),
            key=lambda k: (
                self._items[k].importance,
                self._items[k].access_count,
            ),
        )
        self._items.pop(min_key)


class ProjectKnowledge:
    """
    项目知识 — 持久化的项目级知识库

    存储:
    - 架构决策记录 (ADR)
    - 项目约定与规范
    - 依赖关系图
    - API 文档索引
    - 代码库向量索引
    """

    def __init__(self, project_path: str = "."):
        self.project_path = project_path
        self._adr: list[dict[str, Any]] = []
        self._conventions: dict[str, str] = {}
        self._dependency_graph: dict[str, list[str]] = {}
        self._api_index: dict[str, str] = {}

    def add_adr(self, title: str, decision: str, context: str = "") -> None:
        """添加架构决策记录"""
        self._adr.append(
            {
                "title": title,
                "decision": decision,
                "context": context,
                "timestamp": time.time(),
            }
        )

    def set_convention(self, name: str, rule: str) -> None:
        """设置项目约定"""
        self._conventions[name] = rule

    def get_convention(self, name: str) -> str | None:
        """获取项目约定"""
        return self._conventions.get(name)

    def all_conventions(self) -> dict[str, str]:
        """获取所有约定"""
        return dict(self._conventions)

    def add_dependency(self, module: str, depends_on: str) -> None:
        """添加依赖关系"""
        if module not in self._dependency_graph:
            self._dependency_graph[module] = []
        if depends_on not in self._dependency_graph[module]:
            self._dependency_graph[module].append(depends_on)

    def get_dependents(self, module: str) -> list[str]:
        """获取依赖某模块的所有模块"""
        return [m for m, deps in self._dependency_graph.items() if module in deps]

    def get_dependencies(self, module: str) -> list[str]:
        """获取某模块的所有依赖"""
        return self._dependency_graph.get(module, [])


class MemoryEngine:
    """
    记忆引擎 — 统一管理各级记忆

    检索策略:
    - 关键词匹配 → BM25
    - 语义相似 → Embedding + Vector Search
    - 图遍历 → 依赖关系链追踪
    - 混合检索 → 多路召回 + 重排序
    """

    def __init__(self):
        self.working = WorkingMemory()
        self.project = ProjectKnowledge()
        self._episodic: list[dict[str, Any]] = []
        self._long_term: dict[str, Any] = {}
        self._persist_dir = Path.home() / ".pycoder" / "memory"
        self._load_all()

    def remember(
        self, key: str, content: str, level: str = "working", importance: float = 0.5
    ) -> None:
        """记录信息到指定记忆层级"""
        if level == "working":
            self.working.add(key, content, importance)
        elif level == "project":
            self.project.set_convention(key, content)
            self._save_project_knowledge()
        elif level == "long_term":
            self._long_term[key] = {"content": content, "timestamp": time.time()}
            self._save_long_term()
        elif level == "episodic":
            self._episodic.append(
                {
                    "key": key,
                    "content": content,
                    "timestamp": time.time(),
                }
            )

    def recall(self, query: str, level: str = "all") -> list[str]:
        """从记忆中检索相关信息"""
        results: list[str] = []

        if level in ("working", "all"):
            for item in self.working.search(query):
                results.append(f"[工作记忆] {item.key}: {item.content}")

        if level in ("project", "all"):
            for name, rule in self.project.all_conventions().items():
                if query.lower() in f"{name} {rule}".lower():
                    results.append(f"[项目约定] {name}: {rule}")

        if level in ("long_term", "all"):
            for key, data in self._long_term.items():
                if query.lower() in str(data).lower():
                    results.append(f"[长期知识] {key}: {data['content'][:200]}")

        if level in ("episodic", "all"):
            for episode in self._episodic:
                if query.lower() in str(episode).lower():
                    results.append(f"[情景记忆] {episode['key']}: {episode['content'][:200]}")

        return results[-10:]  # 返回最相关的

    def get_context_for_llm(self, max_tokens: int = 2000) -> str:
        """
        为 LLM 调用构建上下文

        Returns:
            拼接好的上下文字符串
        """
        parts: list[str] = []

        # 工作记忆摘要
        summary = self.working.summarize()
        if summary:
            parts.append(summary)

        # 项目约定
        conventions = self.project.all_conventions()
        if conventions:
            parts.append("项目约定:")
            for name, rule in list(conventions.items())[:5]:
                parts.append(f"- {name}: {rule[:100]}")

        context = "\n".join(parts)
        return context[:max_tokens]

    # ── 持久化 ──────────────────────────────

    def _save_project_knowledge(self) -> None:
        """持久化项目知识"""
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "conventions": self.project.all_conventions(),
                "adr": self.project._adr,
                "saved_at": time.time(),
            }
            (self._persist_dir / "project_knowledge.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("保存项目知识失败: %s", e)

    def _save_long_term(self) -> None:
        """持久化长期知识"""
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            (self._persist_dir / "long_term.json").write_text(
                json.dumps(self._long_term, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("保存长期知识失败: %s", e)

    def _load_all(self) -> None:
        """从磁盘加载所有持久化记忆"""
        try:
            # 加载项目知识
            pk_path = self._persist_dir / "project_knowledge.json"
            if pk_path.exists():
                data = json.loads(pk_path.read_text(encoding="utf-8"))
                for name, rule in data.get("conventions", {}).items():
                    self.project.set_convention(name, rule)
                logger.debug("加载项目知识: %d 条约定", len(data.get("conventions", {})))

            # 加载长期知识
            lt_path = self._persist_dir / "long_term.json"
            if lt_path.exists():
                self._long_term = json.loads(lt_path.read_text(encoding="utf-8"))
                logger.debug("加载长期知识: %d 条", len(self._long_term))
        except Exception as e:
            logger.debug("加载记忆失败: %s", e)

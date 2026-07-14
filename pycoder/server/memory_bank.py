"""P1: Memory Bank — 跨会话项目持久记忆

借鉴 Cline 的 Memory Bank 设计，自动维护项目上下文文件。
将 PyCoder 从无状态助手升级为有记忆的开发伙伴。

文件结构:
    .pycoder/memory/
    ├── project_brief.md     # 项目概述 (自动生成+人工审阅)
    ├── architecture.md      # 架构决策记录
    ├── tech_context.md      # 技术栈和依赖
    ├── active_context.md    # 当前活跃工作
    └── progress.md          # 进度追踪

每次会话启动时，自动加载相关 memory 注入 system prompt。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class MemoryBank:
    """项目记忆管理器 — 基于文件系统的跨会话持久化"""

    # 记忆文件映射
    MEMORY_FILES: dict[str, str] = {
        "project_brief": "project_brief.md",
        "architecture": "architecture.md",
        "tech_context": "tech_context.md",
        "active_context": "active_context.md",
        "progress": "progress.md",
    }

    # 加载到 context 的优先级顺序
    LOAD_ORDER = ["project_brief", "architecture", "tech_context", "active_context"]

    def __init__(self, workspace: Path) -> None:
        self._memory_dir = workspace / ".pycoder" / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    # ── 上下文加载 ──

    def load_context_for_prompt(self, max_tokens: int = 2000) -> str:
        """加载应注入 system prompt 的记忆内容。

        按优先级加载: project_brief > architecture > tech_context > active_context。
        超过 max_tokens 时截断。
        """
        parts: list[str] = []
        token_estimate = 0

        for key in self.LOAD_ORDER:
            filename = self.MEMORY_FILES.get(key, f"{key}.md")
            content = self._read(filename)
            if not content:
                continue

            tokens = max(len(content) // 4, 1)
            if token_estimate + tokens > max_tokens:
                remaining = max_tokens - token_estimate
                if remaining > 100:
                    parts.append(content[: remaining * 4] + "\n...")
                break

            parts.append(content)
            token_estimate += tokens

        if not parts:
            return ""

        header = "<!-- Memory Bank — 项目持久记忆 -->\n\n"
        return header + "\n\n---\n\n".join(parts)

    def get_project_brief(self) -> str:
        """获取项目概述"""
        return self._read("project_brief.md")

    def get_architecture(self) -> str:
        """获取架构决策记录"""
        return self._read("architecture.md")

    def get_progress(self) -> str:
        """获取进度日志"""
        return self._read("progress.md")

    # ── 内容更新 ──

    def update_project_brief(self, content: str) -> None:
        """更新项目概述"""
        self._write("project_brief.md", self._with_header(content, "Project Brief"))

    def record_architecture_decision(self, title: str, decision: str, rationale: str) -> None:
        """记录架构决策"""
        existing = self._read("architecture.md") or "# Architecture Decisions\n\n"
        entry = (
            f"## {title}\n"
            f"- **决策:** {decision}\n"
            f"- **理由:** {rationale}\n"
            f"- **日期:** {_now()}\n\n"
        )
        self._write("architecture.md", existing + entry)

    def update_tech_context(self, tech_stack: str, dependencies: str = "") -> None:
        """更新技术栈上下文"""
        content = (
            f"# Tech Context\n\n"
            f"## 技术栈\n\n{tech_stack}\n\n"
        )
        if dependencies:
            content += f"## 依赖\n\n{dependencies}\n"
        self._write("tech_context.md", content)

    def set_active_context(self, description: str, files: list[str] | None = None) -> None:
        """设置当前活跃工作上下文"""
        content = f"# Active Context\n\n{description}\n"
        if files:
            content += "\n## 相关文件\n\n"
            for f in files:
                content += f"- `{f}`\n"
        self._write("active_context.md", content)

    def update_progress(self, status: str, detail: str) -> None:
        """更新进度日志"""
        existing = self._read("progress.md") or "# Progress Log\n\n"
        entry = f"- [{_now()}] **{status}**: {detail}\n"
        self._write("progress.md", existing + entry)

    def mark_completed(self, task: str) -> None:
        """标记任务完成"""
        self.update_progress("COMPLETED", task)

    def clear_active_context(self) -> None:
        """清除活跃上下文（任务完成后）"""
        self._write("active_context.md", "")

    # ── 查询 ──

    def has_memory(self) -> bool:
        """检查是否已有任何记忆"""
        return any(
            (self._memory_dir / f).exists() for f in self.MEMORY_FILES.values()
        )

    def list_memories(self) -> list[dict[str, str]]:
        """列出所有记忆文件及其大小"""
        result = []
        for key, filename in self.MEMORY_FILES.items():
            path = self._memory_dir / filename
            if path.exists():
                size = path.stat().st_size
                result.append({"key": key, "file": filename, "size": size})
        return result

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
    def _with_header(content: str, title: str) -> str:
        if not content.startswith("#"):
            content = f"# {title}\n\n{content}"
        if not content.startswith("<!--"):
            content = f"<!-- 最后更新: {_now()} -->\n\n{content}"
        return content


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


# ── 全局单例 ──

_memory_bank: MemoryBank | None = None


def get_memory_bank(workspace: Path | None = None) -> MemoryBank:
    """获取 MemoryBank 单例"""
    global _memory_bank
    if _memory_bank is None:
        from pycoder.server.routers.files import get_workspace_root

        ws = workspace or Path(get_workspace_root())
        _memory_bank = MemoryBank(workspace=ws)
    return _memory_bank


def reset_memory_bank() -> None:
    """重置 MemoryBank 单例（测试用）"""
    global _memory_bank
    _memory_bank = None

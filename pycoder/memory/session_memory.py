"""会话记忆引擎 — 自动保存和恢复会话上下文

每次会话自动记录关键决策、活跃文件、任务进度。
会话结束时生成 LLM 摘要，下次启动时自动加载。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SessionMemory:
    """会话记忆"""
    session_id: str
    workspace: str
    created_at: str
    updated_at: str
    summary: str = ""
    key_decisions: list[str] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)
    task_progress: str = ""
    user_preferences: dict = field(default_factory=dict)
    message_count: int = 0
    token_usage: dict = field(default_factory=dict)


class SessionMemoryEngine:
    """会话记忆引擎

    用法:
        engine = SessionMemoryEngine(workspace, llm_provider)
        await engine.start_session()
        # ... 会话进行中 ...
        await engine.record_decision("使用 Redis 替代 SQLite 缓存")
        await engine.record_file_activity("src/main.py")
        await engine.end_session()
    """

    SAVE_INTERVAL_MESSAGES = 5  # 每 N 轮对话自动保存检查点

    def __init__(self, workspace: Path, llm_provider=None):
        self._workspace = workspace
        self._llm = llm_provider
        self._memory_dir = workspace / ".pycoder" / "sessions"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._current_session: SessionMemory | None = None
        self._message_counter = 0

    # ── 会话生命周期 ──

    async def start_session(self, session_id: str | None = None) -> SessionMemory:
        """开始新会话，加载上次会话上下文

        Args:
            session_id: 会话 ID，不指定则自动生成

        Returns:
            SessionMemory 对象
        """
        session_id = session_id or f"session_{int(time.time())}"
        self._current_session = SessionMemory(
            session_id=session_id,
            workspace=str(self._workspace),
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._message_counter = 0

        # 加载上次会话摘要
        last_summary = self._load_last_summary()
        if last_summary:
            self._current_session.summary = last_summary

        return self._current_session

    async def end_session(self) -> str:
        """结束会话，生成摘要并持久化

        Returns:
            LLM 生成的会话摘要
        """
        if not self._current_session:
            return ""

        # 生成摘要
        summary = await self._generate_summary()
        self._current_session.summary = summary
        self._current_session.updated_at = datetime.now(UTC).isoformat()

        # 持久化
        self._save_session(self._current_session)

        self._current_session = None
        self._message_counter = 0
        return summary

    # ── 记录操作 ──

    async def record_message(self, role: str, content: str):
        """记录消息（增量保存检查点）

        Args:
            role: 消息角色（"user" / "assistant"）
            content: 消息内容
        """
        if not self._current_session:
            return
        self._message_counter += 1
        if self._message_counter % self.SAVE_INTERVAL_MESSAGES == 0:
            await self._save_checkpoint()

    async def record_decision(self, decision: str):
        """记录关键决策"""
        if self._current_session:
            self._current_session.key_decisions.append(decision)
            # 关键决策立即保存
            await self._save_checkpoint()

    async def record_file_activity(self, file_path: str):
        """记录活跃文件（去重）"""
        if self._current_session and file_path not in self._current_session.active_files:
            self._current_session.active_files.append(file_path)

    async def set_task_progress(self, progress: str):
        """设置任务进度描述"""
        if self._current_session:
            self._current_session.task_progress = progress
            await self._save_checkpoint()

    async def set_user_preference(self, key: str, value):
        """设置用户偏好"""
        if self._current_session:
            self._current_session.user_preferences[key] = value

    def record_token_usage(self, usage: dict):
        """记录 Token 消耗"""
        if self._current_session:
            self._current_session.token_usage = usage

    # ── 查询操作 ──

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """列出历史会话（按时间倒序）

        Args:
            limit: 最大返回数量

        Returns:
            [{"session_id": ..., "created_at": ..., "summary": ..., ...}, ...]
        """
        sessions = []
        for f in sorted(
            self._memory_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id"),
                    "created_at": data.get("created_at"),
                    "summary": data.get("summary", "")[:200],
                    "message_count": data.get("message_count", 0),
                    "task_progress": data.get("task_progress", ""),
                })
            except (json.JSONDecodeError, OSError):
                pass
        return sessions

    def get_session(self, session_id: str) -> dict | None:
        """获取指定会话详情"""
        path = self._memory_dir / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def delete_session(self, session_id: str) -> bool:
        """删除会话记忆"""
        path = self._memory_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def search_sessions(self, query: str, limit: int = 10) -> list[dict]:
        """关键词搜索会话（全文搜索摘要和决策）

        Args:
            query: 搜索关键词
            limit: 最大返回数量

        Returns:
            匹配的会话列表
        """
        results = []
        for f in sorted(
            self._memory_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            if len(results) >= limit:
                break
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                text = json.dumps(data, ensure_ascii=False).lower()
                if query.lower() in text:
                    results.append({
                        "session_id": data.get("session_id"),
                        "created_at": data.get("created_at"),
                        "summary": data.get("summary", "")[:200],
                        "task_progress": data.get("task_progress", ""),
                    })
            except (json.JSONDecodeError, OSError):
                pass
        return results

    def export_session(self, session_id: str) -> str | None:
        """导出会话为 Markdown

        Returns:
            Markdown 格式字符串或 None
        """
        data = self.get_session(session_id)
        if not data:
            return None

        lines = [
            f"# 会话: {session_id}",
            "",
            f"**时间**: {data.get('created_at', '')}",
            f"**工作区**: {data.get('workspace', '')}",
            f"**消息数**: {data.get('message_count', 0)}",
            "",
            "## 摘要",
            "",
            data.get("summary", "无"),
            "",
            "## 任务进度",
            "",
            data.get("task_progress", "无"),
            "",
            "## 关键决策",
            "",
        ]
        for d in data.get("key_decisions", []):
            lines.append(f"- {d}")
        lines.extend(["", "## 活跃文件", ""])
        for f in data.get("active_files", []):
            lines.append(f"- {f}")
        return "\n".join(lines)

    # ── 内部方法 ──

    async def _generate_summary(self) -> str:
        """使用 LLM 生成会话摘要"""
        if not self._current_session:
            return ""

        if not self._llm:
            # 无 LLM，生成简单摘要
            parts = []
            if self._current_session.task_progress:
                parts.append(f"任务进度: {self._current_session.task_progress}")
            if self._current_session.key_decisions:
                parts.append(
                    f"关键决策: {'; '.join(self._current_session.key_decisions[-3:])}"
                )
            if self._current_session.active_files:
                parts.append(
                    f"活跃文件: {', '.join(self._current_session.active_files[-5:])}"
                )
            return " | ".join(parts) if parts else "无"

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
        except (OSError, RuntimeError, ValueError, AttributeError) as e:
            logger.debug("session_summarize_failed: %s", e)
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
            self._memory_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not session_files:
            return ""

        try:
            data = json.loads(session_files[0].read_text(encoding="utf-8"))
            return data.get("summary", "")
        except (json.JSONDecodeError, OSError):
            return ""

    async def _save_checkpoint(self):
        """保存检查点"""
        if self._current_session:
            self._current_session.updated_at = datetime.now(UTC).isoformat()
            self._current_session.message_count = self._message_counter
            self._save_session(self._current_session)

    @property
    def current_session(self) -> SessionMemory | None:
        return self._current_session

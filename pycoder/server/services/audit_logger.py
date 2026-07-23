"""
全链路审计日志 — 借鉴生产级 Agent 团队方案

记录每次 Agent 工具调用的完整信息，满足:
  - 操作可追溯: 谁、何时、做了什么、结果如何
  - 合规审计: 全链路操作日志
  - 调试辅助: 快速定位问题

用法:
  from pycoder.server.services.audit_logger import AuditLogger, AuditEntry

  logger = AuditLogger()
  logger.log("read_file", {"path": "app.py"}, "success", duration_ms=1.2)
  logger.log("execute_code", {"code": "..."}, "failed", error="SyntaxError")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """审计日志条目"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)
    agent_role: str = ""
    tool_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result: str = ""          # success / failed / blocked
    error: str = ""
    duration_ms: float = 0.0
    workspace: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_role": self.agent_role,
            "tool_name": self.tool_name,
            "params": self._sanitize_params(self.params),
            "result": self.result,
            "error": self.error[:500] if self.error else "",
            "duration_ms": round(self.duration_ms, 2),
            "workspace": self.workspace,
            "session_id": self.session_id,
        }

    @staticmethod
    def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
        """过滤敏感参数"""
        sensitive_keys = {"api_key", "password", "token", "secret", "key", "auth", "credential"}
        safe = {}
        for k, v in params.items():
            if any(s in k.lower() for s in sensitive_keys):
                safe[k] = "***REDACTED***"
            elif isinstance(v, str) and len(v) > 500:
                safe[k] = v[:500] + "..."
            else:
                safe[k] = v
        return safe


class AuditLogger:
    """全链路审计日志器

    特性:
      - JSONL 格式持久化（每行一条记录，追加写入）
      - 内存缓存（最近 N 条，快速查询）
      - 自动轮转（按日期分割日志文件）
      - 敏感信息脱敏
    """

    def __init__(
        self,
        workspace: Path | None = None,
        max_memory_entries: int = 1000,
        auto_flush: bool = True,
    ):
        self._workspace = workspace or Path.home() / ".pycoder"
        self._log_dir = self._workspace / "audit_logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._max_memory = max_memory_entries
        self._auto_flush = auto_flush

        # 内存缓存
        self._entries: list[AuditEntry] = []
        self._total_count: int = 0

        # 统计
        self._stats: dict[str, dict[str, int]] = {}  # 按工具名统计

    def _log_file(self) -> Path:
        """当天日志文件"""
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"audit_{date_str}.jsonl"

    def log(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        result: str = "success",
        *,
        error: str = "",
        duration_ms: float = 0.0,
        agent_role: str = "",
        session_id: str = "",
        workspace: str = "",
    ) -> AuditEntry:
        """记录一条审计日志

        Args:
            tool_name: 工具名称
            params: 工具参数
            result: 结果 (success/failed/blocked)
            error: 错误信息
            duration_ms: 执行耗时
            agent_role: Agent 角色
            session_id: 会话 ID
            workspace: 工作区路径

        Returns:
            AuditEntry
        """
        entry = AuditEntry(
            tool_name=tool_name,
            params=params or {},
            result=result,
            error=error,
            duration_ms=duration_ms,
            agent_role=agent_role,
            session_id=session_id,
            workspace=workspace,
        )

        # 内存缓存
        self._entries.append(entry)
        self._total_count += 1
        if len(self._entries) > self._max_memory:
            self._entries = self._entries[-self._max_memory:]

        # 统计
        if tool_name not in self._stats:
            self._stats[tool_name] = {"success": 0, "failed": 0, "blocked": 0}
        self._stats[tool_name][result] = self._stats[tool_name].get(result, 0) + 1

        # 持久化
        if self._auto_flush:
            self._flush_entry(entry)

        return entry

    def _flush_entry(self, entry: AuditEntry) -> None:
        """将单条记录写入 JSONL 文件"""
        try:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("audit_flush_error: %s", e)

    def flush(self) -> int:
        """批量刷新所有缓存记录到磁盘"""
        count = 0
        try:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                for entry in self._entries:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                    count += 1
        except OSError as e:
            logger.warning("audit_flush_error: %s", e)
        return count

    def query(
        self,
        *,
        tool_name: str | None = None,
        result: str | None = None,
        min_duration_ms: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """查询审计日志

        Args:
            tool_name: 按工具名筛选
            result: 按结果筛选 (success/failed/blocked)
            min_duration_ms: 最小耗时筛选
            limit: 返回数量
            offset: 偏移量

        Returns:
            匹配的审计条目列表
        """
        matched: list[dict[str, Any]] = []
        for entry in reversed(self._entries):
            if tool_name and entry.tool_name != tool_name:
                continue
            if result and entry.result != result:
                continue
            if min_duration_ms and entry.duration_ms < min_duration_ms:
                continue
            matched.append(entry.to_dict())
            if len(matched) >= limit + offset:
                break
        return matched[offset:offset + limit]

    def get_stats(self) -> dict[str, Any]:
        """获取审计统计"""
        total_success = sum(s.get("success", 0) for s in self._stats.values())
        total_failed = sum(s.get("failed", 0) for s in self._stats.values())
        total = total_success + total_failed

        return {
            "total_entries": self._total_count,
            "total_success": total_success,
            "total_failed": total_failed,
            "success_rate": round(total_success / max(total, 1), 3),
            "by_tool": dict(self._stats),
            "log_file": str(self._log_file()),
            "memory_entries": len(self._entries),
        }

    def cleanup_old_logs(self, max_age_days: int = 90) -> int:
        """清理超过指定天数的审计日志"""
        cutoff = time.time() - max_age_days * 86400
        cleaned = 0
        for f in self._log_dir.glob("audit_*.jsonl"):
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    cleaned += 1
                except OSError:
                    pass
        if cleaned:
            logger.info("audit_cleanup: cleaned=%d files", cleaned)
        return cleaned


# ── 全局单例 ──
_global_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """获取全局审计日志器"""
    global _global_audit_logger
    if _global_audit_logger is None:
        _global_audit_logger = AuditLogger()
    return _global_audit_logger
"""
审计追踪 — 不可变操作日志

每次 AI 操作都记录完整的审计日志，包括:
- 谁在什么时候做了什么操作
- 是否经过用户确认
- 操作结果和影响
- 支持回溯任意时间点的系统状态
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    """单条审计记录"""
    # 基础信息
    trace_id: str
    timestamp: float = field(default_factory=time.time)
    iso_time: str = ""

    # 操作信息
    capability_id: str = ""
    params_summary: str = ""
    permission_level: int = 0
    decision: str = ""            # 允许/拒绝/需要确认
    user_confirmed: bool = False

    # 结果信息
    success: bool = False
    result_summary: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    rollback_used: bool = False

    # 上下文
    session_id: str = ""
    project_path: str = ""
    caller: str = "unknown"

    # 变更信息（写操作记录 diff）
    diff_summary: str | None = None
    files_modified: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.iso_time:
            from datetime import datetime
            self.iso_time = datetime.fromtimestamp(self.timestamp).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "iso_time": self.iso_time,
            "capability_id": self.capability_id,
            "params_summary": self.params_summary,
            "permission_level": self.permission_level,
            "decision": self.decision,
            "user_confirmed": self.user_confirmed,
            "success": self.success,
            "result_summary": self.result_summary,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "rollback_used": self.rollback_used,
            "session_id": self.session_id,
            "project_path": self.project_path,
            "caller": self.caller,
            "diff_summary": self.diff_summary,
            "files_modified": self.files_modified,
        }


class AuditTrail:
    """
    审计追踪 — 不可变（append-only）操作日志

    特性:
    - 每条记录包含完整上下文
    - 按时间/能力/用户/结果多维过滤
    - 生成安全合规报告
    - 异常模式自动检测
    """

    def __init__(self, max_records: int = 100000, persist_path: Path | None = None):
        self._records: list[AuditRecord] = []
        self._max_records = max_records
        self._persist_path = persist_path
        self._indices: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self._session_id = str(uuid.uuid4())

    def log(self, record: AuditRecord) -> None:
        """记录一条审计日志"""
        record.session_id = record.session_id or self._session_id
        self._records.append(record)

        # 维护索引
        idx = len(self._records) - 1
        self._indices["capability"][record.capability_id].append(idx)
        self._indices["decision"][record.decision].append(idx)
        self._indices["session"][record.session_id].append(idx)
        self._indices["success"][str(record.success)].append(idx)
        self._indices["caller"][record.caller].append(idx)

        # 检查容量
        if len(self._records) > self._max_records * 1.2:
            self._compact()

        # 持久化（如果启用）
        if self._persist_path:
            self._persist_record(record)

    def query(
        self,
        *,
        capability_id: str | None = None,
        session_id: str | None = None,
        success: bool | None = None,
        decision: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """
        多维查询审计记录

        Args:
            capability_id: 按能力 ID 过滤
            session_id: 按会话过滤
            success: 按成功/失败过滤
            decision: 按决策类型过滤
            since: 起始时间戳
            until: 结束时间戳
            limit: 返回上限
            offset: 偏移量
        """
        # 使用索引加速
        candidate_indices: set[int] | None = None

        if capability_id and capability_id in self._indices["capability"]:
            s = set(self._indices["capability"][capability_id])
            candidate_indices = s if candidate_indices is None else candidate_indices & s

        if session_id and session_id in self._indices["session"]:
            s = set(self._indices["session"][session_id])
            candidate_indices = s if candidate_indices is None else candidate_indices & s

        if decision and decision in self._indices["decision"]:
            s = set(self._indices["decision"][decision])
            candidate_indices = s if candidate_indices is None else candidate_indices & s

        if success is not None:
            s = set(self._indices["success"][str(success)])
            candidate_indices = s if candidate_indices is None else candidate_indices & s

        # 获取候选记录
        if candidate_indices is not None:
            records = [self._records[i] for i in sorted(candidate_indices)]
        else:
            records = list(self._records)

        # 时间过滤
        if since is not None:
            records = [r for r in records if r.timestamp >= since]
        if until is not None:
            records = [r for r in records if r.timestamp <= until]

        return records[offset:offset + limit]

    def get_recent(self, limit: int = 50) -> list[AuditRecord]:
        """获取最近的审计记录"""
        return list(reversed(self._records[-limit:]))

    def get_by_trace_id(self, trace_id: str) -> AuditRecord | None:
        """通过 trace_id 查找记录"""
        for r in reversed(self._records):
            if r.trace_id == trace_id:
                return r
        return None

    def generate_report(self, since: float | None = None) -> dict[str, Any]:
        """生成安全合规报告"""
        records = self._records
        if since is not None:
            records = [r for r in records if r.timestamp >= since]

        if not records:
            return {"total_operations": 0}

        total = len(records)
        success_count = sum(1 for r in records if r.success)
        confirmed_count = sum(1 for r in records if r.user_confirmed)
        rollback_count = sum(1 for r in records if r.rollback_used)

        # 按能力分组
        by_capability: dict[str, int] = defaultdict(int)
        for r in records:
            by_capability[r.capability_id] += 1

        # 按决策分组
        by_decision: dict[str, int] = defaultdict(int)
        for r in records:
            by_decision[r.decision] += 1

        # 时间范围
        time_range = {
            "start": min(r.iso_time for r in records),
            "end": max(r.iso_time for r in records),
        }

        return {
            "total_operations": total,
            "success_rate": success_count / max(total, 1),
            "user_confirmed_rate": confirmed_count / max(total, 1),
            "rollback_rate": rollback_count / max(total, 1),
            "avg_duration_ms": sum(r.duration_ms for r in records) / max(total, 1),
            "top_capabilities": sorted(by_capability.items(), key=lambda x: x[1], reverse=True)[:10],
            "decision_distribution": dict(by_decision),
            "time_range": time_range,
            "anomalies": self._detect_anomalies(records),
        }

    def export(self, format: str = "json") -> str:
        """导出审计日志"""
        if format == "json":
            return json.dumps(
                [r.to_dict() for r in self._records],
                ensure_ascii=False,
                indent=2,
            )
        elif format == "csv":
            if not self._records:
                return ""
            headers = list(self._records[0].to_dict().keys())
            lines = [",".join(headers)]
            for r in self._records:
                lines.append(",".join(str(r.to_dict().get(h, "")) for h in headers))
            return "\n".join(lines)
        return json.dumps([r.to_dict() for r in self._records], ensure_ascii=False)

    def clear(self) -> None:
        """清空审计日志"""
        self._records.clear()
        self._indices.clear()

    def _compact(self) -> None:
        """压缩记录（保留最近的）"""
        keep = self._max_records
        self._records = self._records[-keep:]
        self._rebuild_indices()

    def _rebuild_indices(self) -> None:
        """重建索引"""
        self._indices = defaultdict(lambda: defaultdict(list))
        for i, record in enumerate(self._records):
            self._indices["capability"][record.capability_id].append(i)
            self._indices["decision"][record.decision].append(i)
            self._indices["session"][record.session_id].append(i)
            self._indices["success"][str(record.success)].append(i)
            self._indices["caller"][record.caller].append(i)

    def _persist_record(self, record: AuditRecord) -> None:
        """持久化单条记录"""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("审计日志持久化失败: %s", e)

    def _detect_anomalies(self, records: list[AuditRecord]) -> list[str]:
        """检测异常模式"""
        anomalies: list[str] = []

        if len(records) < 10:
            return anomalies

        # 检测短期高频操作
        time_window = 60  # 60 秒窗口
        recent = [r for r in records if r.timestamp > time.time() - time_window]
        if len(recent) > 50:
            anomalies.append(f"高频操作: {len(recent)} 次 / {time_window} 秒")

        # 检测持续失败
        last_10 = records[-10:]
        failures = sum(1 for r in last_10 if not r.success)
        if failures >= 8:
            anomalies.append(f"持续失败: 最近 10 次操作中 {failures} 次失败")

        # 检测高危操作聚集
        high_risk = sum(1 for r in records[-50:] if r.permission_level >= 3)
        if high_risk >= 10:
            anomalies.append(f"高危操作聚集: 最近 50 次操作中 {high_risk} 次高级权限操作")

        return anomalies

    @property
    def record_count(self) -> int:
        return len(self._records)

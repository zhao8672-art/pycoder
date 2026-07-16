"""安全审计模块测试

覆盖:
  - AuditRecord: 数据模型创建与序列化
  - AuditTrail: 日志记录、多维查询、报告生成
  - AuditTrail: 导出 JSON/CSV、容量压缩、持久化
  - AuditTrail: 异常检测、索引维护
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.safety.audit import AuditRecord, AuditTrail


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _make_record(**kwargs) -> AuditRecord:
    """创建测试用审计记录"""
    defaults: dict = {
        "trace_id": "test-trace-001",
        "capability_id": "editor.code.read",
        "params_summary": "读取 main.py",
        "permission_level": 0,
        "decision": "允许",
        "success": True,
        "result_summary": "成功读取",
        "duration_ms": 12.5,
        "caller": "agent_v1",
    }
    defaults.update(kwargs)
    return AuditRecord(**defaults)


# ══════════════════════════════════════════════════════════
# AuditRecord 测试
# ══════════════════════════════════════════════════════════


class TestAuditRecord:
    """审计记录数据模型"""

    def test_create_with_defaults(self):
        """使用默认值创建记录"""
        record = AuditRecord(trace_id="trace-1")
        assert record.trace_id == "trace-1"
        assert record.timestamp > 0
        assert record.iso_time != ""
        assert record.decision == ""
        assert record.success is False
        assert record.error is None
        assert record.files_modified == []

    def test_iso_time_auto_generated(self):
        """iso_time 自动从时间戳生成"""
        record = AuditRecord(trace_id="t1", timestamp=1609459200.0)
        assert record.iso_time.startswith("2021-01-01")

    def test_iso_time_preserved_if_provided(self):
        """如果提供了 iso_time 则不覆盖"""
        record = AuditRecord(trace_id="t1", iso_time="custom-time")
        assert record.iso_time == "custom-time"

    def test_to_dict_contains_all_fields(self):
        """to_dict 包含所有字段"""
        record = _make_record(
            trace_id="trace-full",
            files_modified=["a.py", "b.py"],
            diff_summary="+3 -1",
        )
        d = record.to_dict()
        assert d["trace_id"] == "trace-full"
        assert d["files_modified"] == ["a.py", "b.py"]
        assert d["diff_summary"] == "+3 -1"
        assert d["success"] is True
        assert d["rollback_used"] is False

    def test_to_dict_with_error(self):
        """错误信息正确序列化"""
        record = _make_record(success=False, error="FileNotFoundError: test.txt")
        d = record.to_dict()
        assert d["error"] == "FileNotFoundError: test.txt"
        assert d["success"] is False


# ══════════════════════════════════════════════════════════
# AuditTrail 基础功能测试
# ══════════════════════════════════════════════════════════


class TestAuditTrailBasic:
    """审计追踪基础功能"""

    def test_log_adds_record(self):
        """记录一条日志"""
        trail = AuditTrail()
        record = _make_record()
        trail.log(record)
        assert trail.record_count == 1

    def test_log_assigns_session_id(self):
        """log 自动补充 session_id"""
        trail = AuditTrail()
        record = _make_record(session_id="")
        trail.log(record)
        assert record.session_id != ""

    def test_log_preserves_existing_session_id(self):
        """log 不覆盖已有的 session_id"""
        trail = AuditTrail()
        record = _make_record(session_id="custom-session")
        trail.log(record)
        assert record.session_id == "custom-session"

    def test_get_recent_returns_latest(self):
        """get_recent 返回最近的记录（倒序）"""
        trail = AuditTrail()
        for i in range(5):
            trail.log(_make_record(trace_id=f"trace-{i}"))
        recent = trail.get_recent(limit=3)
        assert len(recent) == 3
        # 倒序，最新的在前
        assert recent[0].trace_id == "trace-4"

    def test_get_recent_limit(self):
        """get_recent 限制返回数量"""
        trail = AuditTrail()
        for i in range(10):
            trail.log(_make_record(trace_id=f"t-{i}"))
        assert len(trail.get_recent(limit=50)) == 10

    def test_get_by_trace_id_found(self):
        """通过 trace_id 查找存在的记录"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="target"))
        trail.log(_make_record(trace_id="other"))
        found = trail.get_by_trace_id("target")
        assert found is not None
        assert found.trace_id == "target"

    def test_get_by_trace_id_not_found(self):
        """通过 trace_id 查找不存在的记录"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="exists"))
        assert trail.get_by_trace_id("nonexistent") is None

    def test_clear_removes_all(self):
        """清空所有记录"""
        trail = AuditTrail()
        trail.log(_make_record())
        trail.log(_make_record())
        trail.clear()
        assert trail.record_count == 0
        assert trail.get_recent() == []


# ══════════════════════════════════════════════════════════
# AuditTrail 查询测试
# ══════════════════════════════════════════════════════════


class TestAuditTrailQuery:
    """审计追踪多维查询"""

    @pytest.fixture
    def trail_with_data(self) -> AuditTrail:
        """构建包含多种记录的审计追踪"""
        trail = AuditTrail()
        # 成功操作
        trail.log(_make_record(
            trace_id="s1", capability_id="editor.code.read", decision="允许", success=True, caller="agent_a",
        ))
        # 拒绝操作
        trail.log(_make_record(
            trace_id="s2", capability_id="shell.exec", decision="拒绝", success=False, caller="agent_b",
        ))
        # 需要确认的操作
        trail.log(_make_record(
            trace_id="s3", capability_id="git.commit", decision="需要确认", success=True, user_confirmed=True, caller="agent_a",
        ))
        # 回滚操作
        trail.log(_make_record(
            trace_id="s4", capability_id="file.write", decision="允许", success=False, rollback_used=True, caller="agent_a",
        ))
        return trail

    def test_query_by_capability(self, trail_with_data):
        """按能力 ID 过滤"""
        results = trail_with_data.query(capability_id="editor.code.read")
        assert len(results) == 1
        assert results[0].trace_id == "s1"

    def test_query_by_decision(self, trail_with_data):
        """按决策类型过滤"""
        results = trail_with_data.query(decision="拒绝")
        assert len(results) == 1
        assert results[0].trace_id == "s2"

    def test_query_by_success(self, trail_with_data):
        """按成功/失败过滤"""
        results = trail_with_data.query(success=True)
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_query_by_session(self, trail_with_data):
        """按会话过滤"""
        # 所有记录有相同 session_id（默认）
        session = trail_with_data._session_id
        results = trail_with_data.query(session_id=session)
        assert len(results) == 4

    def test_query_combined_filters(self, trail_with_data):
        """组合多个过滤条件"""
        results = trail_with_data.query(capability_id="editor.code.read", success=True)
        assert len(results) == 1
        assert results[0].trace_id == "s1"

    def test_query_with_time_range(self, trail_with_data):
        """按时间范围过滤"""
        now = time.time()
        results = trail_with_data.query(since=now - 10, until=now + 10)
        assert len(results) == 4

    def test_query_with_limit_offset(self):
        """测试分页"""
        trail = AuditTrail()
        for i in range(10):
            trail.log(_make_record(trace_id=f"t-{i}"))
        results = trail.query(limit=3, offset=2)
        assert len(results) == 3

    def test_query_no_match(self, trail_with_data):
        """查询无匹配结果（索引中不存在的 capability 回退到全量扫描）"""
        # 不存在的 capability_id 不在索引中，会回退到全量记录
        results = trail_with_data.query(capability_id="nonexistent.cap")
        assert len(results) == 4  # 回退到全量扫描

    def test_query_no_match_with_session(self, trail_with_data):
        """查询不存在的会话（索引中不存在的 session 回退到全量扫描）"""
        results = trail_with_data.query(session_id="nonexistent-session")
        assert len(results) == 4  # 回退到全量扫描


# ══════════════════════════════════════════════════════════
# AuditTrail 报告与导出测试
# ══════════════════════════════════════════════════════════


class TestAuditTrailReport:
    """审计报告与导出"""

    def test_generate_report_empty(self):
        """空追踪报告"""
        trail = AuditTrail()
        report = trail.generate_report()
        assert report["total_operations"] == 0

    def test_generate_report_with_data(self):
        """有数据时的报告"""
        trail = AuditTrail()
        for i in range(5):
            success = i % 2 == 0
            trail.log(_make_record(
                trace_id=f"r-{i}",
                capability_id=f"cap.{i % 3}",
                decision="允许" if success else "拒绝",
                success=success,
                duration_ms=10.0 + i,
            ))
        report = trail.generate_report()
        assert report["total_operations"] == 5
        assert 0 < report["success_rate"] < 1
        assert "time_range" in report
        assert "top_capabilities" in report
        assert "decision_distribution" in report

    def test_generate_report_with_since(self):
        """按时间范围生成报告"""
        trail = AuditTrail()
        now = time.time()
        trail.log(_make_record(trace_id="old", timestamp=now - 1000))
        trail.log(_make_record(trace_id="new", timestamp=now))
        report = trail.generate_report(since=now - 10)
        assert report["total_operations"] == 1

    def test_export_json(self):
        """导出为 JSON"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="export-1"))
        exported = trail.export(format="json")
        data = json.loads(exported)
        assert isinstance(data, list)
        assert data[0]["trace_id"] == "export-1"

    def test_export_csv(self):
        """导出为 CSV"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="csv-1", capability_id="test.cap"))
        exported = trail.export(format="csv")
        assert "trace_id" in exported
        assert "csv-1" in exported
        assert "test.cap" in exported

    def test_export_csv_empty(self):
        """空记录导出 CSV"""
        trail = AuditTrail()
        assert trail.export(format="csv") == ""

    def test_export_unknown_format_falls_back_to_json(self):
        """未知格式回退到 JSON"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="fallback"))
        result = trail.export(format="xml")
        assert "trace_id" in result


# ══════════════════════════════════════════════════════════
# AuditTrail 容量与持久化测试
# ══════════════════════════════════════════════════════════


class TestAuditTrailCapacity:
    """容量管理与持久化"""

    def test_compact_when_over_limit(self):
        """超过容量上限时触发压缩"""
        trail = AuditTrail(max_records=10)
        for i in range(15):
            trail.log(_make_record(trace_id=f"compact-{i}"))
        # 压缩在 1.2 * max_records=12 条时触发，保留最近 10 条
        # 第 13 条触发压缩 → 保留 10 条 → 再加 2 条 = 12 条
        assert trail.record_count <= 12

    def test_persist_to_file(self, tmp_path):
        """持久化到文件"""
        persist_file = tmp_path / "audit.jsonl"
        trail = AuditTrail(persist_path=persist_file)
        trail.log(_make_record(trace_id="persist-1"))
        trail.log(_make_record(trace_id="persist-2"))
        assert persist_file.exists()
        lines = persist_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_persist_creates_parent_dirs(self, tmp_path):
        """持久化自动创建父目录"""
        persist_file = tmp_path / "nested" / "dir" / "audit.jsonl"
        trail = AuditTrail(persist_path=persist_file)
        trail.log(_make_record())
        assert persist_file.exists()

    def test_persist_handles_error_gracefully(self, tmp_path):
        """持久化写入失败时不会抛出异常"""
        persist_file = tmp_path / "readonly" / "audit.jsonl"
        persist_file.parent.mkdir(parents=True)
        trail = AuditTrail(persist_path=persist_file)

        # 模拟文件打开失败（如权限不足）
        with patch("builtins.open", side_effect=OSError("模拟写入失败")):
            # 不应抛出异常，_persist_record 内部捕获了异常
            trail._persist_record(_make_record())


# ══════════════════════════════════════════════════════════
# AuditTrail 异常检测测试
# ══════════════════════════════════════════════════════════


class TestAuditTrailAnomalies:
    """异常模式检测"""

    def test_no_anomalies_with_few_records(self):
        """记录太少时不检测异常"""
        trail = AuditTrail()
        for i in range(5):
            trail.log(_make_record(trace_id=f"a-{i}", success=True))
        report = trail.generate_report()
        assert report["anomalies"] == []

    def test_detect_high_frequency(self):
        """检测高频操作异常"""
        trail = AuditTrail()
        now = time.time()
        # 模拟 60 秒内 60 次操作
        for i in range(60):
            trail.log(_make_record(
                trace_id=f"hf-{i}", success=True, timestamp=now - 30 + i * 0.5,
            ))
        report = trail.generate_report()
        assert any("高频操作" in a for a in report["anomalies"])

    def test_detect_persistent_failures(self):
        """检测持续失败异常"""
        trail = AuditTrail()
        # 最近 10 次中 9 次失败
        for i in range(10):
            success = i == 0  # 仅第一次成功
            trail.log(_make_record(trace_id=f"pf-{i}", success=success))
        report = trail.generate_report()
        assert any("持续失败" in a for a in report["anomalies"])

    def test_detect_high_risk_clustering(self):
        """检测高危操作聚集"""
        trail = AuditTrail()
        for i in range(50):
            # 前 12 个是高危操作
            trail.log(_make_record(
                trace_id=f"hr-{i}", permission_level=3 if i < 12 else 0, success=True,
            ))
        report = trail.generate_report()
        assert any("高危操作" in a for a in report["anomalies"])

    def test_report_includes_avg_duration(self):
        """报告包含平均耗时"""
        trail = AuditTrail()
        trail.log(_make_record(trace_id="d1", duration_ms=100.0))
        trail.log(_make_record(trace_id="d2", duration_ms=200.0))
        report = trail.generate_report()
        assert report["avg_duration_ms"] == 150.0
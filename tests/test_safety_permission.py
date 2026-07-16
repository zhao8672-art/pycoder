"""权限引擎模块测试

覆盖:
  - DecisionType / PermissionDecision / PermissionRule / BehaviorRecord: 数据模型
  - PermissionEngine: 权限检查（白名单/黑名单/自定义规则/危险参数/关键路径）
  - PermissionEngine: 信任级别检查与批量批准
  - PermissionEngine: 信任提升/降级/紧急锁定
  - PermissionEngine: 行为记录与信任报告
  - PermissionEngine: 模式匹配
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.bus.protocol import SideEffect, TrustLevel
from pycoder.safety.permission import (
    BehaviorRecord,
    DecisionType,
    PermissionDecision,
    PermissionEngine,
    PermissionRule,
)


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════


class TestDecisionType:
    """决策类型枚举"""

    def test_values(self):
        """验证枚举值"""
        assert DecisionType.AUTO_ALLOW == "auto_allow"
        assert DecisionType.AUTO_DENY == "auto_deny"
        assert DecisionType.REQUIRE_CONFIRM == "require_confirm"
        assert DecisionType.ALLOW_BATCH == "allow_batch"


class TestPermissionDecision:
    """权限决策数据模型"""

    def test_defaults(self):
        """默认值"""
        d = PermissionDecision(allowed=False, decision_type=DecisionType.AUTO_DENY)
        assert d.allowed is False
        assert d.reason == ""
        assert d.requires_user_confirm is False

    def test_require_confirm(self):
        """需要确认的决策"""
        d = PermissionDecision(
            allowed=False,
            decision_type=DecisionType.REQUIRE_CONFIRM,
            reason="需要确认",
            requires_user_confirm=True,
            confirm_message="请确认操作",
        )
        assert d.requires_user_confirm is True
        assert d.confirm_message == "请确认操作"


class TestPermissionRule:
    """权限规则"""

    def test_create_rule(self):
        """创建规则"""
        rule = PermissionRule(
            pattern="editor.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_ALLOW,
            description="编辑器操作",
        )
        assert rule.pattern == "editor.*"
        assert rule.trust_level == TrustLevel.READ_ONLY


class TestBehaviorRecord:
    """行为记录"""

    def test_create_record(self):
        """创建行为记录"""
        record = BehaviorRecord(
            capability_id="file.write",
            success=True,
            decision="auto_allow",
            trust_level=1,
            user_approved=False,
            timestamp=1234567890.0,
        )
        assert record.capability_id == "file.write"
        assert record.success is True


# ══════════════════════════════════════════════════════════
# PermissionEngine 权限检查测试
# ══════════════════════════════════════════════════════════


class TestPermissionEngineCheck:
    """权限检查核心逻辑"""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch) -> PermissionEngine:
        """创建权限引擎（默认信任级别 WORKSPACE_WRITE）"""
        # 使用临时目录避免加载磁盘上的历史行为记录
        import pycoder.safety.permission as perm_mod
        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")
        return PermissionEngine(initial_trust=TrustLevel.WORKSPACE_WRITE)

    def test_blacklist_denies(self, engine: PermissionEngine):
        """黑名单中的操作被拒绝"""
        engine.add_blacklist("dangerous.op")
        result = engine.check("dangerous.op", TrustLevel.READ_ONLY)
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY
        assert "黑名单" in result.reason

    def test_whitelist_allows(self, engine: PermissionEngine):
        """白名单中的操作被允许"""
        engine.add_whitelist("trusted.op")
        result = engine.check("trusted.op", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_custom_rule_auto_allow(self, engine: PermissionEngine):
        """自定义规则匹配自动允许"""
        rule = PermissionRule(
            pattern="custom.allow.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_ALLOW,
            description="自定义允许",
        )
        engine.add_rule(rule)
        result = engine.check("custom.allow.test", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_custom_rule_auto_deny(self, engine: PermissionEngine):
        """自定义规则匹配自动拒绝"""
        rule = PermissionRule(
            pattern="custom.deny.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_DENY,
            description="自定义拒绝",
        )
        engine.add_rule(rule)
        result = engine.check("custom.deny.test", TrustLevel.READ_ONLY)
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY

    def test_dangerous_command_params_denied(self, engine: PermissionEngine):
        """危险命令参数被拒绝"""
        result = engine.check(
            "shell.exec",
            TrustLevel.READ_ONLY,
            params={"cmd": "rm -rf /"},
        )
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY
        assert "危险操作" in result.reason

    def test_dangerous_file_path_denied(self, engine: PermissionEngine):
        """危险文件路径被拒绝"""
        result = engine.check(
            "file.read",
            TrustLevel.READ_ONLY,
            params={"path": "/etc/passwd"},
        )
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY

    def test_critical_path_with_insufficient_trust(self, engine: PermissionEngine):
        """关键路径操作需要完全自主权限"""
        result = engine.check(
            "file.write",
            TrustLevel.READ_ONLY,
            params={"path": ".env"},
        )
        assert result.allowed is False
        assert "关键路径" in result.reason

    def test_trust_level_sufficient_auto_allows(self, engine: PermissionEngine):
        """信任级别足够时自动允许"""
        result = engine.check("editor.code.read", TrustLevel.READ_ONLY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_trust_level_insufficient_requires_confirm(self, engine: PermissionEngine):
        """信任级别不足时需要确认"""
        result = engine.check("shell.exec", TrustLevel.SYSTEM_ACCESS)
        assert result.allowed is False
        assert result.decision_type == DecisionType.REQUIRE_CONFIRM
        assert result.requires_user_confirm is True
        assert "信任级别" in result.reason

    def test_safe_params_not_denied(self, engine: PermissionEngine):
        """安全参数不会被拒绝"""
        result = engine.check(
            "shell.exec",
            TrustLevel.READ_ONLY,
            params={"cmd": "echo hello"},
        )
        # 不应因危险参数被拒绝（echo 不在危险列表中）
        # 但可能因信任级别不足被拒绝
        assert result.decision_type != DecisionType.AUTO_DENY or "危险" not in result.reason


# ══════════════════════════════════════════════════════════
# PermissionEngine 信任级别管理测试
# ══════════════════════════════════════════════════════════


class TestPermissionEngineTrust:
    """信任级别管理"""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch) -> PermissionEngine:
        """创建权限引擎（使用临时目录隔离行为历史）"""
        import pycoder.safety.permission as perm_mod
        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")
        return PermissionEngine(initial_trust=TrustLevel.WORKSPACE_WRITE)

    def test_set_trust_level(self):
        """手动设置信任级别"""
        engine = PermissionEngine(initial_trust=TrustLevel.READ_ONLY)
        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        assert engine.current_trust == TrustLevel.FULL_AUTONOMY

    def test_emergency_lockdown(self):
        """紧急锁定降到只读"""
        engine = PermissionEngine(initial_trust=TrustLevel.PROJECT_WRITE)
        engine.emergency_lockdown()
        assert engine.current_trust == TrustLevel.READ_ONLY

    def test_escalate_trust_insufficient_history(self, engine: PermissionEngine):
        """行为记录不足时拒绝提升"""
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "50" in msg

    def test_escalate_trust_with_good_history(self, engine: PermissionEngine):
        """良好行为记录下成功提升"""
        # 填充 100 条成功记录
        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op",
                success=True,
                decision="auto_allow",
                trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is True
        assert engine.current_trust == TrustLevel.PROJECT_WRITE
        assert "提升" in msg

    def test_escalate_trust_with_rollbacks(self, engine: PermissionEngine):
        """有回滚记录时拒绝提升"""
        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op",
                success=True,
                decision="auto_allow",
                trust_level=1,
                rollback_used=(i < 5),  # 前 5 条有回滚
            ))
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "回滚" in msg

    def test_escalate_trust_low_success_rate(self, engine: PermissionEngine):
        """成功率不足时拒绝提升"""
        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op",
                success=(i < 80),  # 80% 成功率
                decision="auto_allow",
                trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "成功率" in msg

    def test_escalate_trust_at_max_level(self, engine: PermissionEngine):
        """已达最高级别不再提升"""
        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        for _ in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=True, decision="auto_allow", trust_level=4,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "最高" in msg

    def test_revoke_trust(self):
        """安全事件降级"""
        engine = PermissionEngine(initial_trust=TrustLevel.PROJECT_WRITE)
        engine.revoke_trust("检测到异常操作")
        assert engine.current_trust == TrustLevel.WORKSPACE_WRITE

    def test_revoke_trust_at_readonly(self):
        """只读级别不再降级"""
        engine = PermissionEngine(initial_trust=TrustLevel.READ_ONLY)
        engine.revoke_trust("测试")
        assert engine.current_trust == TrustLevel.READ_ONLY


# ══════════════════════════════════════════════════════════
# PermissionEngine 行为记录与持久化测试
# ══════════════════════════════════════════════════════════


class TestPermissionEngineBehavior:
    """行为记录与持久化"""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch) -> PermissionEngine:
        """创建权限引擎（使用临时目录）"""
        import pycoder.safety.permission as perm_mod
        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")
        return PermissionEngine()

    def test_record_behavior(self, engine: PermissionEngine):
        """记录行为"""
        engine.record_behavior(BehaviorRecord(
            capability_id="file.write", success=True, decision="auto_allow",
        ))
        report = engine.get_trust_report()
        assert report["total_behaviors"] == 1

    def test_record_behavior_truncates(self, engine: PermissionEngine):
        """行为记录超过 500 条时截断"""
        for i in range(600):
            engine.record_behavior(BehaviorRecord(
                capability_id=f"op.{i}", success=True, decision="auto_allow",
            ))
        report = engine.get_trust_report()
        assert report["total_behaviors"] <= 500

    def test_persist_and_load_behavior(self, tmp_path, monkeypatch):
        """行为记录持久化到磁盘并加载"""
        import pycoder.safety.permission as perm_mod

        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")

        # 创建引擎并记录行为
        engine = PermissionEngine()
        engine.record_behavior(BehaviorRecord(
            capability_id="persist.test",
            success=True,
            decision="auto_allow",
            trust_level=1,
            user_approved=False,
            timestamp=1234567890.0,
        ))

        # 创建新引擎加载历史
        engine2 = PermissionEngine()
        report = engine2.get_trust_report()
        assert report["total_behaviors"] >= 1

    def test_get_trust_report(self):
        """获取信任状态报告"""
        engine = PermissionEngine()
        engine.add_whitelist("op.a")
        engine.add_whitelist("op.b")
        engine.add_blacklist("op.c")

        for i in range(10):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=(i > 0), decision="auto_allow",
            ))

        report = engine.get_trust_report()
        assert report["current_trust"] == TrustLevel.WORKSPACE_WRITE.name
        assert report["whitelist_count"] == 2
        assert report["blacklist_count"] == 1
        assert "recent_success_rate" in report
        assert "batch_approvals" in report


# ══════════════════════════════════════════════════════════
# PermissionEngine 模式匹配测试
# ══════════════════════════════════════════════════════════


class TestPermissionEnginePatternMatching:
    """模式匹配"""

    def test_exact_match(self):
        """精确匹配"""
        assert PermissionEngine._match_pattern("editor.code.read", "editor.code.read") is True

    def test_wildcard_match(self):
        """通配符匹配"""
        assert PermissionEngine._match_pattern("editor.lsp.completion", "editor.lsp.*") is True

    def test_wildcard_no_match(self):
        """通配符不匹配"""
        assert PermissionEngine._match_pattern("shell.exec", "editor.lsp.*") is False

    def test_prefix_wildcard(self):
        """前缀通配符"""
        assert PermissionEngine._match_pattern("self_evo.scan", "self_evo.*") is True

    def test_middle_wildcard(self):
        """中间通配符"""
        assert PermissionEngine._match_pattern("tools.agent.scan", "tools.agent.*") is True
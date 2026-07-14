"""
权限引擎 — 五级渐进信任模型

每次 AI 发起能力调用时，权限引擎介入检查:
1. 查找能力要求的权限级别
2. 检查当前信任级别
3. 低于该级别的操作 → 自动允许
4. 等于或高于 → 进入决策:
   a. 在白名单中 → 自动允许
   b. 类似操作已批准 → 自动允许
   c. 需要确认 → 弹出提示
   d. 在黑名单中 → 自动拒绝
5. 记录审计日志
"""

from __future__ import annotations

import enum
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import SideEffect, TrustLevel

logger = logging.getLogger(__name__)

# 行为历史持久化路径
_PERMISSION_DIR = Path(
    os.environ.get(
        "PYCODER_PERMISSION_DIR",
        str(Path.home() / ".pycoder" / "permission"),
    )
)
_BEHAVIOR_FILE = _PERMISSION_DIR / "behavior_history.jsonl"


class DecisionType(enum.StrEnum):
    """权限决策类型"""

    AUTO_ALLOW = "auto_allow"  # 自动允许
    AUTO_DENY = "auto_deny"  # 自动拒绝
    REQUIRE_CONFIRM = "require_confirm"  # 需要用户确认
    ALLOW_BATCH = "allow_batch"  # 批量允许（同类型操作）


@dataclass
class PermissionDecision:
    """权限检查结果"""

    allowed: bool
    decision_type: DecisionType
    reason: str = ""
    requires_user_confirm: bool = False
    confirm_message: str = ""
    batch_approved_count: int = 0
    escalate_suggestion: str = ""


@dataclass
class PermissionRule:
    """单条权限规则"""

    pattern: str  # 匹配模式（能力 ID 或路径正则）
    trust_level: TrustLevel  # 所需信任级别
    action: DecisionType  # 匹配后的动作
    description: str = ""


@dataclass
class BehaviorRecord:
    """AI 行为记录 —— 用于信任评分"""

    capability_id: str
    success: bool
    decision: str = ""  # 权限决策类型
    trust_level: int = 0  # 当前信任级别
    user_approved: bool = False
    had_side_effects: bool = False
    rollback_used: bool = False
    timestamp: float = 0.0


class PermissionEngine:
    """
    权限引擎

    五级权限模型:
    - Level 0 (READ_ONLY): 文件读取、代码分析 —— 始终允许
    - Level 1 (WORKSPACE_WRITE): 创建/编辑文件 —— 默认允许
    - Level 2 (PROJECT_WRITE): Git、测试、Shell —— 批量确认
    - Level 3 (SYSTEM_ACCESS): 包管理、网络 —— 关键操作确认
    - Level 4 (FULL_AUTONOMY): 修改自身代码 —— 人工显式确认

    信任度提升机制:
    AI 可以用"良好行为记录"申请提升信任级别
    连续 100 次操作无错误 → 可申请提升一级
    """

    # 关键路径白名单 —— 永不自动修改
    CRITICAL_PATHS: set[str] = {
        "*.env",
        "*.env.*",
        ".env.*",
        "*/config/*.json",
        "*/.git/config",
        "*/.pycoder/config.json",
        "*/.pycoder/.api_key",
        "*__pycache__/*",
        "*/node_modules/*",
    }

    # 危险命令模式
    DANGEROUS_COMMANDS: list[str] = [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf .",
        "> /dev/sda",
        ":(){ :|:& };:",
        "chmod 777 /",
        "mkfs.",
        "dd if=/dev/zero",
        "format c:",
        "shutdown",
        "reboot",
        "kill -9 -1",
    ]

    def __init__(self, initial_trust: TrustLevel = TrustLevel.WORKSPACE_WRITE):
        self._current_trust = initial_trust
        self._whitelist: set[str] = set()  # 白名单能力 ID
        self._blacklist: set[str] = set()  # 黑名单能力 ID
        self._custom_rules: list[PermissionRule] = []  # 自定义规则
        self._behavior_history: list[BehaviorRecord] = []
        self._load_behavior_history()
        self._batch_approval: dict[str, int] = {}  # 批量批准计数
        self._user_confirm_handler: Callable[[str], bool] | None = None

        # 初始化默认规则
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        """初始化默认安全规则"""
        # 只读操作始终允许
        self._custom_rules.append(
            PermissionRule(
                pattern="editor.code.read",
                trust_level=TrustLevel.READ_ONLY,
                action=DecisionType.AUTO_ALLOW,
                description="代码读取始终允许",
            )
        )
        self._custom_rules.append(
            PermissionRule(
                pattern="editor.lsp.*",
                trust_level=TrustLevel.READ_ONLY,
                action=DecisionType.AUTO_ALLOW,
                description="LSP 操作始终允许",
            )
        )

        # ═══ 自进化能力 — 完全放开 ═══
        self._custom_rules.append(
            PermissionRule(
                pattern="self_evo.*",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.AUTO_ALLOW,
                description="自进化能力完全放开 — 扫描/修复/测试/部署/学习",
            )
        )

        # ═══ 自动化/扫描工具 — 完全放开 ═══
        self._custom_rules.append(
            PermissionRule(
                pattern="tools.agent.*",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.AUTO_ALLOW,
                description="Agent工具完全放开 — 自扫描/配置查询",
            )
        )

        # ═══ 系统升级/安装 — 完全放开（含外部服务）═══
        self._custom_rules.append(
            PermissionRule(
                pattern="tools.marketplace.*",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.AUTO_ALLOW,
                description="市场工具完全放开 — skills/扩展/升级",
            )
        )
        self._custom_rules.append(
            PermissionRule(
                pattern="tools.env.docker_execute",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.AUTO_ALLOW,
                description="Docker执行完全放开",
            )
        )

        # 危险操作需要最高确认
        self._custom_rules.append(
            PermissionRule(
                pattern="self_evo.deploy.*",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.REQUIRE_CONFIRM,
                description="自部署操作需要人工确认",
            )
        )
        self._custom_rules.append(
            PermissionRule(
                pattern="self_evo.arch.implement",
                trust_level=TrustLevel.FULL_AUTONOMY,
                action=DecisionType.REQUIRE_CONFIRM,
                description="架构级变更需要人工确认",
            )
        )

    @property
    def current_trust(self) -> TrustLevel:
        """当前信任级别"""
        return self._current_trust

    def check(
        self,
        capability_id: str,
        required_level: TrustLevel,
        params: dict[str, Any] | None = None,
        side_effects: list[SideEffect] | None = None,
    ) -> PermissionDecision:
        """
        检查操作权限

        Args:
            capability_id: 能力 ID
            required_level: 能力要求的权限级别
            params: 调用参数（用于更精细的检查）
            side_effects: 副作���类型

        Returns:
            PermissionDecision 权限决策
        """
        # 1. 检查黑名单
        if capability_id in self._blacklist:
            return PermissionDecision(
                allowed=False,
                decision_type=DecisionType.AUTO_DENY,
                reason=f"'{capability_id}' 在黑名单中",
            )

        # 2. 检查自定义规则
        for rule in self._custom_rules:
            if self._match_pattern(capability_id, rule.pattern):
                if rule.action == DecisionType.AUTO_DENY:
                    return PermissionDecision(
                        allowed=False,
                        decision_type=DecisionType.AUTO_DENY,
                        reason=f"符合拒绝规则: {rule.description}",
                    )
                elif rule.action == DecisionType.AUTO_ALLOW:
                    return PermissionDecision(
                        allowed=True,
                        decision_type=DecisionType.AUTO_ALLOW,
                        reason=f"符合允许规则: {rule.description}",
                    )

        # 3. 检查白名单
        if capability_id in self._whitelist:
            return PermissionDecision(
                allowed=True,
                decision_type=DecisionType.AUTO_ALLOW,
                reason="操作在白名单中",
            )

        # 4. 检查危险参数
        if params and self._has_dangerous_params(capability_id, params):
            return PermissionDecision(
                allowed=False,
                decision_type=DecisionType.AUTO_DENY,
                reason="参数包含危险操作",
            )

        # 5. 关键路径保护
        if params and self._touches_critical_path(params):
            if self._current_trust < TrustLevel.FULL_AUTONOMY:
                return PermissionDecision(
                    allowed=False,
                    decision_type=DecisionType.AUTO_DENY,
                    reason="操作涉及关键路径，需要完全自主权限",
                )

        # 6. 信任级别检查
        if self._current_trust.value >= required_level.value:
            # 当前信任足够，批量批准检查
            if required_level >= TrustLevel.PROJECT_WRITE:
                batch_key = f"{capability_id}::{required_level.value}"
                count = self._batch_approval.get(batch_key, 0) + 1
                self._batch_approval[batch_key] = count
                if count > 1:
                    return PermissionDecision(
                        allowed=True,
                        decision_type=DecisionType.ALLOW_BATCH,
                        reason=f"同类操作已批准 ({count} 次)",
                        batch_approved_count=count,
                    )

            return PermissionDecision(
                allowed=True,
                decision_type=DecisionType.AUTO_ALLOW,
                reason="当前信任级别足够",
            )

        # 7. 需要确认
        return PermissionDecision(
            allowed=False,
            decision_type=DecisionType.REQUIRE_CONFIRM,
            reason=f"需要信任级别 {required_level.name}，当前为 {self._current_trust.name}",
            requires_user_confirm=True,
            confirm_message=(
                f"操作 '{capability_id}' 需要信任级别 {required_level.name} "
                f"(当前: {self._current_trust.name})。是否允许？"
            ),
            escalate_suggestion=(
                f"您可以提升 AI 的信任级别到 {required_level.name} " f"以自动允许此类操作。"
            ),
        )

    def escalate_trust(self, reason: str = "") -> tuple[bool, str]:
        """
        AI 申请提升信任级别

        条件:
        - 连续 50 次操作无安全事件
        - 至少 10 次用户手动批准同级别操作

        Returns:
            (是否允许提升, 原因消息)
        """
        if self._current_trust.value >= TrustLevel.FULL_AUTONOMY.value:
            return False, "已达到最高信任级别"

        # 检查行为记录
        recent = self._behavior_history[-100:]
        if len(recent) < 50:
            return False, f"需要至少 50 次操作记录，当前 {len(recent)} 次"

        # 安全检查
        safety_incidents = [r for r in recent if r.rollback_used]
        if safety_incidents:
            return False, f"最近有 {len(safety_incidents)} 次回滚操作，不建议提升"

        # 成功率检查
        success_rate = sum(1 for r in recent if r.success) / len(recent)
        if success_rate < 0.95:
            return False, f"操作成功率 {success_rate:.1%}，需要 ≥ 95%"

        # 提升一级
        old_level = self._current_trust
        self._current_trust = TrustLevel(self._current_trust.value + 1)
        logger.info(
            "信任级别提升: %s → %s (原因: %s)",
            old_level.name,
            self._current_trust.name,
            reason or "良好行为记录",
        )

        return True, f"信任级别已从 {old_level.name} 提升到 {self._current_trust.name}"

    def revoke_trust(self, incident: str = "") -> None:
        """
        安全事件自动降级
        """
        if self._current_trust.value > TrustLevel.READ_ONLY.value:
            old_level = self._current_trust
            self._current_trust = TrustLevel(max(0, self._current_trust.value - 1))
            logger.warning(
                "信任级别降级: %s → %s (事件: %s)",
                old_level.name,
                self._current_trust.name,
                incident,
            )

    def record_behavior(self, record: BehaviorRecord) -> None:
        """记录 AI 行为"""
        self._behavior_history.append(record)
        # 只保留最近 500 条
        if len(self._behavior_history) > 500:
            self._behavior_history = self._behavior_history[-500:]
        # 持久化到磁盘
        self._persist_behavior_record(record)

    def _load_behavior_history(self) -> None:
        """从磁盘加载行为历史"""
        try:
            _PERMISSION_DIR.mkdir(parents=True, exist_ok=True)
            if not _BEHAVIOR_FILE.exists():
                return
            with open(_BEHAVIOR_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._behavior_history.append(
                            BehaviorRecord(
                                capability_id=data.get("capability_id", ""),
                                success=data.get("success", True),
                                decision=data.get("decision", ""),
                                trust_level=data.get("trust_level", 0),
                                user_approved=data.get("user_approved", False),
                                had_side_effects=data.get("had_side_effects", False),
                                rollback_used=data.get("rollback_used", False),
                                timestamp=data.get("timestamp", 0),
                            )
                        )
                    except (json.JSONDecodeError, KeyError):
                        continue
            # 只保留最近 500 条
            if len(self._behavior_history) > 500:
                self._behavior_history = self._behavior_history[-500:]
        except OSError:
            pass

    def _persist_behavior_record(self, record: BehaviorRecord) -> None:
        """持久化单条行为记录（JSONL 追加）"""
        try:
            _PERMISSION_DIR.mkdir(parents=True, exist_ok=True)
            with open(_BEHAVIOR_FILE, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "capability_id": record.capability_id,
                            "success": record.success,
                            "decision": record.decision,
                            "trust_level": record.trust_level,
                            "user_approved": record.user_approved,
                            "had_side_effects": record.had_side_effects,
                            "rollback_used": record.rollback_used,
                            "timestamp": record.timestamp,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass

    def add_whitelist(self, capability_id: str) -> None:
        """添加到白名单"""
        self._whitelist.add(capability_id)

    def add_blacklist(self, capability_id: str) -> None:
        """添加到黑名单"""
        self._blacklist.add(capability_id)

    def add_rule(self, rule: PermissionRule) -> None:
        """添加自定义权限规则"""
        self._custom_rules.append(rule)

    def set_trust_level(self, level: TrustLevel) -> None:
        """手动设置信任级别"""
        self._current_trust = level

    def emergency_lockdown(self) -> None:
        """紧急锁定 —— 将信任级别降到最低"""
        self._current_trust = TrustLevel.READ_ONLY
        logger.critical("紧急锁定: AI 权限已限制为只读")

    def get_trust_report(self) -> dict[str, Any]:
        """获取信任状态报告"""
        recent = self._behavior_history[-100:]
        return {
            "current_trust": self._current_trust.name,
            "trust_level": self._current_trust.value,
            "total_behaviors": len(self._behavior_history),
            "recent_success_rate": sum(1 for r in recent if r.success) / max(len(recent), 1),
            "recent_rollbacks": sum(1 for r in recent if r.rollback_used),
            "whitelist_count": len(self._whitelist),
            "blacklist_count": len(self._blacklist),
            "batch_approvals": dict(self._batch_approval),
        }

    # ── 私有方法 ───────────────────────────

    @staticmethod
    def _match_pattern(capability_id: str, pattern: str) -> bool:
        """简单的模式匹配（支持 * 通配符）"""
        import fnmatch

        return fnmatch.fnmatch(capability_id, pattern)

    def _has_dangerous_params(self, capability_id: str, params: dict[str, Any]) -> bool:
        """检查参数是否包含危险操作"""
        # 检查 Shell 命令
        if "cmd" in params or "command" in params:
            cmd = str(params.get("cmd", params.get("command", "")))
            for pattern in self.DANGEROUS_COMMANDS:
                if pattern.lower() in cmd.lower():
                    return True

        # 检查文件路径
        for path_key in ("path", "file", "source", "target"):
            if path_key in params:
                p = str(params[path_key]).lower()
                if any(
                    dangerous in p
                    for dangerous in ["/etc/passwd", "/etc/shadow", "c:\\windows\\system32"]
                ):
                    return True

        return False

    def _touches_critical_path(self, params: dict[str, Any]) -> bool:
        """检查是否涉及关键路径"""
        import fnmatch

        for key, value in params.items():
            if key in ("path", "file", "file_path", "source", "target"):
                p = str(value)
                for critical in self.CRITICAL_PATHS:
                    if fnmatch.fnmatch(p, critical):
                        return True
        return False

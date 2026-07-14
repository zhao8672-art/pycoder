"""
AutoPluginManager — 自动插件/Skills 管理总调度器

集成五大组件为完整闭环:
    1. AutoPluginDetector  — 检测缺失能力
    2. AutoPluginEvaluator — 评估候选
    3. AutoPluginInstaller — 安全安装
    4. AutoPluginValidator — 安装后验证
    5. InstallLog / Stats   — 审计与统计

完整执行流程:
    任务触发 → detect() → 列出缺失能力 → evaluate() → 排名
    → 最佳候选 → install() → validate() → 登记日志 → 回调通知

用法:
    from .auto_plugin_manager import AutoPluginManager, get_plugin_manager
    mgr = get_plugin_manager()
    report = await mgr.auto_fulfill("用户消息: 帮我们review代码")
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.services.auto_plugin_detector import (
    AutoPluginDetector,
    CapabilityNeed,
)
from pycoder.server.services.auto_plugin_evaluator import AutoPluginEvaluator
from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller
from pycoder.server.services.auto_plugin_validator import AutoPluginValidator

logger = logging.getLogger(__name__)

# ── 已安装 Skills 注册表路径 ──
_INSTALLED_REGISTRY = Path.home() / ".pycoder" / "installed_skills.json"


@dataclass
class AutoFulfillReport:
    """一次自动补全的完整报告"""

    task_message: str = ""
    detected_needs: list[dict] = field(default_factory=list)  # serialized CapabilityNeed
    evaluated_candidates: list[dict] = field(default_factory=list)
    install_results: list[dict] = field(default_factory=list)
    validation_reports: list[dict] = field(default_factory=list)
    installed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_message": self.task_message[:100],
            "detected_needs": self.detected_needs,
            "installed_count": self.installed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "errors": self.errors[-5:],
            "duration_ms": round(self.duration_ms, 1),
        }


class AutoPluginManager:
    """自动插件/Skills 管理总调度器"""

    def __init__(self):
        self.detector = AutoPluginDetector()
        self.evaluator = AutoPluginEvaluator()
        self.installer = AutoPluginInstaller()
        self.validator = AutoPluginValidator()
        self._ws_callback: Callable[[dict], Awaitable[None]] | None = None
        self._auto_enabled: bool = True  # 是否允许自动安装
        self._require_confirmation: bool = True  # 是否需要用户确认才安装

    def set_ws_callback(self, cb: Callable[[dict], Awaitable[None]]) -> None:
        self._ws_callback = cb

    def configure(self, auto_enabled: bool = True, require_confirmation: bool = True) -> None:
        self._auto_enabled = auto_enabled
        self._require_confirmation = require_confirmation

    async def _emit(self, event: dict) -> None:
        if self._ws_callback:
            try:
                await self._ws_callback(event)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("emit_ws_callback_failed: %s", e)
                pass

    # ══════════════════════════════════════════════════════
    # 核心流程: 自动补全缺失能力
    # ══════════════════════════════════════════════════════

    async def auto_fulfill(self, message: str) -> AutoFulfillReport:
        """检测并自动安装缺失的能力

        完整流程: detect → evaluate → rank → install → validate → report

        Args:
            message: 用户消息或任务描述

        Returns:
            AutoFulfillReport
        """
        t0 = time.monotonic()
        report = AutoFulfillReport(task_message=message)

        try:
            # 阶段 1: 获取已安装列表
            installed = self._get_installed_ids()

            # 阶段 2: 探测缺失能力
            needs = await self.detector.detect(
                message,
                installed_skill_ids=installed,
            )
            report.detected_needs = [n.__dict__ for n in needs]
            await self._emit(
                {
                    "type": "auto_plugin_detected",
                    "needs": report.detected_needs,
                    "count": len(needs),
                    "message": f"🔍 检测到 {len(needs)} 个缺失能力",
                }
            )

            if not needs:
                report.duration_ms = (time.monotonic() - t0) * 1000
                return report

            # 阶段 3: 评估候选
            candidates: list[dict] = []
            for need in needs:
                # 从市场获取详情
                candidate = await self._get_candidate_detail(need)
                if candidate:
                    candidates.append(candidate)

            if not candidates:
                report.errors.append("所有候选无法获取详情")
                report.duration_ms = (time.monotonic() - t0) * 1000
                return report

            # 阶段 4: 评估排名
            ranked = await self.evaluator.rank_candidates(candidates, top_n=5)
            report.evaluated_candidates = [r.__dict__ for r in ranked]

            best = ranked[0] if ranked else None
            if not best or not best.passed:
                report.errors.append("最佳候选未通过评估门槛")
                report.duration_ms = (time.monotonic() - t0) * 1000
                return report

            await self._emit(
                {
                    "type": "auto_plugin_evaluated",
                    "best": best.__dict__,
                    "message": f"📊 最佳候选: {best.name} (评分 {best.overall_score})",
                }
            )

            # 阶段 5: 安装（跳过已安装的）
            need_map = {n.capability: n for n in needs}
            candidate_map = {}
            for r in ranked:
                data = next((c for c in candidates if c.get("id", "") == r.candidate_id), {})
                candidate_map[r.candidate_id] = data

            for r in ranked[:3]:
                if r.candidate_id in installed:
                    report.skipped_count += 1
                    continue

                need = need_map.get(r.candidate_id)
                source = need.need_type if need else "skill"

                # 安装
                install_result = await self.installer.install(
                    r.candidate_id,
                    candidate_map.get(r.candidate_id, {}),
                    source,
                )
                report.install_results.append(install_result.__dict__)

                if install_result.success:
                    report.installed_count += 1

                    # 安装后验证
                    validation = await self.validator.validate(r.candidate_id)
                    report.validation_reports.append(validation.__dict__)

                    if not validation.passed:
                        report.errors.append(
                            f"{r.candidate_id}: 安装成功但验证未通过 " f"(评分 {validation.score})",
                        )

                    await self._emit(
                        {
                            "type": "auto_plugin_installed",
                            "id": r.candidate_id,
                            "name": install_result.name,
                            "version": install_result.version,
                            "validation_score": validation.score,
                            "message": f"✅ 已安装 {install_result.name} v{install_result.version}",
                        }
                    )
                else:
                    report.failed_count += 1
                    report.errors.append(
                        f"{r.candidate_id}: 安装失败 - {install_result.error[:100]}",
                    )

        except Exception as e:
            report.errors.append(f"自动补全异常: {str(e)[:200]}")
            logger.error("auto_fulfill_exception: %s", e)

        report.duration_ms = (time.monotonic() - t0) * 1000
        return report

    # ══════════════════════════════════════════════════════
    # 候选详情获取
    # ══════════════════════════════════════════════════════

    async def _get_candidate_detail(self, need: CapabilityNeed) -> dict | None:
        """从 Skills Market 获取候选详情"""
        try:
            from pycoder.server.skills_market_v2 import EnhancedSkillsMarketManager

            market = EnhancedSkillsMarketManager()
            result = market.search(query=need.capability, limit=5)
            items = result.get("items", []) if isinstance(result, dict) else result
            if isinstance(items, list):
                for item in items[:5]:
                    if isinstance(item, dict) and item.get("id") == need.capability:
                        return item
                # 返回第一个结果
                if items and isinstance(items[0], dict):
                    return items[0]
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.debug("candidate_detail_failed: %s", e)
        return None

    # ══════════════════════════════════════════════════════
    # 已安装能力列表
    # ══════════════════════════════════════════════════════

    def _get_installed_ids(self) -> list[str]:
        """获取所有已安装的 Skill ID"""
        installed: set[str] = set()

        # 从 installed_skills.json
        if _INSTALLED_REGISTRY.exists():
            try:
                data = json.loads(_INSTALLED_REGISTRY.read_text(encoding="utf-8"))
                installed.update(data.keys())
            except (json.JSONDecodeError, OSError):
                pass

        # 从文件系统
        skills_dir = Path.home() / ".pycoder" / "skills"
        if skills_dir.exists():
            for f in skills_dir.glob("*.md"):
                if not f.name.startswith("."):
                    installed.add(f.stem)

        return list(installed)

    # ══════════════════════════════════════════════════════
    # 统计信息
    # ══════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            "auto_enabled": self._auto_enabled,
            "require_confirmation": self._require_confirmation,
            "detector": self.detector.get_stats(),
            "evaluator": self.evaluator.get_stats(),
            "installed": self.installer.get_installed(),
            "install_log_count": len(self.installer.get_install_log()),
        }


# ── 全局单例 ──
_manager_instance: AutoPluginManager | None = None


def get_plugin_manager() -> AutoPluginManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AutoPluginManager()
    return _manager_instance


def reset_plugin_manager() -> None:
    global _manager_instance
    _manager_instance = None

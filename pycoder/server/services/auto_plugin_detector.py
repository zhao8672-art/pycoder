"""
AutoPluginDetector — 实时检测任务所需的缺失插件/Skills

职责:
    1. 分析用户消息和任务上下文，提取所需的能力描述
    2. 对比已注册的插件和 Skills，识别缺失项
    3. 生成"能力需求清单"供后续评估和安装

检测策略:
    - 关键词匹配: 从消息中提取技术栈关键词
    - 意图关联: 根据任务类别推荐关联 Skills
    - 历史分析: 检查 KnowledgeBase 中同类型任务的历史需求

用法:
    from .auto_plugin_detector import AutoPluginDetector
    detector = AutoPluginDetector()
    needs = detector.detect(message, installed_ids)
    # needs = [{"capability": "code-review", "type": "skill",
    #           "reason": "任务涉及代码审查"}]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── 任务类型 → 推荐 Skills 映射 ──
_TASK_SKILL_MAP: dict[str, list[str]] = {
    "code_review": ["code-review", "debugger", "lint-helper"],
    "test": ["test-generator", "coverage-analyzer", "mock-helper"],
    "debug": ["debugger", "error-analyzer", "log-analyzer"],
    "refactor": ["refactor-advisor", "code-metrics", "design-patterns"],
    "security": ["security-scanner", "vulnerability-checker"],
    "performance": ["performance-optimizer", "profiler-helper", "memory-analyzer"],
    "docker": ["docker-helper", "compose-validator", "container-debug"],
    "database": ["db-migrator", "query-optimizer", "schema-validator"],
    "api": ["api-designer", "swagger-generator", "rest-client"],
    "git": ["git-assistant", "conflict-resolver", "git-history"],
    "docs": ["doc-generator", "markdown-helper", "api-docs"],
    "deploy": ["deploy-helper", "ci-cd-validator", "config-manager"],
    "frontend": ["frontend-design", "css-helper", "react-helper"],
    "backend": ["debugger", "api-designer", "db-migrator"],
}

# ── 关键词 → 任务类型映射 ──
_KEYWORD_TASK_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"审查|review|检查代码|code.*review|QA|质量"), "code_review"),
    (re.compile(r"测试|test|单元测试|pytest|unittest"), "test"),
    (re.compile(r"调试|debug|修复bug|bug.*fix|异常|错误"), "debug"),
    (re.compile(r"重构|refactor|优化|改进|重写|rewrite"), "refactor"),
    (re.compile(r"安全|security|漏洞|注入|xss|csrf|加密"), "security"),
    (re.compile(r"性能|performance|优化|加速|slow|内存|memory|cache"), "performance"),
    (re.compile(r"docker|容器|container|compose|镜像"), "docker"),
    (re.compile(r"数据库|db|sql|mongo|postgres|mysql|schema|迁移"), "database"),
    (re.compile(r"api|接口|rest|graphql|endpoint|路由"), "api"),
    (re.compile(r"git|commit|push|pull|merge|branch|版本"), "git"),
    (re.compile(r"文档|docs|document|readme|markdown"), "docs"),
    (re.compile(r"部署|deploy|ci/cd|发布|上线|发布"), "deploy"),
    (re.compile(r"前端|ui|vue|react|angular|css|html|页面"), "frontend"),
    (re.compile(r"后端|server|service|微服务|模块"), "backend"),
]

# ── 技术栈关键词 → 推荐 Skills ──
_TECH_STACK_SKILLS: dict[str, list[str]] = {
    "fastapi": ["api-designer", "swagger-generator"],
    "django": ["backend", "db-migrator"],
    "flask": ["backend", "api-designer"],
    "react": ["frontend-design", "react-helper"],
    "vue": ["frontend-design", "css-helper"],
    "pytorch": ["performance-optimizer", "profiler-helper"],
    "tensorflow": ["performance-optimizer"],
    "sqlalchemy": ["db-migrator", "schema-validator"],
    "pandas": ["performance-optimizer"],
    "pytest": ["test-generator", "coverage-analyzer"],
    "docker": ["docker-helper", "deploy-helper"],
    "kubernetes": ["deploy-helper", "config-manager"],
}


@dataclass
class CapabilityNeed:
    """能力需求描述"""
    capability: str          # 能力名称 (如 "code-review")
    name: str                # 人类可读名称 (如 "Code Review Skill")
    need_type: str           # "plugin" | "skill" | "extension"
    reason: str              # 为什么需要
    confidence: float        # 0-1 置信度
    tech_stack: str = ""     # 关联的技术栈


class AutoPluginDetector:
    """自动插件/Skills 需求探测器

    分析用户消息和任务上下文，检测缺失的插件和 Skills。
    不依赖 LLM，全规则驱动 — 零 Token 消耗。
    """

    def __init__(self):
        self._skill_market = None
        self._ext_manager = None

    # ══════════════════════════════════════════════════════
    # 主检测入口
    # ══════════════════════════════════════════════════════

    async def detect(
        self,
        message: str,
        installed_plugin_ids: list[str] = None,
        installed_skill_ids: list[str] = None,
        installed_ext_ids: list[str] = None,
    ) -> list[CapabilityNeed]:
        """检测消息中缺失的能力

        Args:
            message: 用户消息或任务描述
            installed_plugin_ids: 已安装的插件 ID 列表
            installed_skill_ids: 已安装的 Skill ID 列表
            installed_ext_ids: 已安装的扩展 ID 列表

        Returns:
            CapabilityNeed 列表（按置信度降序）
        """
        installed_plugin_ids = installed_plugin_ids or []
        installed_skill_ids = installed_skill_ids or []
        installed_ext_ids = installed_ext_ids or []
        installed_set = set(installed_plugin_ids + installed_skill_ids + installed_ext_ids)

        needs: list[CapabilityNeed] = []

        # 1. 关键词 → 任务类型 → 推荐 Skills
        task_types = self._detect_task_types(message)
        for task_type in task_types:
            recommended = _TASK_SKILL_MAP.get(task_type, [])
            for skill_id in recommended:
                if skill_id not in installed_set:
                    needs.append(CapabilityNeed(
                        capability=skill_id,
                        name=self._to_readable_name(skill_id),
                        need_type="skill",
                        reason=f"任务类型「{task_type}」推荐关联 Skill",
                        confidence=0.7,
                    ))

        # 2. 技术栈检测 → 推荐 Skills
        tech_stacks = self._detect_tech_stack(message)
        for ts in tech_stacks:
            recommended = _TECH_STACK_SKILLS.get(ts, [])
            for skill_id in recommended:
                if skill_id not in installed_set and not any(
                    n.capability == skill_id for n in needs
                ):
                    needs.append(CapabilityNeed(
                        capability=skill_id,
                        name=self._to_readable_name(skill_id),
                        need_type="skill",
                        reason=f"技术栈「{ts}」推荐关联 Skill",
                        confidence=0.75,
                        tech_stack=ts,
                    ))

        # 3. 从 Skills Market 搜索匹配
        try:
            market_needs = await self._search_market(message, installed_set)
            for nn in market_needs:
                if not any(n.capability == nn.capability for n in needs):
                    needs.append(nn)
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("detect_market_search_failed: %s", e)
            pass

        # 4. 按置信度排序
        needs.sort(key=lambda n: n.confidence, reverse=True)
        return needs

    # ══════════════════════════════════════════════════════
    # 任务类型检测
    # ══════════════════════════════════════════════════════

    def _detect_task_types(self, message: str) -> list[str]:
        """从消息中检测任务类型"""
        detected: list[str] = []
        for pattern, task_type in _KEYWORD_TASK_MAP:
            if pattern.search(message):
                detected.append(task_type)
        return detected[:3]  # 最多返回 3 种

    def _detect_tech_stack(self, message: str) -> list[str]:
        """从消息中检测技术栈"""
        detected: list[str] = []
        msg_lower = message.lower()
        for ts in _TECH_STACK_SKILLS:
            if ts in msg_lower or ts.upper() in message:
                detected.append(ts)
        return detected[:3]

    # ══════════════════════════════════════════════════════
    # Skills Market 搜索
    # ══════════════════════════════════════════════════════

    async def _search_market(
        self, message: str, installed_set: set[str],
    ) -> list[CapabilityNeed]:
        """通过 Skills Market 搜索相关技能"""
        try:
            from pycoder.server.skills_market_v2 import EnhancedSkillsMarketManager
            market = EnhancedSkillsMarketManager()

            # 提取关键词
            words = re.findall(r"[\u4e00-\u9fff\w]{2,}", message)
            keywords = [w for w in words if len(w) > 2][:5]

            needs: list[CapabilityNeed] = []
            for kw in keywords:
                result = market.search(query=kw, limit=3)
                items = result.get("items", []) if isinstance(result, dict) else result
                if isinstance(items, list):
                    for item in items[:3]:
                        sid = None
                        sname = ""
                        if isinstance(item, dict):
                            sid = item.get("id", "")
                            sname = item.get("name", "") or item.get("id", "")
                        if sid and sid not in installed_set and not any(
                            n.capability == sid for n in needs
                        ):
                            needs.append(CapabilityNeed(
                                capability=sid,
                                name=sname,
                                need_type="skill",
                                reason=f"关键词「{kw}」搜索推荐",
                                confidence=0.6,
                            ))
            return needs
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            import logging
            logging.getLogger(__name__).debug(
                "market_search_failed: %s", e,
            )
            return []

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _to_readable_name(skill_id: str) -> str:
        """code-review → Code Review"""
        return skill_id.replace("-", " ").replace("_", " ").title()

    def get_stats(self) -> dict:
        return {
            "task_types": len(_TASK_SKILL_MAP),
            "keyword_patterns": len(_KEYWORD_TASK_MAP),
            "tech_stacks": len(_TECH_STACK_SKILLS),
        }

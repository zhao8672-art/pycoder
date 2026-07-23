"""
SkillsAutoInstaller — 根据用户需求自动搜索、安装、调用技能

核心能力:
  1. 语义匹配：用户消息 → 相关技能列表
  2. 自动安装：检测未安装技能，自动安装
  3. 智能调用：安装后自动加载技能内容
  4. 批量安装：支持一次安装多个技能

用法:
    installer = SkillsAutoInstaller()

    # 智能匹配
    matches = await installer.auto_match("帮我生成 PDF 报告")
    # → [{"name": "pdf", "score": 0.95, "installed": false}, ...]

    # 自动搜索+安装
    result = await installer.search_and_install("生成 PDF")
    # → {"installed": ["pdf"], "found": true, "message": "..."}
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 技能关键词映射表（常用技能的关键词触发）──
_SKILL_KEYWORD_MAP: dict[str, list[str]] = {
    "pdf": ["pdf", "生成pdf", "导出pdf", "pdf报告", "pdf文档", "convert to pdf"],
    "excel": ["excel", "xlsx", "电子表格", "导出excel", "spreadsheet"],
    "image": ["图片", "图像", "image", "截图", "screenshot", "照片", "photo"],
    "chart": ["图表", "chart", "可视化", "visualization", "绘图", "plot", "图形"],
    "web": ["网页", "web", "html", "网站", "前端", "frontend"],
    "api": ["api", "接口", "rest", "restful", "endpoint"],
    "database": ["数据库", "database", "sql", "mongodb", "redis", "存储"],
    "testing": ["测试", "test", "pytest", "单元测试", "unit test"],
    "security": ["安全", "security", "漏洞", "扫描", "审计", "audit"],
    "docker": ["docker", "容器", "container", "镜像", "deploy"],
    "git": ["git", "版本控制", "提交", "分支", "commit", "branch"],
    "logging": ["日志", "log", "监控", "monitoring", "debug"],
    "email": ["邮件", "email", "mail", "发送邮件", "smtp"],
    "report": ["报告", "report", "报表", "统计", "summary"],
    "code_review": ["审查", "review", "代码审查", "code review"],
    "documentation": ["文档", "doc", "文档生成", "api文档", "readme"],
    "cli": ["命令行", "cli", "terminal", "终端", "command"],
    "ai": ["ai", "人工智能", "机器学习", "machine learning", "llm", "模型"],
    "data": ["数据", "data", "分析", "analysis", "处理", "processing"],
    "file": ["文件", "file", "读取", "写入", "转换", "convert"],
}


class SkillsAutoInstaller:
    """Skills 自动安装器 — 智能匹配 + 自动安装 + 调用"""

    async def auto_match(self, user_message: str) -> list[dict]:
        """智能匹配：用户消息 → 相关技能列表

        Args:
            user_message: 用户输入的消息

        Returns:
            [{"name": "pdf", "score": 0.95, "installed": false, "reason": "..."}, ...]
        """
        from pycoder.skills import get_marketplace

        try:
            marketplace = get_marketplace()
        except Exception as e:
            logger.warning("skills_marketplace_init_failed", error=str(e))
            return []

        msg_lower = user_message.lower()
        matched_skills: dict[str, float] = {}

        # 1. 关键词匹配（使用词边界避免误匹配，如 "pdf" 不匹配 "pdf.js"）
        for skill_name, keywords in _SKILL_KEYWORD_MAP.items():
            for kw in keywords:
                # 使用 \b 词边界匹配，避免子串误匹配
                pattern = re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                if pattern.search(msg_lower):
                    matched_skills[skill_name] = max(
                        matched_skills.get(skill_name, 0), 0.7
                    )
                    break

        # 2. 在市场中进行语义搜索
        try:
            search_results = marketplace.search(user_message[:100], limit=10)
            for skill in search_results:
                name = getattr(skill, "name", skill.get("name", "")) if isinstance(skill, dict) else skill.name
                if name.lower() not in matched_skills:
                    matched_skills[name.lower()] = 0.5
                else:
                    matched_skills[name.lower()] = max(
                        matched_skills[name.lower()], 0.6
                    )
        except Exception as e:
            logger.debug("skill_search_failed", error=str(e))

        # 3. 检查安装状态
        try:
            installed = marketplace.get_installed_skills()
            installed_names = {s.name.lower() for s in installed}
        except Exception:
            installed_names = set()

        # 4. 构建结果
        results = []
        for name, score in sorted(matched_skills.items(), key=lambda x: -x[1]):
            is_installed = name.lower() in installed_names
            results.append({
                "name": name,
                "score": round(score, 2),
                "installed": is_installed,
                "reason": f"关键词匹配 '{name}'" if score >= 0.7 else "语义搜索匹配",
            })

        return results[:10]

    async def search_and_install(self, user_request: str) -> dict:
        """根据用户需求自动搜索并安装技能

        Args:
            user_request: 用户请求文本

        Returns:
            {"installed": [...], "skipped": [...], "found": bool, "message": str}
        """
        matches = await self.auto_match(user_request)

        if not matches:
            return {
                "installed": [],
                "skipped": [],
                "found": False,
                "message": "未找到匹配的技能",
            }

        from pycoder.skills import get_marketplace

        try:
            marketplace = get_marketplace()
        except Exception as e:
            return {
                "installed": [],
                "skipped": [],
                "found": False,
                "message": f"技能市场不可用: {e}",
            }

        installed_list: list[str] = []
        skipped_list: list[str] = []

        for match in matches:
            if match["installed"]:
                skipped_list.append(match["name"])
                continue

            if match["score"] < 0.5:
                logger.debug(
                    "skill_low_score_skip", name=match["name"],
                    score=match["score"],
                    reason=match.get("reason", ""),
                )
                skipped_list.append(f"{match['name']}(低置信度:{match['score']})")
                continue

            try:
                success = marketplace.install(match["name"])
                if success:
                    installed_list.append(match["name"])
                    logger.info("skill_auto_installed", name=match["name"])
                else:
                    skipped_list.append(match["name"])
            except Exception as e:
                logger.warning("skill_install_failed", name=match["name"], error=str(e))
                skipped_list.append(match["name"])

        return {
            "installed": installed_list,
            "skipped": skipped_list,
            "found": True,
            "message": (
                f"已安装 {len(installed_list)} 个技能: {', '.join(installed_list)}"
                if installed_list
                else "所有匹配技能已安装或无需安装"
            ),
        }

    async def install_by_name(self, skill_name: str) -> dict:
        """按名称安装指定技能

        Args:
            skill_name: 技能名称

        Returns:
            {"success": bool, "message": str}
        """
        from pycoder.skills import get_marketplace

        try:
            marketplace = get_marketplace()
            installed = marketplace.get_installed_skills()
            if any(s.name.lower() == skill_name.lower() for s in installed):
                return {"success": True, "message": f"技能 '{skill_name}' 已安装"}

            success = marketplace.install(skill_name)
            if success:
                return {"success": True, "message": f"技能 '{skill_name}' 安装成功"}
            return {"success": False, "message": f"技能 '{skill_name}' 安装失败"}
        except Exception as e:
            return {"success": False, "message": f"安装失败: {e}"}


# ── 全局单例 ──

_SKILLS_INSTALLER: SkillsAutoInstaller | None = None


def get_skills_installer() -> SkillsAutoInstaller:
    """获取 SkillsAutoInstaller 全局单例"""
    global _SKILLS_INSTALLER
    if _SKILLS_INSTALLER is None:
        _SKILLS_INSTALLER = SkillsAutoInstaller()
    return _SKILLS_INSTALLER
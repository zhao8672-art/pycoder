"""
声明式工具权限矩阵 — 替代 _infer_permission() 的启发式推断

每个工具显式声明所需的最低 TrustLevel。
AI 默认获得 PROJECT_WRITE 级别，大部分工具自动放行。
"""

from __future__ import annotations

from pycoder.bus.protocol import TrustLevel

RL = TrustLevel.READ_ONLY
WW = TrustLevel.WORKSPACE_WRITE
PW = TrustLevel.PROJECT_WRITE
SA = TrustLevel.SYSTEM_ACCESS

TOOL_PERMISSIONS: dict[str, TrustLevel] = {
    # ── 文件操作 ──
    "tools.file.read": RL,
    "tools.file.list": RL,
    "tools.file.write": WW,
    "tools.file.create_directory": WW,
    "tools.file.delete": PW,

    # ── 搜索 ──
    "tools.search.text": RL,
    "tools.search.quick_open": RL,

    # ── 代码执行 ──
    "tools.exec.python": WW,
    "tools.exec.code": WW,
    "tools.exec.multilang": PW,
    "tools.exec.debug_python": PW,
    "tools.exec.profile_python": PW,

    # ── 代码质量 ──
    "tools.quality.code_review": RL,
    "tools.quality.format_code": PW,
    "tools.quality.security_scan": PW,
    "tools.quality.dependency_analysis": PW,

    # ── Git ──
    "tools.git.status": RL,
    "tools.git.log": RL,
    "tools.git.diff_branch": RL,
    "tools.git.resolve_conflict": PW,

    # ── Shell ──
    "tools.shell.run_terminal": PW,

    # ── 环境 ──
    "tools.env.python": RL,
    "tools.env.docker_status": RL,
    "tools.env.docker_execute": SA,
    "tools.env.languages": RL,

    # ── 测试 ──
    "tools.testing.generate_tests": PW,
    "tools.testing.test_integration": PW,
    "tools.testing.test_e2e": PW,
    "tools.testing.test_performance": PW,
    "tools.testing.generate_pipeline": PW,

    # ── Skills 市场 ──
    "tools.marketplace.skills_search": RL,
    "tools.marketplace.skills_recommendations": RL,
    "tools.marketplace.skills_trending": RL,
    "tools.marketplace.skills_stats": RL,
    "tools.marketplace.skills_detail": RL,
    "tools.marketplace.skills_categories": RL,
    "tools.marketplace.skills_rate": RL,
    "tools.marketplace.skills_sync": PW,
    "tools.marketplace.skills_update": PW,
    "tools.marketplace.skills_market": RL,
    "tools.marketplace.snippets": RL,

    # ── 扩展管理 ──
    "tools.marketplace.extensions_search": RL,
    "tools.marketplace.extensions_installed": RL,
    "tools.marketplace.extensions_install": PW,
    "tools.marketplace.extensions_uninstall": PW,
    "tools.marketplace.extensions_refresh": PW,

    # ── 系统升级 ──
    "tools.marketplace.system_upgrade": SA,

    # ── Agent ──
    "tools.agent.list_configs": RL,
}


def get_permission(capability_id: str) -> TrustLevel:
    """获取指定工具的权限级别

    Args:
        capability_id: 能力 ID（如 tools.file.read）

    Returns:
        TrustLevel 枚举值
    """
    if capability_id in TOOL_PERMISSIONS:
        return TOOL_PERMISSIONS[capability_id]
    # 回退：根据 ID 前缀推断
    if any(kw in capability_id
           for kw in (".read", ".list", ".status", ".search", ".log")):
        return RL
    if any(kw in capability_id
           for kw in (".write", ".create", ".format")):
        return WW
    return PW  # 默认项目级

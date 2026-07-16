"""
声明式工具权限矩阵测试

覆盖:
  - TOOL_PERMISSIONS: 预定义权限表的完整性
  - get_permission: 已知工具返回正确 TrustLevel
  - get_permission: 未知工具按前缀推断
  - get_permission: 回退默认值
  - TrustLevel: 枚举值验证
"""
from __future__ import annotations

import pytest

from pycoder.bus.protocol import TrustLevel
from pycoder.capabilities.permissions import (
    TOOL_PERMISSIONS,
    get_permission,
    RL,
    WW,
    PW,
    SA,
)


# ══════════════════════════════════════════════════════════
# TrustLevel 枚举验证
# ══════════════════════════════════════════════════════════


class TestTrustLevel:
    """TrustLevel 枚举"""

    def test_read_only_value(self):
        """READ_ONLY 值为 0"""
        assert TrustLevel.READ_ONLY == 0

    def test_workspace_write_value(self):
        """WORKSPACE_WRITE 值为 1"""
        assert TrustLevel.WORKSPACE_WRITE == 1

    def test_project_write_value(self):
        """PROJECT_WRITE 值为 2"""
        assert TrustLevel.PROJECT_WRITE == 2

    def test_system_access_value(self):
        """SYSTEM_ACCESS 值为 3"""
        assert TrustLevel.SYSTEM_ACCESS == 3

    def test_full_autonomy_value(self):
        """FULL_AUTONOMY 值为 4"""
        assert TrustLevel.FULL_AUTONOMY == 4

    def test_aliases_match(self):
        """别名与枚举值匹配"""
        assert RL == TrustLevel.READ_ONLY
        assert WW == TrustLevel.WORKSPACE_WRITE
        assert PW == TrustLevel.PROJECT_WRITE
        assert SA == TrustLevel.SYSTEM_ACCESS


# ══════════════════════════════════════════════════════════
# TOOL_PERMISSIONS 预定义权限表测试
# ══════════════════════════════════════════════════════════


class TestToolPermissionsTable:
    """预定义权限表"""

    def test_file_read_is_read_only(self):
        """文件读取为只读"""
        assert TOOL_PERMISSIONS["tools.file.read"] == TrustLevel.READ_ONLY

    def test_file_list_is_read_only(self):
        """文件列表为只读"""
        assert TOOL_PERMISSIONS["tools.file.list"] == TrustLevel.READ_ONLY

    def test_file_write_is_workspace_write(self):
        """文件写入为工作区写入"""
        assert TOOL_PERMISSIONS["tools.file.write"] == TrustLevel.WORKSPACE_WRITE

    def test_file_delete_is_project_write(self):
        """文件删除为项目写入"""
        assert TOOL_PERMISSIONS["tools.file.delete"] == TrustLevel.PROJECT_WRITE

    def test_search_tools_are_read_only(self):
        """搜索工具为只读"""
        assert TOOL_PERMISSIONS["tools.search.text"] == TrustLevel.READ_ONLY
        assert TOOL_PERMISSIONS["tools.search.quick_open"] == TrustLevel.READ_ONLY

    def test_exec_python_is_workspace_write(self):
        """Python 执行为工作区写入"""
        assert TOOL_PERMISSIONS["tools.exec.python"] == TrustLevel.WORKSPACE_WRITE

    def test_exec_multilang_is_project_write(self):
        """多语言执行为项目写入"""
        assert TOOL_PERMISSIONS["tools.exec.multilang"] == TrustLevel.PROJECT_WRITE

    def test_quality_code_review_is_read_only(self):
        """代码审查为只读"""
        assert TOOL_PERMISSIONS["tools.quality.code_review"] == TrustLevel.READ_ONLY

    def test_git_status_is_read_only(self):
        """Git 状态为只读"""
        assert TOOL_PERMISSIONS["tools.git.status"] == TrustLevel.READ_ONLY

    def test_shell_run_terminal_is_project_write(self):
        """Shell 终端为项目写入"""
        assert TOOL_PERMISSIONS["tools.shell.run_terminal"] == TrustLevel.PROJECT_WRITE

    def test_env_docker_status_is_read_only(self):
        """Docker 状态查询为只读"""
        assert TOOL_PERMISSIONS["tools.env.docker_status"] == TrustLevel.READ_ONLY

    def test_env_docker_execute_is_system_access(self):
        """Docker 执行为系统访问"""
        assert TOOL_PERMISSIONS["tools.env.docker_execute"] == TrustLevel.SYSTEM_ACCESS

    def test_marketplace_skills_search_is_read_only(self):
        """Skills 搜索为只读"""
        assert TOOL_PERMISSIONS["tools.marketplace.skills_search"] == TrustLevel.READ_ONLY

    def test_marketplace_skills_sync_is_project_write(self):
        """Skills 同步为项目写入"""
        assert TOOL_PERMISSIONS["tools.marketplace.skills_sync"] == TrustLevel.PROJECT_WRITE

    def test_marketplace_system_upgrade_is_system_access(self):
        """系统升级为系统访问"""
        assert TOOL_PERMISSIONS["tools.marketplace.system_upgrade"] == TrustLevel.SYSTEM_ACCESS

    def test_agent_list_configs_is_read_only(self):
        """Agent 配置列表为只读"""
        assert TOOL_PERMISSIONS["tools.agent.list_configs"] == TrustLevel.READ_ONLY

    def test_all_tools_have_valid_trust_level(self):
        """所有预设工具的权限级别都是有效的 TrustLevel"""
        for cap_id, level in TOOL_PERMISSIONS.items():
            assert isinstance(level, TrustLevel), f"{cap_id} 的权限级别不是 TrustLevel: {level}"
            assert level in TrustLevel, f"{cap_id} 的权限级别 {level} 不在 TrustLevel 枚举中"


# ══════════════════════════════════════════════════════════
# get_permission 测试
# ══════════════════════════════════════════════════════════


class TestGetPermission:
    """获取权限级别"""

    def test_get_known_tool_permission(self):
        """获取已知工具的权限"""
        assert get_permission("tools.file.read") == TrustLevel.READ_ONLY
        assert get_permission("tools.file.write") == TrustLevel.WORKSPACE_WRITE
        assert get_permission("tools.file.delete") == TrustLevel.PROJECT_WRITE
        assert get_permission("tools.env.docker_execute") == TrustLevel.SYSTEM_ACCESS

    def test_get_unknown_tool_read_prefix(self):
        """未知工具，包含 .read 前缀 → READ_ONLY"""
        assert get_permission("tools.custom.read") == TrustLevel.READ_ONLY
        assert get_permission("tools.unknown.read_config") == TrustLevel.READ_ONLY

    def test_get_unknown_tool_list_prefix(self):
        """未知工具，包含 .list 前缀 → READ_ONLY"""
        assert get_permission("tools.custom.list") == TrustLevel.READ_ONLY
        assert get_permission("tools.unknown.list_items") == TrustLevel.READ_ONLY

    def test_get_unknown_tool_status_prefix(self):
        """未知工具，包含 .status 前缀 → READ_ONLY"""
        assert get_permission("tools.custom.status") == TrustLevel.READ_ONLY
        assert get_permission("tools.unknown.status_check") == TrustLevel.READ_ONLY

    def test_get_unknown_tool_search_prefix(self):
        """未知工具，包含 .search 前缀 → READ_ONLY"""
        assert get_permission("tools.custom.search") == TrustLevel.READ_ONLY
        assert get_permission("tools.unknown.search_deep") == TrustLevel.READ_ONLY

    def test_get_unknown_tool_log_prefix(self):
        """未知工具，包含 .log 前缀 → READ_ONLY"""
        assert get_permission("tools.custom.log") == TrustLevel.READ_ONLY
        assert get_permission("tools.unknown.log_view") == TrustLevel.READ_ONLY

    def test_get_unknown_tool_write_prefix(self):
        """未知工具，包含 .write 前缀 → WORKSPACE_WRITE"""
        assert get_permission("tools.custom.write") == TrustLevel.WORKSPACE_WRITE
        assert get_permission("tools.unknown.write_file") == TrustLevel.WORKSPACE_WRITE

    def test_get_unknown_tool_create_prefix(self):
        """未知工具，包含 .create 前缀 → WORKSPACE_WRITE"""
        assert get_permission("tools.custom.create") == TrustLevel.WORKSPACE_WRITE
        assert get_permission("tools.unknown.create_project") == TrustLevel.WORKSPACE_WRITE

    def test_get_unknown_tool_format_prefix(self):
        """未知工具，包含 .format 前缀 → WORKSPACE_WRITE"""
        assert get_permission("tools.custom.format") == TrustLevel.WORKSPACE_WRITE
        assert get_permission("tools.unknown.format_code") == TrustLevel.WORKSPACE_WRITE

    def test_get_unknown_tool_default_fallback(self):
        """未知工具，无匹配前缀 → 默认 PROJECT_WRITE"""
        assert get_permission("tools.custom.execute") == TrustLevel.PROJECT_WRITE
        assert get_permission("tools.unknown.delete_all") == TrustLevel.PROJECT_WRITE
        assert get_permission("completely.random.tool") == TrustLevel.PROJECT_WRITE

    def test_get_unknown_tool_empty_string(self):
        """空字符串 → 默认 PROJECT_WRITE"""
        assert get_permission("") == TrustLevel.PROJECT_WRITE

    def test_prefix_match_priority_known_over_prefix(self):
        """已知工具权限优先于前缀推断"""
        # "tools.file.write" 已知为 WORKSPACE_WRITE
        assert get_permission("tools.file.write") == TrustLevel.WORKSPACE_WRITE
        # 如果按前缀推断 .write 也是 WORKSPACE_WRITE，所以一致
        # 但 "tools.file.delete" 已知为 PROJECT_WRITE，不匹配任何前缀推断
        assert get_permission("tools.file.delete") == TrustLevel.PROJECT_WRITE

    def test_all_known_tools_return_trustlevel(self):
        """所有已知工具都返回 TrustLevel 类型"""
        for cap_id in TOOL_PERMISSIONS:
            result = get_permission(cap_id)
            assert isinstance(result, TrustLevel), f"{cap_id} 返回的不是 TrustLevel: {type(result)}"
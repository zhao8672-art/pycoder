"""env 模块测试 — 工具检测与安装"""
from __future__ import annotations

import pytest
from pycoder.env.tool_detector import ToolDetector, ToolRequirement, ToolStatus
from pycoder.env.auto_installer import AutoInstaller
from pycoder.env.version_checker import VersionChecker


class TestToolDetector:
    def test_detect_all_returns_list(self):
        detector = ToolDetector()
        statuses = detector.detect_all()
        assert isinstance(statuses, list)
        assert len(statuses) > 0
        assert all(isinstance(s, ToolStatus) for s in statuses)

    def test_git_is_installed(self):
        """Git 在开发环境中应该已安装"""
        detector = ToolDetector()
        statuses = detector.detect_all()
        git_status = next(
            (s for s in statuses if s.name == "git"), None
        )
        assert git_status is not None
        # Git 通常在开发环境中已安装
        assert git_status.installed

    def test_detect_single_tool(self):
        detector = ToolDetector([ToolRequirement(
            name="python",
            display_name="Python",
            required=True,
            check_cmd="python --version",
            min_version="3.0.0",
        )])
        statuses = detector.detect_all()
        assert len(statuses) == 1
        assert statuses[0].installed
        assert statuses[0].meets_minimum

    def test_missing_tool_reported(self):
        detector = ToolDetector([ToolRequirement(
            name="nonexistent_tool_xyz",
            display_name="不存在工具",
            required=True,
            check_cmd="nonexistent_tool_xyz --version",
        )])
        statuses = detector.detect_all()
        assert not statuses[0].installed
        assert "未找到" in statuses[0].error

    def test_get_report_structure(self):
        detector = ToolDetector()
        report = detector.get_report()
        assert "all_ok" in report
        assert "required_missing" in report
        assert "optional_missing" in report
        assert "version_issues" in report
        assert "all_statuses" in report

    def test_get_tool_by_name(self):
        detector = ToolDetector()
        tool = detector.get_tool_by_name("docker")
        assert tool is not None
        assert tool.name == "docker"
        assert tool.display_name == "Docker"

    def test_get_tool_by_name_not_found(self):
        detector = ToolDetector()
        tool = detector.get_tool_by_name("nonexistent")
        assert tool is None

    def test_version_parsing(self):
        assert ToolDetector._parse_version("git version 2.45.0") == "2.45.0"
        assert ToolDetector._parse_version("v1.2.3") == "1.2.3"
        assert ToolDetector._parse_version("no version here") is None


class TestAutoInstaller:
    def test_get_platform(self):
        platform = AutoInstaller.get_platform()
        assert platform in ("windows", "macos", "linux")

    def test_get_install_guide_known_tool(self):
        detector = ToolDetector()
        installer = AutoInstaller(detector)
        guide = installer.get_install_guide("docker")
        assert "Docker" in guide
        assert len(guide) > 0

    def test_get_install_guide_unknown_tool(self):
        detector = ToolDetector()
        installer = AutoInstaller(detector)
        guide = installer.get_install_guide("nonexistent")
        assert "未知工具" in guide

    def test_get_all_missing_guides(self):
        detector = ToolDetector()
        installer = AutoInstaller(detector)
        guide = installer.get_all_missing_guides()
        assert isinstance(guide, str)

    def test_get_version_fix_guides(self):
        detector = ToolDetector()
        installer = AutoInstaller(detector)
        guide = installer.get_version_fix_guides()
        assert isinstance(guide, str)


class TestVersionChecker:
    @pytest.mark.parametrize("current,minimum,expected", [
        ("1.2.3", "1.0.0", True),
        ("1.0.0", "1.0.0", True),
        ("0.9.0", "1.0.0", False),
        ("2.0.0", "1.0.0", True),
        ("1.0.0", "2.0.0", False),
    ])
    def test_meets_minimum(self, current, minimum, expected):
        assert VersionChecker.meets_minimum(current, minimum) == expected

    @pytest.mark.parametrize("v1,v2,expected", [
        ("1.0.0", "2.0.0", -1),
        ("2.0.0", "1.0.0", 1),
        ("1.0.0", "1.0.0", 0),
    ])
    def test_compare(self, v1, v2, expected):
        assert VersionChecker.compare(v1, v2) == expected

    @pytest.mark.parametrize("current,range_str,expected", [
        ("1.5.0", ">=1.0.0,<2.0.0", True),
        ("0.9.0", ">=1.0.0,<2.0.0", False),
        ("2.1.0", ">=1.0.0,<2.0.0", False),
        ("1.0.0", "==1.0.0", True),
        ("1.0.1", "!=1.0.0", True),
    ])
    def test_is_compatible(self, current, range_str, expected):
        assert VersionChecker.is_compatible(current, range_str) == expected

    def test_meets_minimum_invalid(self):
        assert not VersionChecker.meets_minimum("invalid", "1.0.0")
        assert not VersionChecker.meets_minimum("1.0.0", "invalid")
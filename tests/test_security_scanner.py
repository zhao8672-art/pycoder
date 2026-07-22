"""P1-1: 依赖安全扫描器单元测试"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from pycoder.python.security_scanner import (
    DependencySecurityScanner,
    ScanResult,
    scan_project,
)


class TestVulnerabilityMatching:
    def test_match_known_vuln(self):
        scanner = DependencySecurityScanner()
        vulns = scanner._match_vulnerabilities(
            [{"name": "django", "version_spec": ""}],
            {"django": "1.11.0"},
        )
        assert len(vulns) > 0
        assert all(v["package"] == "django" for v in vulns)

    def test_safe_version(self):
        scanner = DependencySecurityScanner()
        vulns = scanner._match_vulnerabilities(
            [{"name": "django", "version_spec": ""}],
            {"django": "4.2.0"},  # 最新版本
        )
        assert len(vulns) == 0

    def test_unknown_package(self):
        scanner = DependencySecurityScanner()
        vulns = scanner._match_vulnerabilities(
            [{"name": "totally-unknown-package-xyz", "version_spec": ""}],
            {"totally-unknown-package-xyz": "1.0.0"},
        )
        assert len(vulns) == 0


class TestParseRequirements:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_parse_simple_requirements(self):
        (self.tmp_path / "requirements.txt").write_text(
            "django==3.0.0\n"
            "flask>=1.0.0\n"
            "# comment\n"
            "requests\n",
            encoding="utf-8",
        )
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        packages = scanner._parse_requirements_txt()
        names = [p["name"] for p in packages]
        assert "django" in names
        assert "flask" in names
        assert "requests" in names

    def test_parse_with_extras(self):
        (self.tmp_path / "requirements.txt").write_text(
            "uvicorn[standard]>=0.20.0\n",
            encoding="utf-8",
        )
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        packages = scanner._parse_requirements_txt()
        assert any("uvicorn" in p["name"] for p in packages)

    def test_no_requirements_file(self):
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        packages = scanner._parse_requirements_txt()
        assert packages == []


class TestParsePyproject:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_parse_pyproject(self):
        (self.tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "myproject"\n'
            'version = "0.1.0"\n'
            'dependencies = [\n'
            '    "django>=3.0.0",\n'
            '    "fastapi==0.100.0",\n'
            ']\n',
            encoding="utf-8",
        )
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        packages = scanner._parse_pyproject_toml()
        names = [p["name"] for p in packages]
        assert "django" in names
        assert "fastapi" in names


class TestParseSetup:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_parse_setup_py(self):
        (self.tmp_path / "setup.py").write_text(
            'from setuptools import setup\n'
            'setup(\n'
            '    name="mypkg",\n'
            '    install_requires=[\n'
            '        "django>=2.0",\n'
            '        "flask",\n'
            '    ],\n'
            ')\n',
            encoding="utf-8",
        )
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        packages = scanner._parse_setup_py()
        names = [p["name"] for p in packages]
        assert "django" in names
        assert "flask" in names


class TestEndToEndScan:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_scan_with_requirements(self):
        (self.tmp_path / "requirements.txt").write_text(
            "django==2.0.0\n",  # 已知有漏洞
            encoding="utf-8",
        )
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        result = scanner.scan()
        assert isinstance(result, ScanResult)
        # 模拟已安装版本
        result_vulns = scanner._match_vulnerabilities(
            scanner._parse_dependencies(),
            {"django": "2.0.0"},
        )
        # 注意：完整 scan() 不传入 installed，所以默认用 version_spec

    def test_to_dict(self):
        (self.tmp_path / "requirements.txt").write_text("flask==0.12.0\n", encoding="utf-8")
        scanner = DependencySecurityScanner(project_root=self.tmp_path)
        result = scanner.scan()
        d = scanner.to_dict(result)
        assert "project_root" in d
        assert "total_packages" in d
        assert "vulnerabilities" in d
        assert "recommendations" in d

    def test_add_custom_vuln(self):
        scanner = DependencySecurityScanner()
        scanner.add_vulnerability({
            "package": "my-internal-pkg",
            "affected_patterns": [r"^0\."],
            "fixed_version": "1.0.0",
            "severity": "HIGH",
            "cve_id": "INTERNAL-001",
            "title": "Test vulnerability",
            "description": "Custom vuln",
            "cwe": "CWE-89",
            "cvss": 7.0,
        })
        vulns = scanner._match_vulnerabilities(
            [{"name": "my-internal-pkg", "version_spec": ""}],
            {"my-internal-pkg": "0.5.0"},
        )
        assert len(vulns) == 1
        assert vulns[0]["cve_id"] == "INTERNAL-001"


class TestRecommendations:
    def test_no_vulns_recommendation(self):
        scanner = DependencySecurityScanner()
        recs = scanner._build_recommendations([], [])
        assert len(recs) == 1
        assert "未发现" in recs[0]

    def test_vulns_recommendation(self):
        vulns = [
            {
                "package": "django",
                "fixed_version": "4.2.0",
                "severity": "CRITICAL",
            },
            {
                "package": "django",
                "fixed_version": "4.2.0",
                "severity": "HIGH",
            },
        ]
        recs = scanner_recommendations(vulns, [])
        assert any("django" in r and "4.2.0" in r for r in recs)


def scanner_recommendations(vulns, packages):
    scanner = DependencySecurityScanner()
    return scanner._build_recommendations(vulns, packages)

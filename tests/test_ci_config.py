"""P2-5: CI/CD 安全扫描配置测试

验证 GitHub Actions security-scan workflow 和 pre-commit 配置
存在且包含关键安全扫描步骤与回归防护钩子。
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECURITY_SCAN_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "security-scan.yml"
PRE_COMMIT_CONFIG = PROJECT_ROOT / ".pre-commit-config.yaml"


def _read_yaml_or_text(path: Path) -> str:
    """读取文件内容（优先 YAML 解析，失败则返回纯文本）"""
    content = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(content)
    except ImportError:
        return content


class TestSecurityScanWorkflow:
    """security-scan.yml 验证"""

    def test_workflow_file_exists(self):
        assert SECURITY_SCAN_WORKFLOW.exists(), "security-scan.yml 不存在"

    def test_workflow_has_bandit_step(self):
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "bandit" in content.lower(), "缺少 Bandit 安全扫描步骤"

    def test_workflow_has_semgrep_step(self):
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "semgrep" in content.lower(), "缺少 Semgrep 扫描步骤"

    def test_workflow_has_safety_step(self):
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "safety" in content.lower(), "缺少 Safety 依赖检查步骤"

    def test_workflow_has_coverage_gate(self):
        """覆盖率门禁 — 防止覆盖率回归（当前基线 41%，门禁 38%）"""
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "cov-fail-under" in content, "缺少覆盖率门禁"
        assert "cov=pycoder.server" in content, "覆盖率应针对 server 核心模块"

    def test_workflow_has_artifact_upload(self):
        """安全报告应作为 artifact 上传"""
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "upload-artifact" in content, "缺少 artifact 上传步骤"
        assert "security-reports" in content, "缺少 security-reports artifact"

    def test_workflow_triggers_on_push_and_pr(self):
        """应在 push 和 PR 时触发"""
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "push:" in content
        assert "pull_request:" in content
        assert "master" in content

    def test_workflow_uses_python_setup(self):
        """应使用 actions/setup-python"""
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "actions/setup-python" in content

    def test_workflow_uses_checkout_v4(self):
        """应使用 actions/checkout@v4"""
        content = SECURITY_SCAN_WORKFLOW.read_text(encoding="utf-8")
        assert "actions/checkout@v4" in content


class TestPreCommitConfig:
    """pre-commit 配置验证"""

    def test_config_file_exists(self):
        assert PRE_COMMIT_CONFIG.exists(), ".pre-commit-config.yaml 不存在"

    def test_has_bandit_hook(self):
        """P2-5: 应包含 bandit 安全扫描钩子"""
        content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
        assert "bandit" in content.lower(), "缺少 bandit 钩子"

    def test_has_no_bare_except_hook(self):
        """P2-5: 应包含禁止裸 except 的本地钩子"""
        content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
        assert "no-bare-except" in content, "缺少 no-bare-except 钩子"
        assert "except Exception: pass" in content, "钩子应检测 except Exception: pass"

    def test_has_flake8_hook(self):
        """应保留 flake8 钩子"""
        content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
        assert "flake8" in content

    def test_has_black_hook(self):
        """应保留 black 格式化钩子"""
        content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
        assert "black" in content

    def test_critical_files_listed_in_hook(self):
        """no-bare-except 钩子应检查关键文件"""
        content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
        for critical_file in ["agent_orchestrator.py", "self_evolution.py"]:
            assert critical_file in content, f"钩子未覆盖 {critical_file}"


class TestArchitectureRegressionGuard:
    """架构回归防护 — 确保关键文件无裸 except: pass"""

    @pytest.mark.parametrize("critical_file", [
        "pycoder/server/app.py",
        "pycoder/server/chat_handler.py",
        "pycoder/server/services/agent_orchestrator.py",
        "pycoder/server/self_evolution.py",
    ])
    def test_no_bare_except_pass(self, critical_file):
        """关键文件中不应有 except Exception: pass"""
        p = PROJECT_ROOT / critical_file
        if not p.exists():
            pytest.skip(f"{critical_file} 不存在")
        content = p.read_text(encoding="utf-8")
        forbidden = ["except Exception: pass", "except Exception as e: pass"]
        for pattern in forbidden:
            assert pattern not in content, (
                f"{critical_file} 中仍存在 '{pattern}'，"
                "应替换为具体异常类型 + 日志记录"
            )

"""gh_permissions — GitHub CLI 权限检查工具库。

可复用的 token scope 验证、自动刷新和 CI 风格报告生成工具。

快速使用:
    ```python
    from gh_permissions import check_permissions

    result = check_permissions(["repo", "workflow"], interactive=False)
    if not result.ok:
        print(f"权限不足: {result.missing_scopes}")
    ```

CI/CD 使用:
    ```bash
    python -m gh_permissions --check-only --format ci --scopes repo workflow
    ```

CLI 格式:
    --format json   JSON 输出 (CI/CD 解析)
    --format ci     CI 风格报告 (含耗时、scope 详情, 带 box drawing)
    --format human  人类可读摘要 (默认)
"""

from gh_permissions.checker import GitHubPermissionChecker, check_permissions
from gh_permissions.exceptions import (
    GitHubAuthError,
    GitHubCLINotFoundError,
    GitHubPermissionError,
    GitHubScopeMissingError,
)
from gh_permissions.models import PermissionResult
from gh_permissions.reporter import ReportFormatter

__all__ = [
    "GitHubPermissionChecker",
    "PermissionResult",
    "ReportFormatter",
    "check_permissions",
    "GitHubPermissionError",
    "GitHubCLINotFoundError",
    "GitHubAuthError",
    "GitHubScopeMissingError",
]

__version__ = "1.0.0"

"""gh_permissions 异常定义。"""


class GitHubPermissionError(Exception):
    """GitHub 权限检查基础异常。"""


class GitHubCLINotFoundError(GitHubPermissionError):
    """gh CLI 未安装。"""


class GitHubAuthError(GitHubPermissionError):
    """gh CLI 未认证或 token 无效。"""


class GitHubScopeMissingError(GitHubPermissionError):
    """token 缺失必需 scope。"""

    def __init__(self, missing_scopes: list[str], current_scopes: list[str]) -> None:
        self.missing_scopes = missing_scopes
        self.current_scopes = current_scopes
        super().__init__(
            f"缺失 scope: {missing_scopes} (当前: {current_scopes})"
        )

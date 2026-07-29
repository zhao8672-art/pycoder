"""网络请求工具 — GitHub API 等外部 HTTP 请求的 P 层抽象

将原本位于 pycoder.server.skills_data_sources 的网络工具函数
下沉到 P 层（core.services.net），消除 D→C 违规。

演进策略（ADR-002）：
- 新代码应从 pycoder.core.services.net 导入
- 旧路径 pycoder.server.skills_data_sources 保留并标记 @deprecated
- 6 个月过渡期后删除旧路径
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from pycoder.core.services.log import log


def _get_github_token() -> str:
    """获取 GitHub Token, 优先级: 环境变量 > ~/.pycoder/config.json"""
    token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
    if token:
        return token
    config_path = Path.home() / ".pycoder" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            token = cfg.get("github_token", "") or cfg.get("github", {}).get("token", "")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, KeyError, TypeError):
            pass
    return token


def make_github_request(
    url: str, params: dict[str, Any] | None = None, timeout: int = 30
) -> dict[str, Any] | list[Any] | None:
    """发起 GitHub API 请求，自动附加认证头和指数退避重试

    Args:
        url: GitHub API URL
        params: 查询参数
        timeout: 超时秒数

    Returns:
        JSON 响应（dict 或 list），失败返回 None
    """
    import urllib.error
    import urllib.request

    token = _get_github_token()
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    if params:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403 and "rate limit" in str(e).lower():
                wait = 2**attempt
                log.warning(f"GitHub API 速率限制，{wait}s 后重试")
                time.sleep(wait)
                continue
            log.error(f"GitHub API HTTP {e.code}: {e.reason}")
            return None
        except Exception as e:
            log.error(f"GitHub API 请求失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            return None
    return None

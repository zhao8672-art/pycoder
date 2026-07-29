"""server/domains/ — 按业务域组织的路由清单层

演进式策略（ADR-002）：
- 不移动现有 routers/services 文件（避免破坏导入链）
- 创建域清单文件，声明每个域包含的路由和服务
- 为未来物理迁移提供组织架构

13 个域目录：
    chat/       workspace/   git/        agent/
    team/       extensions/  skills/     evolution/
    files/      sessions/    config/     search/
    system/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def register_domain_routes(app: FastAPI) -> None:
    """按域注册所有路由（委托到现有 router_groups）

    这是域组织层的入口，未来可逐步将各域注册函数
    迁移到对应的 domains/<domain>/__init__.py 中。
    """
    from pycoder.server.router_groups import register_router_groups

    register_router_groups(app)


__all__ = ["register_domain_routes"]

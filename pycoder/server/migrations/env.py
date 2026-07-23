"""
Alembic 迁移环境配置 — 自动数据库迁移引擎

用法:
  alembic revision --autogenerate -m "描述"
  alembic upgrade head
  alembic downgrade -1
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── 加载 PyCoder 的 SQLAlchemy Base ──
try:
    from pycoder.server.unified_db import Base
    target_metadata = Base.metadata
except ImportError:
    # 如果 unified_db 不可用，回退到空元数据
    from sqlalchemy import MetaData
    target_metadata = MetaData()

logger = logging.getLogger("alembic.env")

# Alembic Config 对象
config = context.config

# 从环境变量覆盖数据库 URL
db_url = os.environ.get(
    "PYCODER_DATABASE_URL",
    f"sqlite:///{Path.home() / '.pycoder' / 'pycoder.db'}",
)
config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    """离线模式迁移 — 生成 SQL 脚本（不连接数据库）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式迁移 — 直接连接数据库执行"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
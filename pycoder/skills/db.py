"""技能市场数据库操作 — SQLite + FTS5 全文索引"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pycoder.skills.models import SkillDefinition

logger = logging.getLogger(__name__)

# ── 数据目录 ──────────────────────────────────────

DATA_DIR = Path("data/skills")
"""技能内容存储目录"""

DB_PATH = DATA_DIR / "skills.db"
"""技能元数据 SQLite 数据库路径"""


class SkillDatabase:
    """技能市场数据库管理器"""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库和表结构（V2 — 含增量迁移）"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # ── 迁移预处理：检测并重命名带表级 UNIQUE 约束的旧表 ──
            self._migrate_drop_table_unique_if_exists(conn, "skill_reviews")

            conn.executescript("""
                -- ══ V1 基础表 ══
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    description TEXT DEFAULT '',
                    author TEXT DEFAULT 'PyCoder',
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    dependencies TEXT DEFAULT '[]',
                    install_count INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    rating_sum INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    markdown_content TEXT DEFAULT '',
                    is_builtin INTEGER DEFAULT 0,
                    installed_at TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                    user TEXT DEFAULT 'anonymous',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
                CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
                CREATE INDEX IF NOT EXISTS idx_skills_rating ON skills(rating DESC);
                CREATE INDEX IF NOT EXISTS idx_skills_install_count ON skills(install_count DESC);
                CREATE INDEX IF NOT EXISTS idx_ratings_skill_id ON ratings(skill_id);

                -- ══ V2 新增表 ══

                -- 截图表
                CREATE TABLE IF NOT EXISTS skill_screenshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    caption TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_screenshots_skill ON skill_screenshots(skill_id);

                -- 版本历史表
                CREATE TABLE IF NOT EXISTS skill_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    released_at TEXT NOT NULL,
                    changelog TEXT DEFAULT '',
                    download_url TEXT DEFAULT '',
                    download_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE,
                    UNIQUE(skill_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_versions_skill ON skill_versions(skill_id, released_at DESC);

                -- 评论表（V2 — 含 review_text，部分唯一索引防刷分）
                CREATE TABLE IF NOT EXISTS skill_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_name TEXT DEFAULT 'anonymous',
                    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                    review_text TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    helpful_count INTEGER DEFAULT 0,
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_skill ON skill_reviews(skill_id, created_at DESC);
                -- 部分唯一索引：仅登录用户启用一人一评（anonymous 允许多次评分，V1 兼容）
                CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_user_unique
                    ON skill_reviews(skill_id, user_id) WHERE user_id != 'anonymous';

                -- 收藏表
                CREATE TABLE IF NOT EXISTS skill_favorites (
                    user_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, skill_id),
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
                );

                -- 异步安装任务表
                CREATE TABLE IF NOT EXISTS install_tasks (
                    task_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    current_step TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    started_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT DEFAULT '',
                    user_id TEXT DEFAULT 'anonymous'
                );
                CREATE INDEX IF NOT EXISTS idx_install_tasks_skill ON install_tasks(skill_id, status);
            """)

            # ── V2 增量字段迁移（ALTER TABLE，幂等）──
            self._migrate_add_columns_if_missing(conn, "skills", {
                "publisher": "TEXT DEFAULT ''",
                "verified": "INTEGER DEFAULT 0",
                "source_url": "TEXT DEFAULT ''",
                "homepage_url": "TEXT DEFAULT ''",
                "license": "TEXT DEFAULT ''",
                "icon_url": "TEXT DEFAULT ''",
                "local_version": "TEXT DEFAULT ''",
                "remote_version": "TEXT DEFAULT ''",
                "stars": "INTEGER DEFAULT 0",
            })

            # ── 迁移：移除 skill_reviews 表级 UNIQUE 约束（V2 改用部分唯一索引）──
            self._migrate_drop_table_unique_if_exists(conn, "skill_reviews")

            # ── FTS5 全文索引（中英文混合搜索）──
            try:
                conn.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                        skill_id UNINDEXED,
                        name,
                        description,
                        tags
                    );
                """)
                cnt = conn.execute("SELECT COUNT(*) FROM skills_fts").fetchone()[0]
                total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
                if cnt < total:
                    conn.execute("DELETE FROM skills_fts")
                    conn.execute(
                        "INSERT INTO skills_fts(skill_id, name, description, tags) "
                        "SELECT id, name, description, tags FROM skills"
                    )
                logger.info("FTS5 索引就绪: %d 条", cnt or total)
            except sqlite3.OperationalError as e:
                logger.warning("FTS5 不可用，降级到 LIKE 搜索: %s", e)

            conn.commit()
        logger.info("技能市场数据库已初始化（V2）: %s", self._db_path)

    @staticmethod
    def _migrate_add_columns_if_missing(
        conn: sqlite3.Connection, table: str, columns: dict[str, str]
    ) -> None:
        """幂等添加新列（SQLite 不支持 IF NOT EXISTS on ALTER TABLE ADD COLUMN）"""
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()  # nosec B608
        }
        for col, definition in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")  # nosec B608
                logger.info("迁移: %s.%s 已添加", table, col)

    @staticmethod
    def _migrate_drop_table_unique_if_exists(
        conn: sqlite3.Connection, table: str
    ) -> None:
        """检测并重建带表级 UNIQUE 约束的表"""
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row or not row[0]:
                return
            sql_lower = row[0].lower()
            if "unique(skill_id, user_id)" not in sql_lower.replace(" ", ""):
                return
            logger.info("迁移: %s 表检测到 UNIQUE 约束，开始重建", table)
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old_v1")  # nosec B608
            logger.info("迁移: %s 旧表已重命名为 %s_old_v1", table, table)
        except sqlite3.OperationalError as e:
            logger.debug("迁移检查跳过 %s: %s", table, e)

    def save_skill_to_db(
        self, skill_def: SkillDefinition, *, mark_as_installed: bool = True
    ) -> None:
        """将技能保存到 SQLite 数据库（V2 — 含新增字段）"""
        now = datetime.now(timezone.utc).isoformat()
        if not skill_def.created_at:
            skill_def.created_at = now
        if not skill_def.updated_at:
            skill_def.updated_at = now

        installed_at = now if mark_as_installed else ""
        if mark_as_installed and not skill_def.local_version:
            skill_def.local_version = skill_def.version

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skills
                    (id, name, version, description, author, category, tags,
                     dependencies, install_count, rating, rating_count, rating_sum,
                     created_at, updated_at, markdown_content, is_builtin, installed_at,
                     publisher, verified, source_url, homepage_url, license, icon_url,
                     local_version, remote_version, stars)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_def.id,
                    skill_def.name,
                    skill_def.version,
                    skill_def.description,
                    skill_def.author,
                    skill_def.category,
                    json.dumps(skill_def.tags, ensure_ascii=False),
                    json.dumps(skill_def.dependencies, ensure_ascii=False),
                    skill_def.install_count,
                    skill_def.rating,
                    0,
                    0,
                    skill_def.created_at,
                    skill_def.updated_at,
                    skill_def.markdown_content,
                    1 if skill_def.is_builtin else 0,
                    installed_at,
                    skill_def.publisher or skill_def.author,
                    1 if skill_def.verified else 0,
                    skill_def.source_url,
                    skill_def.homepage_url,
                    skill_def.license,
                    skill_def.icon_url,
                    skill_def.local_version,
                    skill_def.remote_version,
                    skill_def.stars,
                ),
            )
            self._upsert_fts(conn, skill_def)
            conn.commit()

    def _upsert_fts(self, conn: sqlite3.Connection, skill_def: SkillDefinition) -> None:
        """更新 FTS5 索引（删除旧记录 + 插入新记录）"""
        try:
            conn.execute("DELETE FROM skills_fts WHERE skill_id = ?", (skill_def.id,))
            conn.execute(
                "INSERT INTO skills_fts(skill_id, name, description, tags) VALUES (?, ?, ?, ?)",
                (
                    skill_def.id,
                    skill_def.name,
                    skill_def.description,
                    json.dumps(skill_def.tags, ensure_ascii=False),
                ),
            )
        except sqlite3.OperationalError:
            pass

    def skill_exists(self, skill_id: str) -> bool:
        """检查技能是否已存在于数据库中"""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            return row is not None

    def count_skills(self) -> int:
        """获取技能总数"""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                return conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        except Exception:
            return 0

    def row_to_skill_def(self, row: sqlite3.Row) -> SkillDefinition:
        """将数据库行转换为 SkillDefinition（V2 — 含新字段）"""
        keys = row.keys() if hasattr(row, "keys") else []
        return SkillDefinition(
            id=row["id"],
            name=row["name"],
            version=row["version"],
            description=row["description"],
            author=row["author"],
            category=row["category"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            dependencies=json.loads(row["dependencies"]) if row["dependencies"] else [],
            install_count=row["install_count"],
            rating=row["rating"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            markdown_content=row["markdown_content"] or "",
            is_builtin=bool(row["is_builtin"]),
            publisher=row["publisher"] if "publisher" in keys else (row["author"] or ""),
            verified=bool(row["verified"]) if "verified" in keys else False,
            source_url=row["source_url"] if "source_url" in keys else "",
            homepage_url=row["homepage_url"] if "homepage_url" in keys else "",
            license=row["license"] if "license" in keys else "",
            icon_url=row["icon_url"] if "icon_url" in keys else "",
            local_version=row["local_version"] if "local_version" in keys else "",
            remote_version=row["remote_version"] if "remote_version" in keys else "",
            stars=row["stars"] if "stars" in keys else 0,
        )

    def row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库行转换为字典（V2 — 与前端 SkillItem 完全对齐）"""
        keys = list(row.keys()) if hasattr(row, "keys") else []

        def _get(name: str, default: Any = None) -> Any:
            return row[name] if name in keys else default

        rating_count = _get("rating_count", 0)
        rating_val = _get("rating", 0.0)
        local_v = _get("local_version", "")
        remote_v = _get("remote_version", "")
        has_update = bool(remote_v and local_v and remote_v != local_v)

        return {
            "id": row["id"],
            "name": row["name"],
            "version": row["version"],
            "description": row["description"],
            "author": row["author"],
            "category": row["category"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "dependencies": json.loads(row["dependencies"]) if row["dependencies"] else [],
            "install_count": row["install_count"],
            "rating": rating_val,
            "rating_count": rating_count,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_builtin": bool(row["is_builtin"]),
            "installed": bool(row["installed_at"]),
            "publisher": _get("publisher", "") or row["author"],
            "verified": bool(_get("verified", 0)),
            "source_url": _get("source_url", ""),
            "homepage_url": _get("homepage_url", ""),
            "license": _get("license", ""),
            "icon_url": _get("icon_url", ""),
            "local_version": local_v,
            "remote_version": remote_v,
            "stars": _get("stars", 0),
            "downloads": row["install_count"],
            "has_update": has_update,
            "installs": row["install_count"],
            "ratings_count": rating_count,
        }

    @property
    def db_path(self) -> Path:
        """数据库路径"""
        return self._db_path

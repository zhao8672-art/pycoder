"""
技能市场模块 — OpenClaw ClawHub 风格技能生态

提供技能的注册、发现、安装、管理和评分功能。
技能元数据存储在 SQLite 数据库中，技能内容存储在文件系统 data/skills/ 目录中。

V2 升级 (2026-07):
- 字段对齐前端 SkillItem（stars/downloads/has_update/verified/publisher/reviews）
- FTS5 全文索引 + BM25 相关性排序
- 递归安装依赖 + 拓扑排序 + 环检测 + 失败回滚
- 原子评分 + UNIQUE(skill_id, user_id) 防刷分
- 详情页扩展：截图/版本历史/评分分布/评论正文
- 异步安装任务 + 进度推送
- 版本检查 + 更新流程

用法:
    from pycoder.skills import SkillMarketplace, SkillDefinition, register_capabilities

    # 获取单例
    marketplace = SkillMarketplace()

    # 注册技能
    await marketplace.register_skill(skill_def, markdown_content)

    # 搜索技能（V2 FTS5）
    results = await marketplace.search_skills_v2("code review")
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ── 数据目录 ──────────────────────────────────────

DATA_DIR = Path("data/skills")
"""技能内容存储目录"""

DB_PATH = DATA_DIR / "skills.db"
"""技能元数据 SQLite 数据库路径"""


# ── 数据模型 ──────────────────────────────────────


@dataclass
class SkillDefinition:
    """技能定义数据类（V2 — 与前端 SkillItem 字段对齐）"""

    id: str
    """唯一标识符，如 'code-review'"""
    name: str
    """技能名称"""
    version: str = "1.0.0"
    """版本号"""
    description: str = ""
    """技能描述"""
    author: str = "PyCoder"
    """作者（兼容字段，新代码用 publisher）"""
    category: str = "general"
    """分类"""
    tags: list[str] = field(default_factory=list)
    """标签列表"""
    dependencies: list[str] = field(default_factory=list)
    """依赖的技能 ID 列表"""
    install_count: int = 0
    """安装次数（前端 downloads 字段映射）"""
    rating: float = 0.0
    """平均评分 (1-5)"""
    created_at: str = ""
    """创建时间 ISO 格式"""
    updated_at: str = ""
    """更新时间 ISO 格式"""
    markdown_content: str = ""
    """技能 Markdown 内容"""
    is_builtin: bool = False
    """是否为内置技能"""

    # ── V2 新增字段（对齐前端 SkillItem）──
    publisher: str = ""
    """发布者名称（与 author 同义，前端字段）"""
    verified: bool = False
    """是否为已验证发布者"""
    source_url: str = ""
    """远程源 URL（GitHub release / 自建 registry）"""
    homepage_url: str = ""
    """主页 URL"""
    license: str = ""
    """开源许可证"""
    icon_url: str = ""
    """图标 URL"""
    local_version: str = ""
    """本地已安装版本（用于更新检测）"""
    remote_version: str = ""
    """远程最新版本（用于更新检测）"""
    stars: int = 0
    """星标数（前端字段，独立于 rating）"""

    def __post_init__(self) -> None:
        """publisher 缺省时回退到 author"""
        if not self.publisher:
            self.publisher = self.author

    @property
    def has_update(self) -> bool:
        """是否有可用更新（前端字段）"""
        return bool(
            self.remote_version
            and self.local_version
            and self.remote_version != self.local_version
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（与前端 SkillItem 接口对齐）"""
        return {
            # 基础字段
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "install_count": self.install_count,
            "rating": self.rating,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_builtin": self.is_builtin,
            # V2 新增字段（前端期望）
            "publisher": self.publisher or self.author,
            "verified": self.verified,
            "source_url": self.source_url,
            "homepage_url": self.homepage_url,
            "license": self.license,
            "icon_url": self.icon_url,
            "local_version": self.local_version,
            "remote_version": self.remote_version,
            "stars": self.stars,
            "downloads": self.install_count,  # 前端别名
            "has_update": self.has_update,
        }


# ── 技能市场 ──────────────────────────────────────


class SkillMarketplace:
    """技能市场管理器 — 单例模式

    管理技能的注册、安装、搜索、评分等操作。
    元数据存储在 SQLite 中，技能 `.md` 文件存储在 data/skills/ 目录。
    """

    _instance: SkillMarketplace | None = None

    def __new__(cls) -> SkillMarketplace:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._db_path = DB_PATH
        self._skills_dir = DATA_DIR
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._preinstall_builtins()

    # ── 数据库初始化 ──────────────────────────────

    def _init_db(self) -> None:
        """初始化 SQLite 数据库和表结构（V2 — 含增量迁移）"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # ── 迁移预处理：检测并重命名带表级 UNIQUE 约束的旧表 ──
            # 必须在 CREATE TABLE IF NOT EXISTS 之前执行
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
            # 注意：不使用 contentless 表（content=''），否则 UNINDEXED 列不存储值
            # 标准 FTS5 表会存储 UNINDEXED 列，可正常 SELECT skill_id
            try:
                conn.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                        skill_id UNINDEXED,
                        name,
                        description,
                        tags
                    );
                """)
                # 重建索引（仅当索引行数少于技能表行数时）
                cnt = conn.execute("SELECT COUNT(*) FROM skills_fts").fetchone()[0]
                total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
                if cnt < total:
                    # 标准表支持 DELETE，可安全清空
                    conn.execute("DELETE FROM skills_fts")
                    conn.execute(
                        "INSERT INTO skills_fts(skill_id, name, description, tags) "
                        "SELECT id, name, description, tags FROM skills"
                    )
                logger.info("FTS5 索引就绪: %d 条", cnt or total)
            except sqlite3.OperationalError as e:
                # SQLite 编译时未启用 FTS5 → 降级到 LIKE
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
        """检测并重建带表级 UNIQUE 约束的表（SQLite 不支持直接删除约束）

        通过检查 sqlite_master 的 sql 字段判断是否含 UNIQUE(skill_id, user_id)，
        若有则备份数据 → DROP 旧表 → 让 CREATE TABLE IF NOT EXISTS 重建 → 恢复数据
        """
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row or not row[0]:
                return
            sql_lower = row[0].lower()
            # 仅当表级 UNIQUE 约束存在时迁移
            if "unique(skill_id, user_id)" not in sql_lower.replace(" ", ""):
                return
            logger.info("迁移: %s 表检测到 UNIQUE 约束，开始重建", table)
            # 备份 → 删除 → 重建（CREATE TABLE IF NOT EXISTS 在后续脚本中执行）
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old_v1")  # nosec B608
            logger.info("迁移: %s 旧表已重命名为 %s_old_v1", table, table)
        except sqlite3.OperationalError as e:
            logger.debug("迁移检查跳过 %s: %s", table, e)

    def _preinstall_builtins(self) -> None:
        """预安装内置技能（如果尚未安装）"""
        try:
            # 修复已有内置技能: 按内置 ID 列表标记已安装（兼容 is_builtin=0 的旧数据）
            builtin_ids = [
                "code-review", "test-generator", "doc-generator", "refactor-helper",
                "security-scanner", "performance-analyzer", "git-helper",
                "dependency-checker", "lint-fixer", "api-doc-generator",
                "code-explainer", "project-scaffolder",
            ]
            now = __import__("datetime").datetime.now().isoformat()
            with sqlite3.connect(str(self._db_path)) as conn:
                placeholders = ",".join("?" for _ in builtin_ids)
                conn.execute(
                    f"UPDATE skills SET is_builtin=1, installed_at=? "
                    f"WHERE id IN ({placeholders}) "
                    f"AND (installed_at IS NULL OR installed_at = '')",
                    [now] + builtin_ids,
                )
                updated = conn.total_changes
                if updated:
                    logger.info("内置技能安装状态已修复: %d 个", updated)

            from pycoder.skills.builtin import BUILTIN_SKILLS

            for skill_def in BUILTIN_SKILLS:
                if not self._skill_exists(skill_def.id):
                    self._save_skill_to_db(skill_def, mark_as_installed=True)
                    self._save_skill_content(skill_def)
                    logger.info("内置技能已安装", skill_id=skill_def.id, name=skill_def.name)
        except ImportError:
            logger.warning("无法加载内置技能模块")

    def import_external_skills(self) -> dict:
        """从外部数据源导入技能到 SQLite 数据库（Tech Leads + OpenClaw）

        将 EnhancedSkill → SkillDefinition 转换后写入 skills.db，
        使 5000+ 外部技能可通过 V2 API 搜索。

        Returns:
            导入结果统计
        """
        try:
            from pycoder.server.skills_external_sources import fetch_all_external_skills
        except ImportError:
            return {"success": False, "error": "技能采集模块不可用"}

        all_skills, sources_status = fetch_all_external_skills()
        added = 0
        skipped = 0
        errors = 0

        now = __import__("datetime").datetime.now().isoformat()

        for es in all_skills:
            if self._skill_exists(es.id):
                skipped += 1
                continue

            try:
                # EnhancedSkill → SkillDefinition
                tags = (es.tags or []) + (es.topics or [])
                sd = SkillDefinition(
                    id=es.id,
                    name=es.name,
                    version=es.version or "1.0.0",
                    description=(es.description or "")[:500],
                    author=es.author or "Community",
                    category=es.category or "other",
                    tags=list(set(tags))[:10],
                    install_count=max(es.downloads, 1),
                    rating=min(es.rating, 5.0) if es.rating else 0,
                    created_at=now,
                    updated_at=now,
                    is_builtin=False,
                    publisher=es.author or "Community",
                    verified=es.verified,
                    source_url=es.repository_url or es.url or "",
                    stars=es.stars or 0,
                )
                self._save_skill_to_db(sd, mark_as_installed=False)
                added += 1
            except Exception as e:
                logger.debug("导入外部技能失败", skill_id=es.id, error=str(e)[:60])
                errors += 1

        # 重建 FTS5 索引
        try:
            import sqlite3
            with sqlite3.connect(str(self._db_path)) as conn:
                total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
                conn.execute("DELETE FROM skills_fts")
                conn.execute(
                    "INSERT INTO skills_fts(skill_id, name, description, tags) "
                    "SELECT id, name, description, tags FROM skills"
                )
                conn.commit()
            logger.info("外部技能 FTS5 索引已重建", total=total)
        except Exception as e:
            logger.debug("FTS5 重建失败", error=str(e)[:60])

        return {
            "success": True,
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "total_in_db": self._count_skills(),
            "sources": sources_status,
        }

    def _count_skills(self) -> int:
        """获取技能总数"""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                return conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        except Exception:
            return 0

    def _skill_exists(self, skill_id: str) -> bool:
        """检查技能是否已存在于数据库中"""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            return row is not None

    def _save_skill_to_db(
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
            # 同步 FTS5 索引
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
            # FTS5 不可用时静默降级
            pass

    def _save_skill_content(self, skill_def: SkillDefinition) -> None:
        """将技能 Markdown 内容保存到文件系统"""
        if not skill_def.markdown_content:
            return
        skill_dir = self._skills_dir / skill_def.id
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_def.markdown_content, encoding="utf-8")

    def _load_skill_content(self, skill_id: str) -> str:
        """从文件系统加载技能 Markdown 内容"""
        skill_file = self._skills_dir / skill_id / "SKILL.md"
        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")
        return ""

    def _row_to_skill_def(self, row: sqlite3.Row) -> SkillDefinition:
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
            # V2 新字段（兼容旧库，缺列时回退）
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

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库行转换为字典（V2 — 与前端 SkillItem 完全对齐）"""
        keys = list(row.keys()) if hasattr(row, "keys") else []
        # 兼容旧库
        def _get(name: str, default: Any = None) -> Any:
            return row[name] if name in keys else default

        rating_count = _get("rating_count", 0)
        rating_val = _get("rating", 0.0)
        local_v = _get("local_version", "")
        remote_v = _get("remote_version", "")
        has_update = bool(remote_v and local_v and remote_v != local_v)

        return {
            # 基础字段
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
            # V2 新增字段（前端期望）
            "publisher": _get("publisher", "") or row["author"],
            "verified": bool(_get("verified", 0)),
            "source_url": _get("source_url", ""),
            "homepage_url": _get("homepage_url", ""),
            "license": _get("license", ""),
            "icon_url": _get("icon_url", ""),
            "local_version": local_v,
            "remote_version": remote_v,
            "stars": _get("stars", 0),
            # 前端别名
            "downloads": row["install_count"],
            "has_update": has_update,
            "installs": row["install_count"],
            "ratings_count": rating_count,
        }

    # ── 技能注册 ──────────────────────────────────

    async def register_skill(
        self, skill_def: SkillDefinition, markdown_content: str
    ) -> dict[str, Any]:
        """注册技能 — 从 Markdown 内容注册技能（OpenClaw 风格）

        Args:
            skill_def: 技能定义数据
            markdown_content: 技能的 Markdown 内容

        Returns:
            注册结果字典
        """
        if not skill_def.id or not skill_def.name:
            return {"success": False, "error": "技能 ID 和名称不能为空"}

        if not markdown_content.strip():
            return {"success": False, "error": "技能 Markdown 内容不能为空"}

        skill_def.markdown_content = markdown_content
        now = datetime.now(timezone.utc).isoformat()
        if not skill_def.created_at:
            skill_def.created_at = now
        skill_def.updated_at = now

        try:
            self._save_skill_to_db(skill_def, mark_as_installed=False)
            self._save_skill_content(skill_def)
            logger.info("技能已注册", skill_id=skill_def.id, name=skill_def.name)
            return {
                "success": True,
                "skill_id": skill_def.id,
                "name": skill_def.name,
                "version": skill_def.version,
            }
        except sqlite3.IntegrityError:
            return {"success": False, "error": f"技能 ID '{skill_def.id}' 已存在"}
        except Exception as e:
            logger.error("技能注册失败", skill_id=skill_def.id, error=str(e))
            return {"success": False, "error": str(e)}

    # ── 技能安装（V2 — 递归依赖 + 环检测 + 回滚）──

    async def install_skill(
        self,
        skill_id: str,
        *,
        install_dependencies: bool = True,
        user_id: str = "anonymous",
    ) -> dict[str, Any]:
        """安装技能到本地（V2 — 递归安装依赖 + 失败回滚）

        Args:
            skill_id: 技能 ID
            install_dependencies: 是否递归安装依赖（默认 True）
            user_id: 触发安装的用户 ID（用于任务追踪）

        Returns:
            安装结果字典，含 installed_ids / failed_dependency / rolled_back
        """
        # 1. 检查技能存在性
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            if not row:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}
            if row["installed_at"]:
                return {
                    "success": True, "skill_id": skill_id,
                    "message": "技能已安装", "action": "skip",
                }

        # 2. 拓扑排序依赖（含环检测）
        if install_dependencies:
            try:
                install_order = self._topological_sort(skill_id)
            except ValueError as e:
                return {"success": False, "error": f"依赖环检测失败: {e}"}
        else:
            install_order = [skill_id]

        # 3. 按序安装，失败时回滚已安装的
        installed_ids: list[str] = []
        for sid in install_order:
            result = self._install_single(sid)
            if result["success"]:
                if result.get("action") != "skip" or sid == skill_id:
                    installed_ids.append(sid)
            else:
                # 回滚已安装的依赖（按反序）
                rolled_back: list[str] = []
                for rb_sid in reversed(installed_ids):
                    if rb_sid != skill_id:  # 不回滚目标技能本身
                        self._rollback_install(rb_sid)
                        rolled_back.append(rb_sid)
                return {
                    "success": False,
                    "error": f"安装依赖 '{sid}' 失败: {result.get('error', '未知错误')}",
                    "failed_dependency": sid,
                    "rolled_back": rolled_back,
                    "installed_ids": installed_ids,
                }

        # 4. 返回结果
        now = datetime.now(timezone.utc).isoformat()
        target_row = None
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            target_row = conn.execute(
                "SELECT name FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

        logger.info(
            "技能安装完成 (含依赖)",
            skill_id=skill_id,
            installed_count=len(installed_ids),
            all_ids=installed_ids,
        )
        return {
            "success": True,
            "skill_id": skill_id,
            "name": target_row["name"] if target_row else "",
            "installed_at": now,
            "action": "installed",
            "installed_ids": installed_ids,
            "dependencies_installed": [s for s in installed_ids if s != skill_id],
        }

    def _topological_sort(self, root_skill_id: str) -> list[str]:
        """拓扑排序依赖（DFS + 环检测）

        Args:
            root_skill_id: 根技能 ID

        Returns:
            按依赖顺序排列的技能 ID 列表（根技能在最后）

        Raises:
            ValueError: 检测到依赖环
        """
        visited: set[str] = set()        # 已完成访问
        in_stack: set[str] = set()       # 当前递归栈中（用于环检测）
        order: list[str] = []

        def _visit(sid: str, path: list[str]) -> None:
            if sid in visited:
                return
            if sid in in_stack:
                cycle = " → ".join(path + [sid])
                raise ValueError(f"依赖环: {cycle}")
            in_stack.add(sid)

            # 查询当前技能的依赖
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT dependencies FROM skills WHERE id = ?", (sid,)
                ).fetchone()
                if row:
                    deps = json.loads(row["dependencies"]) if row["dependencies"] else []
                    for dep in deps:
                        _visit(dep, path + [sid])

            in_stack.discard(sid)
            visited.add(sid)
            order.append(sid)

        _visit(root_skill_id, [])
        return order

    def _install_single(self, skill_id: str) -> dict[str, Any]:
        """安装单个技能（不含依赖处理）"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

            if not row:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

            if row["installed_at"]:
                return {
                    "success": True, "skill_id": skill_id,
                    "action": "skip", "message": "已安装",
                }

            now = datetime.now(timezone.utc).isoformat()
            # 同步 local_version = version（用于更新检测）
            local_v = row["local_version"] if "local_version" in row.keys() else ""
            if not local_v:
                local_v = row["version"]
            conn.execute(
                "UPDATE skills SET installed_at = ?, "
                "install_count = install_count + 1, "
                "local_version = COALESCE(NULLIF(local_version, ''), version) "
                "WHERE id = ?",
                (now, skill_id),
            )
            conn.commit()
            content = row["markdown_content"]

        # 确保文件内容已写入
        if content and not self._load_skill_content(skill_id):
            skill_dir = self._skills_dir / skill_id
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        return {
            "success": True,
            "skill_id": skill_id,
            "action": "installed",
            "installed_at": now,
        }

    def _rollback_install(self, skill_id: str) -> None:
        """回滚单个技能的安装（不计入卸载次数）"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE skills SET installed_at = '', local_version = '' WHERE id = ?",
                (skill_id,),
            )
            conn.commit()
        skill_dir = self._skills_dir / skill_id
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir, ignore_errors=True)
        logger.info("回滚安装: %s", skill_id)

    async def uninstall_skill(self, skill_id: str) -> dict[str, Any]:
        """卸载技能

        Args:
            skill_id: 技能 ID

        Returns:
            卸载结果字典
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT is_builtin, installed_at FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

            if not row:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

            if bool(row["is_builtin"]):
                return {"success": False, "error": "内置技能不可卸载"}

            if not row["installed_at"]:
                return {
                    "success": True, "skill_id": skill_id,
                    "message": "技能未安装", "action": "skip",
                }

            conn.execute(
                "UPDATE skills SET installed_at = '', "
                "install_count = MAX(0, install_count - 1) WHERE id = ?",
                (skill_id,),
            )
            conn.commit()

        # 删除技能文件
        skill_dir = self._skills_dir / skill_id
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir, ignore_errors=True)

        logger.info("技能已卸载", skill_id=skill_id)
        return {"success": True, "skill_id": skill_id, "action": "uninstalled"}

    # ── 技能搜索 ──────────────────────────────────

    async def search_skills(
        self,
        query: str = "",
        category: str = "",
        tags: list[str] | None = None,
        limit: int = 0,
    ) -> dict[str, Any]:
        """搜索技能

        Args:
            query: 搜索关键词（匹配名称、描述）
            category: 分类过滤
            tags: 标签过滤列表
            limit: 最大返回数量（0=不限）

        Returns:
            搜索结果字典，包含 skills 列表和 total 计数
        """
        conditions: list[str] = []
        params: list[Any] = []

        if query:
            conditions.append("(name LIKE ? OR description LIKE ?)")
            like_query = f"%{query}%"
            params.extend([like_query, like_query])

        if category:
            conditions.append("category = ?")
            params.append(category)

        if tags:
            tag_conditions = " OR ".join(["tags LIKE ?" for _ in tags])
            conditions.append(f"({tag_conditions})")
            params.extend([f'%"{t}"%' for t in tags])

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        limit_clause = "LIMIT ?" if limit > 0 else ""

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} "  # nosec B608
                f"ORDER BY rating DESC, install_count DESC {limit_clause}",
                params if limit <= 0 else [*params, limit],
            ).fetchall()

        skills = [self._row_to_dict(r) for r in rows]
        return {"skills": skills, "total": len(skills)}

    # ── V2 搜索（FTS5 + 多维筛选 + 分页 + BM25）──

    async def search_skills_v2(
        self,
        query: str = "",
        category: str = "",
        tags: list[str] | None = None,
        *,
        min_rating: float = 0.0,
        max_rating: float = 5.0,
        min_downloads: int = 0,
        max_downloads: int = 0,
        updated_within_days: int = 0,
        author: str = "",
        verified_only: bool = False,
        has_update_only: bool = False,
        installed_only: bool | None = None,
        sort_by: str = "relevance",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """V2 统一搜索 — FTS5 全文检索 + 12 维筛选 + 分页

        Args:
            query: 搜索关键词（FTS5 + LIKE 兜底）
            category: 分类
            tags: 标签列表
            min_rating / max_rating: 评分范围
            min_downloads / max_downloads: 下载量范围（max=0 表示不限）
            updated_within_days: 最近 N 天内更新（0=不限）
            author: 作者筛选
            verified_only: 仅已验证
            has_update_only: 仅显示有更新可用
            installed_only: True=仅已安装 / False=仅未安装 / None=全部
            sort_by: relevance / rating / downloads / updated / name / stars
            page: 页码（从 1 开始）
            page_size: 每页数量（1-100）

        Returns:
            {skills, total, page, page_size, took_ms, sort_by}
        """
        start = time.monotonic()
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        conditions: list[str] = []
        params: list[Any] = []
        fts_ids: list[str] | None = None  # FTS5 命中的 skill_id 列表

        # 1. FTS5 全文搜索（优先），失败降级到 LIKE
        if query and query.strip():
            fts_ids = self._fts_search(query.strip())
            if fts_ids is not None:
                # FTS5 命中，按 BM25 排序的结果限制 ID 集合
                if not fts_ids:
                    # FTS5 执行成功但无结果，尝试 LIKE 兜底
                    conditions.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
                    like_q = f"%{query}%"
                    params.extend([like_q, like_q, like_q])
                else:
                    placeholders = ",".join("?" * len(fts_ids))
                    conditions.append(f"id IN ({placeholders})")
                    params.extend(fts_ids)
                    # 此时 sort_by 默认按 relevance（已在 fts_search 中按 BM25 排序）
                    # 后续 SQL 仅做过滤，最终顺序由 Python 重排
            else:
                # FTS5 不可用，LIKE 兜底
                conditions.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q])

        # 2. 维度筛选
        if category:
            conditions.append("category = ?")
            params.append(category)
        if tags:
            tag_conds = " OR ".join(["tags LIKE ?" for _ in tags])
            conditions.append(f"({tag_conds})")
            params.extend([f'%"{t}"%' for t in tags])
        if min_rating > 0:
            conditions.append("rating >= ?")
            params.append(min_rating)
        if max_rating < 5:
            conditions.append("rating <= ?")
            params.append(max_rating)
        if min_downloads > 0:
            conditions.append("install_count >= ?")
            params.append(min_downloads)
        if max_downloads > 0:
            conditions.append("install_count <= ?")
            params.append(max_downloads)
        if updated_within_days > 0:
            cutoff = (datetime.now(timezone.utc).timestamp() - updated_within_days * 86400)
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            conditions.append("updated_at >= ?")
            params.append(cutoff_iso)
        if author:
            conditions.append("(author LIKE ? OR publisher LIKE ?)")
            like_a = f"%{author}%"
            params.extend([like_a, like_a])
        if verified_only:
            conditions.append("verified = 1")
        if has_update_only:
            conditions.append("remote_version != '' AND local_version != '' AND remote_version != local_version")
        if installed_only is True:
            conditions.append("installed_at != ''")
        elif installed_only is False:
            conditions.append("installed_at = ''")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 3. 排序
        sort_map = {
            "relevance": "rating DESC, install_count DESC",  # FTS 命中后由 Python 重排
            "rating": "rating DESC, rating_count DESC",
            "downloads": "install_count DESC",
            "updated": "updated_at DESC",
            "name": "name ASC",
            "stars": "stars DESC, rating DESC",
        }
        # 若 FTS5 命中且有结果，强制按 relevance（fts_ids 顺序）
        if query and fts_ids:
            order_clause = f"CASE id {' '.join(['WHEN ? THEN ' + str(i) for i in range(len(fts_ids))])} ELSE {len(fts_ids)} END"
            order_params = list(fts_ids)
        else:
            order_clause = sort_map.get(sort_by, sort_map["relevance"])
            order_params = []

        # 4. 查询总数 + 分页数据
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                f"SELECT COUNT(*) as cnt FROM skills WHERE {where_clause}",  # nosec B608
                params,
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} "  # nosec B608
                f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
                [*params, *order_params, page_size, offset],
            ).fetchall()

        skills = [self._row_to_dict(r) for r in rows]
        took_ms = int((time.monotonic() - start) * 1000)

        return {
            "skills": skills,
            "total": total,
            "page": page,
            "page_size": page_size,
            "took_ms": took_ms,
            "sort_by": sort_by,
            "query": query,
        }

    def _fts_search(self, query: str, limit: int = 200) -> list[str] | None:
        """执行 FTS5 全文搜索

        Args:
            query: 搜索词
            limit: 最大返回数量

        Returns:
            按相关性排序的 skill_id 列表；None 表示 FTS5 不可用
        """
        # 中文分词：用空格分隔（jieba 可选）
        fts_query = self._tokenize_for_fts(query)
        if not fts_query:
            return None

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                # FTS5 MATCH 语法：词之间默认 AND，加 * 支持前缀匹配
                match_expr = " AND ".join(
                    f'"{w}"*' if " " not in w and not w.startswith('"') else w
                    for w in fts_query.split() if w
                )
                rows = conn.execute(
                    "SELECT skill_id FROM skills_fts "
                    "WHERE skills_fts MATCH ? "
                    "ORDER BY bm25(skills_fts) "  # BM25 相关性排序
                    "LIMIT ?",
                    (match_expr, limit),
                ).fetchall()
                return [r[0] for r in rows]
        except sqlite3.OperationalError as e:
            logger.debug("FTS5 搜索失败，降级 LIKE: %s", e)
            return None

    @staticmethod
    def _tokenize_for_fts(query: str) -> str:
        """分词（中文用 jieba，英文按空格）"""
        # 尝试用 jieba 分词（如果可用）
        try:
            import jieba  # type: ignore[import-not-found]
            tokens = [t for t in jieba.cut(query, cut_all=False) if t.strip()]
            return " ".join(tokens)
        except ImportError:
            # 无 jieba 时，简单按空格和标点切分
            import re
            tokens = re.split(r"[\s,，。、;；:：!！?？/\\]+", query)
            return " ".join(t for t in tokens if t)

    # ── 技能列表 ──────────────────────────────────

    async def list_skills(
        self,
        category: str = "",
        sort_by: str = "rating",
        limit: int = 50,
    ) -> dict[str, Any]:
        """列出技能，支持排序和分类过滤

        Args:
            category: 分类过滤
            sort_by: 排序字段 — rating / install_count / name / updated_at
            limit: 最大返回数量

        Returns:
            技能列表字典
        """
        valid_sort_fields = {
            "rating": "rating DESC",
            "install_count": "install_count DESC",
            "name": "name ASC",
            "updated_at": "updated_at DESC",
        }
        order_clause = valid_sort_fields.get(sort_by, "rating DESC")

        conditions: list[str] = []
        params: list[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} ORDER BY {order_clause} LIMIT ?",  # nosec B608
                [*params, limit],
            ).fetchall()

        skills = [self._row_to_dict(r) for r in rows]
        return {"skills": skills, "total": len(skills)}

    # ── 技能详情（V2 — 含截图/版本/评分分布/评论）──

    async def get_skill(self, skill_id: str) -> dict[str, Any]:
        """获取技能详情（含 Markdown 内容 + V2 扩展数据）

        Args:
            skill_id: 技能 ID

        Returns:
            技能详情字典（含 screenshots/versions/rating_distribution/reviews/recent_ratings）
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

            if not row:
                return {"error": f"技能 '{skill_id}' 不存在"}

        skill_dict = self._row_to_dict(row)
        # 加载文件系统中的最新内容
        file_content = self._load_skill_content(skill_id)
        skill_dict["markdown_content"] = file_content or row["markdown_content"]

        # ── V2 扩展：截图列表 ──
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            screenshots = conn.execute(
                "SELECT url, caption, sort_order FROM skill_screenshots "
                "WHERE skill_id = ? ORDER BY sort_order ASC, id ASC",
                (skill_id,),
            ).fetchall()
            skill_dict["screenshots"] = [
                {"url": s["url"], "caption": s["caption"]}
                for s in screenshots
            ]

        # ── V2 扩展：版本历史 ──
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            versions = conn.execute(
                "SELECT version, released_at, changelog, download_url, download_count "
                "FROM skill_versions WHERE skill_id = ? "
                "ORDER BY released_at DESC LIMIT 20",
                (skill_id,),
            ).fetchall()
            skill_dict["versions"] = [
                {
                    "version": v["version"],
                    "released_at": v["released_at"],
                    "changelog": v["changelog"],
                    "download_url": v["download_url"],
                    "download_count": v["download_count"],
                }
                for v in versions
            ]

        # ── V2 扩展：评分分布（5/4/3/2/1 星各多少）──
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            dist_rows = conn.execute(
                "SELECT rating, COUNT(*) as cnt FROM skill_reviews "
                "WHERE skill_id = ? GROUP BY rating ORDER BY rating DESC",
                (skill_id,),
            ).fetchall()
            dist = {str(i): 0 for i in range(1, 6)}
            for r in dist_rows:
                dist[str(r["rating"])] = r["cnt"]
            skill_dict["rating_distribution"] = dist

        # ── V2 扩展：评论列表（含 review_text）──
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            review_rows = conn.execute(
                "SELECT user_name, user_id, rating, review_text, created_at, updated_at, helpful_count "
                "FROM skill_reviews WHERE skill_id = ? "
                "ORDER BY created_at DESC LIMIT 10",
                (skill_id,),
            ).fetchall()
            skill_dict["reviews"] = [
                {
                    "user": r["user_name"],
                    "user_id": r["user_id"],
                    "rating": r["rating"],
                    "review": r["review_text"],
                    "review_text": r["review_text"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "helpful_count": r["helpful_count"],
                }
                for r in review_rows
            ]

        # ── 兼容旧字段：recent_ratings ──
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rating_rows = conn.execute(
                "SELECT rating, user, created_at FROM ratings "
                "WHERE skill_id = ? ORDER BY created_at DESC LIMIT 10",
                (skill_id,),
            ).fetchall()
            skill_dict["recent_ratings"] = [dict(r) for r in rating_rows]

        return {"skill": skill_dict}

    # ── V2 详情扩展方法 ──────────────────────────────

    async def add_screenshot(
        self, skill_id: str, url: str, caption: str = "", sort_order: int = 0
    ) -> dict[str, Any]:
        """添加截图"""
        with sqlite3.connect(str(self._db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO skill_screenshots (skill_id, url, caption, sort_order) "
                "VALUES (?, ?, ?, ?)",
                (skill_id, url, caption, sort_order),
            )
            conn.commit()
            return {"success": True, "id": cur.lastrowid, "skill_id": skill_id}

    async def add_version(
        self,
        skill_id: str,
        version: str,
        changelog: str = "",
        download_url: str = "",
        released_at: str = "",
    ) -> dict[str, Any]:
        """添加版本历史记录"""
        released_at = released_at or datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self._db_path)) as conn:
            try:
                conn.execute(
                    "INSERT INTO skill_versions "
                    "(skill_id, version, released_at, changelog, download_url) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (skill_id, version, released_at, changelog, download_url),
                )
                # 同步更新 skills.remote_version
                conn.execute(
                    "UPDATE skills SET remote_version = ? WHERE id = ?",
                    (version, skill_id),
                )
                conn.commit()
                return {"success": True, "skill_id": skill_id, "version": version}
            except sqlite3.IntegrityError:
                return {"success": False, "error": f"版本 {version} 已存在"}

    # ── 技能更新 ──────────────────────────────────

    async def update_skill(self, skill_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """更新技能信息

        Args:
            skill_id: 技能 ID
            updates: 要更新的字段字典

        Returns:
            更新结果字典
        """
        allowed_fields = {
            "name",
            "version",
            "description",
            "author",
            "category",
            "tags",
            "dependencies",
            "markdown_content",
        }
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
        if not update_fields:
            return {"success": False, "error": "没有可更新的字段"}

        # 处理 JSON 字段
        if "tags" in update_fields and isinstance(update_fields["tags"], list):
            update_fields["tags"] = json.dumps(update_fields["tags"], ensure_ascii=False)
        if "dependencies" in update_fields and isinstance(update_fields["dependencies"], list):
            update_fields["dependencies"] = json.dumps(
                update_fields["dependencies"], ensure_ascii=False
            )

        now = datetime.now(timezone.utc).isoformat()
        set_clauses = [f"{k} = ?" for k in update_fields]
        set_clauses.append("updated_at = ?")
        params = list(update_fields.values()) + [now, skill_id]

        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                f"UPDATE skills SET {', '.join(set_clauses)} WHERE id = ?",  # nosec B608
                params,
            )
            if cursor.rowcount == 0:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}
            conn.commit()

        # 如果更新了 markdown_content，同步到文件系统
        if "markdown_content" in update_fields:
            md_content = updates.get("markdown_content", "")
            skill_dir = self._skills_dir / skill_id
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        logger.info("技能已更新", skill_id=skill_id, fields=list(update_fields.keys()))
        return {"success": True, "skill_id": skill_id, "updated_fields": list(update_fields.keys())}

    # ── 技能评分（V2 — 原子更新 + 防刷分 + 评论）──

    async def rate_skill(
        self,
        skill_id: str,
        rating: int,
        *,
        user_id: str = "anonymous",
        user_name: str = "anonymous",
        review_text: str = "",
    ) -> dict[str, Any]:
        """为技能评分（V2 — 单事务原子更新 + UNIQUE 约束防刷分）

        Args:
            skill_id: 技能 ID
            rating: 评分 (1-5)
            user_id: 用户 ID（默认 anonymous，需登录后传入以启用一人一评）
            user_name: 用户显示名
            review_text: 评论文本（可选）

        Returns:
            评分结果字典，含 new_rating / rating_count / is_update
        """
        if rating < 1 or rating > 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}

        now = datetime.now(timezone.utc).isoformat()
        is_update = False
        old_rating = 0
        # 匿名用户允许多次评分（V1 兼容）；登录用户启用一人一评
        enforce_unique = user_id != "anonymous"

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")  # 加写锁，防并发竞态

            try:
                # 1. 验证技能存在
                row = conn.execute(
                    "SELECT id FROM skills WHERE id = ?", (skill_id,)
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

                # 2. 检查是否已评分（仅登录用户启用 UNIQUE 约束）
                if enforce_unique:
                    existing = conn.execute(
                        "SELECT rating FROM skill_reviews "
                        "WHERE skill_id = ? AND user_id = ?",
                        (skill_id, user_id),
                    ).fetchone()

                    if existing:
                        # 更新已有评分
                        is_update = True
                        old_rating = existing["rating"]
                        conn.execute(
                            "UPDATE skill_reviews SET rating = ?, review_text = ?, "
                            "updated_at = ? WHERE skill_id = ? AND user_id = ?",
                            (rating, review_text, now, skill_id, user_id),
                        )
                    else:
                        # 插入新评分
                        conn.execute(
                            "INSERT INTO skill_reviews "
                            "(skill_id, user_id, user_name, rating, review_text, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (skill_id, user_id, user_name, rating, review_text, now, now),
                        )
                else:
                    # 匿名用户：直接插入，不检查重复
                    conn.execute(
                        "INSERT INTO skill_reviews "
                        "(skill_id, user_id, user_name, rating, review_text, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (skill_id, user_id, user_name, rating, review_text, now, now),
                    )

                # 3. 原子重算评分汇总（避免 race condition）
                conn.execute(
                    """
                    UPDATE skills SET
                        rating_count = (SELECT COUNT(*) FROM skill_reviews WHERE skill_id = ?),
                        rating_sum = (SELECT COALESCE(SUM(rating), 0) FROM skill_reviews WHERE skill_id = ?),
                        rating = ROUND(
                            CAST((SELECT COALESCE(SUM(rating), 0) FROM skill_reviews WHERE skill_id = ?) AS REAL) /
                            MAX(1, (SELECT COUNT(*) FROM skill_reviews WHERE skill_id = ?)),
                            1
                        )
                    WHERE id = ?
                    """,
                    (skill_id, skill_id, skill_id, skill_id, skill_id),
                )

                # 4. 同时兼容旧 ratings 表（用于历史数据查询）
                if not is_update:
                    conn.execute(
                        "INSERT INTO ratings (skill_id, rating, user) VALUES (?, ?, ?)",
                        (skill_id, rating, user_id),
                    )

                # 5. 获取更新后的评分
                updated = conn.execute(
                    "SELECT rating, rating_count FROM skills WHERE id = ?",
                    (skill_id,),
                ).fetchone()

                conn.execute("COMMIT")
            except sqlite3.IntegrityError as e:
                # UNIQUE 约束冲突（理论上不会发生，因为前面已检查）
                conn.execute("ROLLBACK")
                logger.warning("评分冲突: skill=%s user=%s err=%s", skill_id, user_id, e)
                return {"success": False, "error": "评分冲突，请重试"}
            except Exception as e:
                conn.execute("ROLLBACK")
                logger.error("评分失败: skill=%s err=%s", skill_id, e)
                return {"success": False, "error": str(e)}

        logger.info(
            "技能已评分",
            skill_id=skill_id,
            rating=rating,
            user=user_id,
            is_update=is_update,
            old_rating=old_rating,
        )
        return {
            "success": True,
            "skill_id": skill_id,
            "new_rating": updated["rating"] if updated else 0.0,
            "rating_count": updated["rating_count"] if updated else 0,
            "is_update": is_update,
            "previous_rating": old_rating if is_update else None,
        }

    async def submit_review(
        self,
        skill_id: str,
        rating: int,
        review_text: str,
        *,
        user_id: str = "anonymous",
        user_name: str = "anonymous",
    ) -> dict[str, Any]:
        """提交评价（评分 + 评论正文）— rate_skill 的别名，强调评论

        Args:
            skill_id: 技能 ID
            rating: 评分 1-5
            review_text: 评论正文
            user_id: 用户 ID
            user_name: 用户显示名

        Returns:
            提交结果
        """
        return await self.rate_skill(
            skill_id,
            rating,
            user_id=user_id,
            user_name=user_name,
            review_text=review_text,
        )

    async def get_reviews(
        self,
        skill_id: str,
        *,
        sort_by: str = "recent",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """获取技能评论列表

        Args:
            skill_id: 技能 ID
            sort_by: 排序 — recent / helpful / rating_desc / rating_asc
            limit: 返回数量
            offset: 分页偏移

        Returns:
            评论列表 + 总数
        """
        sort_map = {
            "recent": "created_at DESC",
            "helpful": "helpful_count DESC, created_at DESC",
            "rating_desc": "rating DESC, created_at DESC",
            "rating_asc": "rating ASC, created_at DESC",
        }
        order_clause = sort_map.get(sort_by, "created_at DESC")

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM skill_reviews WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT * FROM skill_reviews WHERE skill_id = ? "  # nosec B608
                f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
                (skill_id, limit, offset),
            ).fetchall()

        reviews = [
            {
                "id": r["id"],
                "user": r["user_name"],
                "user_id": r["user_id"],
                "rating": r["rating"],
                "review": r["review_text"],
                "review_text": r["review_text"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "helpful_count": r["helpful_count"],
            }
            for r in rows
        ]
        return {"reviews": reviews, "total": total, "sort_by": sort_by}

    # ── 异步安装任务（V2 — 进度推送 + 状态追踪）──

    async def create_install_task(
        self,
        skill_id: str,
        *,
        user_id: str = "anonymous",
        install_dependencies: bool = True,
    ) -> dict[str, Any]:
        """创建异步安装任务（用于进度反馈场景）

        Args:
            skill_id: 技能 ID
            user_id: 用户 ID
            install_dependencies: 是否递归安装依赖

        Returns:
            {task_id, skill_id, status}
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO install_tasks (task_id, skill_id, status, user_id) "
                "VALUES (?, ?, 'pending', ?)",
                (task_id, skill_id, user_id),
            )
            conn.commit()

        # 同步执行安装（简化实现，可后续改为 asyncio.create_task 后台执行）
        await self._run_install_task(
            task_id, skill_id, install_dependencies=install_dependencies
        )
        return {"task_id": task_id, "skill_id": skill_id, "status": "pending"}

    async def _run_install_task(
        self, task_id: str, skill_id: str, *, install_dependencies: bool = True
    ) -> None:
        """执行安装任务并更新进度"""
        self._update_task(task_id, status="running", progress=10, step="🔍 检查依赖")
        try:
            # 拓扑排序
            if install_dependencies:
                self._update_task(task_id, progress=20, step="📋 解析依赖图")
                try:
                    order = self._topological_sort(skill_id)
                except ValueError as e:
                    self._update_task(
                        task_id, status="failed", error=str(e), progress=0,
                        step="❌ 依赖环检测失败", completed=True,
                    )
                    return
            else:
                order = [skill_id]

            total = len(order)
            installed: list[str] = []
            for i, sid in enumerate(order):
                pct = 20 + int((i / max(total, 1)) * 70)
                self._update_task(
                    task_id, progress=pct,
                    step=f"📥 安装 {sid} ({i + 1}/{total})",
                )
                result = self._install_single(sid)
                if not result["success"] and result.get("action") != "skip":
                    # 回滚
                    for rb in reversed(installed):
                        if rb != skill_id:
                            self._rollback_install(rb)
                    self._update_task(
                        task_id, status="failed",
                        error=f"安装 {sid} 失败: {result.get('error', '')}",
                        progress=pct, step="❌ 安装失败（已回滚）",
                        completed=True,
                    )
                    return
                installed.append(sid)

            self._update_task(
                task_id, status="done", progress=100,
                step=f"✅ 安装完成（{total} 个技能）", completed=True,
            )
        except Exception as e:
            self._update_task(
                task_id, status="failed", error=str(e),
                step="❌ 内部错误", completed=True,
            )

    def _update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        step: str | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> None:
        """更新任务状态"""
        sets: list[str] = []
        params: list[Any] = []
        if status:
            sets.append("status = ?")
            params.append(status)
        if progress is not None:
            sets.append("progress = ?")
            params.append(progress)
        if step:
            sets.append("current_step = ?")
            params.append(step)
        if error:
            sets.append("error = ?")
            params.append(error)
        if completed:
            sets.append("completed_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
        if not sets:
            return
        params.append(task_id)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                f"UPDATE install_tasks SET {', '.join(sets)} WHERE task_id = ?",  # nosec B608
                params,
            )
            conn.commit()

    async def get_install_task(self, task_id: str) -> dict[str, Any]:
        """查询安装任务进度"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM install_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return {"error": f"任务 '{task_id}' 不存在"}
            return {
                "task_id": row["task_id"],
                "skill_id": row["skill_id"],
                "status": row["status"],
                "progress": row["progress"],
                "current_step": row["current_step"],
                "error": row["error"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
            }

    # ── 版本检查与更新（V2）──

    async def check_updates(self, skill_id: str | None = None) -> dict[str, Any]:
        """检查可用更新

        Args:
            skill_id: 指定技能 ID；None=检查所有已安装技能

        Returns:
            {updates: [{skill_id, local, remote}], count}
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if skill_id:
                rows = conn.execute(
                    "SELECT id, name, local_version, remote_version, source_url "
                    "FROM skills WHERE id = ? AND installed_at != ''",
                    (skill_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, local_version, remote_version, source_url "
                    "FROM skills WHERE installed_at != '' "
                    "AND remote_version != '' AND local_version != '' "
                    "AND remote_version != local_version"
                ).fetchall()

        updates = [
            {
                "skill_id": r["id"],
                "name": r["name"],
                "local_version": r["local_version"],
                "remote_version": r["remote_version"],
                "source_url": r["source_url"],
            }
            for r in rows
            if r["remote_version"] and r["local_version"]
            and r["remote_version"] != r["local_version"]
        ]
        return {"updates": updates, "count": len(updates)}

    async def update_skill_version(
        self, skill_id: str, *, user_id: str = "anonymous"
    ) -> dict[str, Any]:
        """更新单个技能到 remote_version

        Returns:
            更新结果
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT local_version, remote_version, installed_at "
                "FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not row:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}
            if not row["installed_at"]:
                return {"success": False, "error": "技能未安装"}
            if not row["remote_version"]:
                return {"success": False, "error": "无远程版本信息"}
            if row["local_version"] == row["remote_version"]:
                return {"success": True, "action": "skip", "message": "已是最新"}

            # 升级 local_version
            conn.execute(
                "UPDATE skills SET local_version = remote_version, "
                "version = remote_version, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), skill_id),
            )
            conn.commit()

        return {
            "success": True,
            "skill_id": skill_id,
            "action": "updated",
            "new_version": row["remote_version"],
        }

    async def update_all(self, *, user_id: str = "anonymous") -> dict[str, Any]:
        """批量更新所有有可用更新的技能

        Returns:
            {updated: [...], failed: [...], skipped: [...]}
        """
        updates_info = await self.check_updates()
        updated: list[str] = []
        failed: list[dict] = []
        skipped: list[str] = []

        for item in updates_info["updates"]:
            sid = item["skill_id"]
            result = await self.update_skill_version(sid, user_id=user_id)
            if result.get("success"):
                if result.get("action") == "skip":
                    skipped.append(sid)
                else:
                    updated.append(sid)
            else:
                failed.append({"skill_id": sid, "error": result.get("error", "")})

        return {"updated": updated, "failed": failed, "skipped": skipped}

    # ── 远程 Registry 同步（V2 P4-1）──

    async def sync_from_registry(
        self,
        client: Any,
        *,
        progress: Any = None,
    ) -> dict[str, Any]:
        """从远程 Registry 同步技能到本地数据库

        策略：
        - 新技能：INSERT
        - 已存在技能：UPDATE 远程字段（version/description/...），保留本地字段
          （install_count/rating/installed_at/local_version/is_builtin）
        - 同步后 remote_version 字段更新为远程最新版本（用于 has_update 检测）

        Args:
            client: RegistryClient 实例
            progress: 可选异步进度回调 (completed, total, step) -> None

        Returns:
            {total, new, updated, unchanged, failed, errors}
        """
        from pycoder.skills.registry_client import SyncResult

        result = SyncResult()
        skills = await client.fetch_all(progress)
        result.total = len(skills)

        for s in skills:
            try:
                # 在 upsert 之前查询本地版本，用于判断 new/updated/unchanged
                with sqlite3.connect(str(self._db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT version FROM skills WHERE id = ?", (s.id,)
                    ).fetchone()
                local_version_before = row["version"] if row else None

                await self._upsert_from_registry(s)

                if local_version_before is None:
                    result.new += 1
                elif local_version_before != s.version:
                    result.updated += 1
                else:
                    result.unchanged += 1
            except Exception as e:
                result.failed += 1
                result.errors.append(f"{s.id}: {e}")
                logger.error("同步技能 %s 失败: %s", s.id, e)

        return result.to_dict()

    async def _upsert_from_registry(self, remote: Any) -> None:
        """将远程技能 upsert 到本地数据库（保留本地数据）

        策略：
        - 如果本地不存在：直接 INSERT，installed_at='', local_version=''
        - 如果本地存在：UPDATE 远程字段，保留 install_count/rating/installed_at/
          local_version/is_builtin/rating_count/rating_sum

        Args:
            remote: RegistrySkill 实例
        """
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT id, install_count, rating, rating_count, rating_sum, "
                "installed_at, local_version, is_builtin, created_at, markdown_content "
                "FROM skills WHERE id = ?",
                (remote.id,),
            ).fetchone()

            if existing is None:
                # 新技能：INSERT
                sd = SkillDefinition(
                    id=remote.id,
                    name=remote.name,
                    version=remote.version,
                    description=remote.description,
                    author=remote.author,
                    category=remote.category,
                    tags=remote.tags,
                    dependencies=remote.dependencies,
                    publisher=remote.publisher or remote.author,
                    verified=remote.verified,
                    source_url=remote.source_url,
                    homepage_url=remote.homepage_url,
                    license=remote.license,
                    icon_url=remote.icon_url,
                    stars=remote.stars,
                    remote_version=remote.version,
                    local_version="",
                    markdown_content=remote.markdown_content,
                    created_at=now,
                    updated_at=now,
                )
                self._save_skill_to_db(sd, mark_as_installed=False)
                self._save_skill_content(sd)
            else:
                # 已存在：UPDATE 远程字段，保留本地字段
                # markdown_content: 远程为空时保留本地
                new_md = remote.markdown_content or existing["markdown_content"]
                conn.execute(
                    """
                    UPDATE skills SET
                        name = ?,
                        version = ?,
                        description = ?,
                        author = ?,
                        category = ?,
                        tags = ?,
                        dependencies = ?,
                        publisher = ?,
                        verified = ?,
                        source_url = ?,
                        homepage_url = ?,
                        license = ?,
                        icon_url = ?,
                        stars = ?,
                        remote_version = ?,
                        markdown_content = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        remote.name,
                        remote.version,
                        remote.description,
                        remote.author,
                        remote.category,
                        json.dumps(remote.tags, ensure_ascii=False),
                        json.dumps(remote.dependencies, ensure_ascii=False),
                        remote.publisher or remote.author,
                        1 if remote.verified else 0,
                        remote.source_url,
                        remote.homepage_url,
                        remote.license,
                        remote.icon_url,
                        remote.stars,
                        remote.version,
                        new_md,
                        now,
                        remote.id,
                    ),
                )
                # 同步 FTS5 索引
                sd_for_fts = SkillDefinition(
                    id=remote.id,
                    name=remote.name,
                    description=remote.description,
                    tags=remote.tags,
                )
                self._upsert_fts(conn, sd_for_fts)
                # 更新文件系统内容（如有新内容）
                if remote.markdown_content:
                    sd_content = SkillDefinition(
                        id=remote.id,
                        name=remote.name,
                        markdown_content=remote.markdown_content,
                    )
                    self._save_skill_content(sd_content)
                conn.commit()

    # ── 收藏（V2）──

    async def toggle_favorite(
        self, skill_id: str, user_id: str = "anonymous"
    ) -> dict[str, Any]:
        """收藏/取消收藏"""
        with sqlite3.connect(str(self._db_path)) as conn:
            existing = conn.execute(
                "SELECT 1 FROM skill_favorites WHERE user_id = ? AND skill_id = ?",
                (user_id, skill_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM skill_favorites WHERE user_id = ? AND skill_id = ?",
                    (user_id, skill_id),
                )
                conn.commit()
                return {"success": True, "skill_id": skill_id, "favorited": False}
            conn.execute(
                "INSERT INTO skill_favorites (user_id, skill_id) VALUES (?, ?)",
                (user_id, skill_id),
            )
            conn.commit()
            return {"success": True, "skill_id": skill_id, "favorited": True}

    async def get_favorites(self, user_id: str = "anonymous") -> dict[str, Any]:
        """获取收藏列表"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT s.* FROM skills s "
                "JOIN skill_favorites f ON s.id = f.skill_id "
                "WHERE f.user_id = ? ORDER BY f.created_at DESC",
                (user_id,),
            ).fetchall()
        return {"skills": [self._row_to_dict(r) for r in rows], "total": len(rows)}

    # ── 分类与统计（V2）──

    async def list_categories(self) -> dict[str, Any]:
        """获取分类列表（含计数）"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt, "
                "SUM(install_count) as installs, "
                "ROUND(AVG(rating), 1) as avg_rating "
                "FROM skills GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
        return {
            "categories": [
                {
                    "name": r["category"],
                    "count": r["cnt"],
                    "total_installs": r["installs"] or 0,
                    "avg_rating": r["avg_rating"] or 0.0,
                }
                for r in rows
            ]
        }

    # ── 统计信息 ──────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取市场统计信息

        Returns:
            统计信息字典
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row

            total = conn.execute("SELECT COUNT(*) as cnt FROM skills").fetchone()["cnt"]
            installed = conn.execute(
                "SELECT COUNT(*) as cnt FROM skills WHERE installed_at != ''"
            ).fetchone()["cnt"]
            builtin = conn.execute(
                "SELECT COUNT(*) as cnt FROM skills WHERE is_builtin = 1"
            ).fetchone()["cnt"]
            avg_rating = conn.execute(
                "SELECT ROUND(AVG(rating), 1) as avg_r FROM skills WHERE rating_count > 0"
            ).fetchone()["avg_r"] or 0.0
            total_installs = conn.execute(
                "SELECT SUM(install_count) as total FROM skills"
            ).fetchone()["total"] or 0
            total_ratings = conn.execute(
                "SELECT COUNT(*) as cnt FROM ratings"
            ).fetchone()["cnt"]

            # 分类统计
            categories = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM skills GROUP BY category ORDER BY cnt DESC"
            ).fetchall()

        return {
            "total_skills": total,
            "installed_skills": installed,
            "builtin_skills": builtin,
            "average_rating": avg_rating,
            "total_installs": total_installs,
            "total_ratings": total_ratings,
            "categories": {c["category"]: c["cnt"] for c in categories},
            "data_dir": str(self._skills_dir),
        }


# ── 全局单例 ──────────────────────────────────────

_marketplace: SkillMarketplace | None = None


def get_marketplace() -> SkillMarketplace:
    """获取技能市场全局单例"""
    global _marketplace
    if _marketplace is None:
        _marketplace = SkillMarketplace()
    return _marketplace


# ── 能力注册 ──────────────────────────────────────


def register_capabilities(registry: Any) -> None:
    """向总线注册技能市场相关能力

    Args:
        registry: CapabilityRegistry 实例
    """
    # ── skills.marketplace.search ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.search",
            name="搜索技能",
            description="在技能市场中搜索技能，支持关键词、分类和标签过滤",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "search", "技能", "搜索"],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类过滤"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签过滤",
                    },
                },
            },
        ),
        handler=_handle_search_skills,
    )

    # ── skills.marketplace.install ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.install",
            name="安装技能",
            description="安装指定的技能到本地",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            tags=["skills", "marketplace", "install", "技能", "安装"],
            schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "要安装的技能 ID"},
                },
                "required": ["skill_id"],
            },
        ),
        handler=_handle_install_skill,
    )

    # ── skills.marketplace.list ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.list",
            name="列出技能",
            description="列出技能市场中的技能，支持分类过滤和排序",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "list", "技能", "列表"],
            schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "分类过滤"},
                    "sort_by": {
                        "type": "string",
                        "enum": ["rating", "install_count", "name", "updated_at"],
                        "description": "排序方式",
                    },
                    "limit": {"type": "integer", "description": "最大返回数量，默认 50"},
                },
            },
        ),
        handler=_handle_list_skills,
    )

    # ── v1.skills_market (向下兼容: V1 旧名 → V2 新名映射) ──
    registry.register(
        CapabilityDefinition(
            id="v1.skills_market",
            name="技能市场(旧名兼容)",
            description=("技能市场管理（向下兼容 V1 名称）。"
                         "支持 list/install/search/info 操作"),
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "v1", "legacy", "兼容"],
            schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "install", "search"],
                        "description": "操作类型",
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类过滤"},
                    "skill_id": {"type": "string", "description": "技能 ID"},
                    "limit": {"type": "integer", "description": "最大返回数量"},
                },
                "required": [],
            },
        ),
        handler=_handle_v1_skills_market,
    )

    # ── skills.marketplace.info ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.info",
            name="获取技能详情",
            description="获取指定技能的详细信息，包括 Markdown 内容和评分",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "info", "技能", "详情"],
            schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "技能 ID"},
                },
                "required": ["skill_id"],
            },
        ),
        handler=_handle_get_skill,
    )

    # ── skills.marketplace.stats ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.stats",
            name="获取市场统计",
            description="获取技能市场的统计信息，包括技能总数、安装数、评分等",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "stats", "技能", "统计"],
            schema={
                "type": "object",
                "properties": {},
            },
        ),
        handler=_handle_get_stats,
    )

    logger.info("技能市场能力已注册")


# ── 能力处理器 ──────────────────────────────────────


async def _handle_search_skills(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理技能搜索"""
    marketplace = get_marketplace()
    return await marketplace.search_skills(
        query=params.get("query", ""),
        category=params.get("category", ""),
        tags=params.get("tags"),
    )


async def _handle_install_skill(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理技能安装"""
    marketplace = get_marketplace()
    return await marketplace.install_skill(params["skill_id"])


async def _handle_list_skills(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理技能列表"""
    marketplace = get_marketplace()
    return await marketplace.list_skills(
        category=params.get("category", ""),
        sort_by=params.get("sort_by", "rating"),
        limit=params.get("limit", 50),
    )


async def _handle_get_skill(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理获取技能详情"""
    marketplace = get_marketplace()
    return await marketplace.get_skill(params["skill_id"])


async def _handle_get_stats(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理获取市场统计"""
    marketplace = get_marketplace()
    return marketplace.get_stats()


async def _handle_v1_skills_market(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """V1 兼容：skills_market 多合一调度

    根据 action 字段分发到具体的 V2 处理器：
    - action=list   → _handle_list_skills
    - action=search → _handle_search_skills
    - action=install → _handle_install_skill
    - 无 action     → 默认 list
    """
    action = params.get("action", "list")
    marketplace = get_marketplace()

    if action == "install":
        sid = params.get("skill_id", "")
        if not sid:
            return {"error": "install requires 'skill_id'"}
        return await marketplace.install_skill(sid)

    if action == "search":
        return await marketplace.search_skills(
            query=params.get("query", ""),
            category=params.get("category", ""),
            limit=params.get("limit", 20),
        )

    # 默认: list
    return await marketplace.list_skills(
        category=params.get("category", ""),
        sort_by=params.get("sort_by", "rating"),
        limit=params.get("limit", 50),
    )
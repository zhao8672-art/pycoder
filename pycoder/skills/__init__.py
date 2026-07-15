"""
技能市场模块 — OpenClaw ClawHub 风格技能生态

提供技能的注册、发现、安装、管理和评分功能。
技能元数据存储在 SQLite 数据库中，技能内容存储在文件系统 data/skills/ 目录中。

用法:
    from pycoder.skills import SkillMarketplace, SkillDefinition, register_capabilities

    # 获取单例
    marketplace = SkillMarketplace()

    # 注册技能
    await marketplace.register_skill(skill_def, markdown_content)

    # 搜索技能
    results = await marketplace.search_skills("code review")
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
    """技能定义数据类"""

    id: str
    """唯一标识符，如 'code-review'"""
    name: str
    """技能名称"""
    version: str = "1.0.0"
    """版本号"""
    description: str = ""
    """技能描述"""
    author: str = "PyCoder"
    """作者"""
    category: str = "general"
    """分类"""
    tags: list[str] = field(default_factory=list)
    """标签列表"""
    dependencies: list[str] = field(default_factory=list)
    """依赖的技能 ID 列表"""
    install_count: int = 0
    """安装次数"""
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

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
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
        """初始化 SQLite 数据库和表结构"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript("""
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
            """)
            conn.commit()
        logger.info("技能市场数据库已初始化", path=str(self._db_path))

    def _preinstall_builtins(self) -> None:
        """预安装内置技能（如果尚未安装）"""
        try:
            from pycoder.skills.builtin import BUILTIN_SKILLS

            for skill_def in BUILTIN_SKILLS:
                if not self._skill_exists(skill_def.id):
                    self._save_skill_to_db(skill_def, mark_as_installed=False)
                    self._save_skill_content(skill_def)
                    logger.info("内置技能已安装", skill_id=skill_def.id, name=skill_def.name)
        except ImportError:
            logger.warning("无法加载内置技能模块")

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
        """将技能保存到 SQLite 数据库"""
        now = datetime.now(timezone.utc).isoformat()
        if not skill_def.created_at:
            skill_def.created_at = now
        if not skill_def.updated_at:
            skill_def.updated_at = now

        installed_at = now if mark_as_installed else ""

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skills
                    (id, name, version, description, author, category, tags,
                     dependencies, install_count, rating, rating_count, rating_sum,
                     created_at, updated_at, markdown_content, is_builtin, installed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            conn.commit()

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
        """将数据库行转换为 SkillDefinition"""
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
        )

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库行转换为字典（不含 markdown_content 全文）"""
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
            "rating": row["rating"],
            "rating_count": row["rating_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_builtin": bool(row["is_builtin"]),
            "installed": bool(row["installed_at"]),
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

    # ── 技能安装 ──────────────────────────────────

    async def install_skill(self, skill_id: str) -> dict[str, Any]:
        """安装技能到本地

        Args:
            skill_id: 技能 ID

        Returns:
            安装结果字典
        """
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

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE skills SET installed_at = ?, "
                "install_count = install_count + 1 WHERE id = ?",
                (now, skill_id),
            )
            conn.commit()

        # 确保文件内容已写入
        if not self._load_skill_content(skill_id):
            content = row["markdown_content"]
            if content:
                skill_dir = self._skills_dir / skill_id
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        logger.info("技能已安装", skill_id=skill_id)
        return {
            "success": True,
            "skill_id": skill_id,
            "name": row["name"],
            "installed_at": now,
            "action": "installed",
        }

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
    ) -> dict[str, Any]:
        """搜索技能

        Args:
            query: 搜索关键词（匹配名称、描述）
            category: 分类过滤
            tags: 标签过滤列表

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

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} "
                "ORDER BY rating DESC, install_count DESC",
                params,
            ).fetchall()

        skills = [self._row_to_dict(r) for r in rows]
        return {"skills": skills, "total": len(skills)}

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
                f"SELECT * FROM skills WHERE {where_clause} ORDER BY {order_clause} LIMIT ?",
                [*params, limit],
            ).fetchall()

        skills = [self._row_to_dict(r) for r in rows]
        return {"skills": skills, "total": len(skills)}

    # ── 技能详情 ──────────────────────────────────

    async def get_skill(self, skill_id: str) -> dict[str, Any]:
        """获取技能详情（含 Markdown 内容）

        Args:
            skill_id: 技能 ID

        Returns:
            技能详情字典，或包含 error 的字典
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

        # 加载评分记录
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rating_rows = conn.execute(
                "SELECT rating, user, created_at FROM ratings "
                "WHERE skill_id = ? ORDER BY created_at DESC LIMIT 10",
                (skill_id,),
            ).fetchall()
            skill_dict["recent_ratings"] = [dict(r) for r in rating_rows]

        return {"skill": skill_dict}

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

    # ── 技能评分 ──────────────────────────────────

    async def rate_skill(self, skill_id: str, rating: int) -> dict[str, Any]:
        """为技能评分

        Args:
            skill_id: 技能 ID
            rating: 评分 (1-5)

        Returns:
            评分结果字典
        """
        if rating < 1 or rating > 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            if not row:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

            # 插入评分记录
            conn.execute(
                "INSERT INTO ratings (skill_id, rating) VALUES (?, ?)",
                (skill_id, rating),
            )

            # 更新技能的平均评分
            conn.execute(
                """
                UPDATE skills SET
                    rating_count = rating_count + 1,
                    rating_sum = rating_sum + ?,
                    rating = ROUND((rating_sum + ?) * 1.0 / (rating_count + 1), 1)
                WHERE id = ?
                """,
                (rating, rating, skill_id),
            )
            conn.commit()

            # 获取更新后的评分
            updated = conn.execute(
                "SELECT rating, rating_count FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

        logger.info("技能已评分", skill_id=skill_id, rating=rating)
        return {
            "success": True,
            "skill_id": skill_id,
            "new_rating": updated["rating"],
            "rating_count": updated["rating_count"],
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
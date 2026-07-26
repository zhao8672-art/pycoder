"""技能市场管理器 — 单例模式，管理技能的注册、安装、搜索、评分等操作"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pycoder.skills.db import DATA_DIR, SkillDatabase
from pycoder.skills.models import SkillDefinition

logger = logging.getLogger(__name__)


class SkillMarketplace:
    """技能市场管理器 — 单例模式"""

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
        self._db = SkillDatabase()
        self._skills_dir = DATA_DIR
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._preinstall_builtins()

    # ── 内置技能 ──────────────────────────────────

    def _preinstall_builtins(self) -> None:
        """预安装内置技能（如果尚未安装）"""
        try:
            builtin_ids = [
                "code-review", "test-generator", "doc-generator", "refactor-helper",
                "security-scanner", "performance-analyzer", "git-helper",
                "dependency-checker", "lint-fixer", "api-doc-generator",
                "code-explainer", "project-scaffolder",
            ]
            now = datetime.now().isoformat()
            with sqlite3.connect(str(self._db.db_path)) as conn:
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
                if not self._db.skill_exists(skill_def.id):
                    self._db.save_skill_to_db(skill_def, mark_as_installed=True)
                    self._save_skill_content(skill_def)
                    logger.info("内置技能已安装", skill_id=skill_def.id, name=skill_def.name)
        except ImportError:
            logger.warning("无法加载内置技能模块")

    # ── 外部技能导入 ──────────────────────────────

    def import_external_skills(self) -> dict:
        """从外部数据源导入技能到 SQLite 数据库"""
        try:
            from pycoder.core.services.external_skills import fetch_all_external_skills
        except ImportError:
            return {"success": False, "error": "技能采集模块不可用"}

        all_skills, sources_status = fetch_all_external_skills()
        added = 0
        skipped = 0
        errors = 0
        now = datetime.now().isoformat()

        for es in all_skills:
            if self._db.skill_exists(es.id):
                skipped += 1
                continue
            try:
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
                self._db.save_skill_to_db(sd, mark_as_installed=False)
                added += 1
            except Exception as e:
                logger.debug("导入外部技能失败", skill_id=es.id, error=str(e)[:60])
                errors += 1

        # 重建 FTS5 索引
        try:
            with sqlite3.connect(str(self._db.db_path)) as conn:
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
            "total_in_db": self._db.count_skills(),
            "sources": sources_status,
        }

    # ── 文件系统操作 ──────────────────────────────

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

    # ── 技能注册 ──────────────────────────────────

    async def register_skill(
        self, skill_def: SkillDefinition, markdown_content: str
    ) -> dict[str, Any]:
        """注册技能 — 从 Markdown 内容注册技能"""
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
            self._db.save_skill_to_db(skill_def, mark_as_installed=False)
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
        """安装技能到本地（V2 — 递归安装依赖 + 失败回滚）"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        if install_dependencies:
            try:
                install_order = self._topological_sort(skill_id)
            except ValueError as e:
                return {"success": False, "error": f"依赖环检测失败: {e}"}
        else:
            install_order = [skill_id]

        installed_ids: list[str] = []
        for sid in install_order:
            result = self._install_single(sid)
            if result["success"]:
                if result.get("action") != "skip" or sid == skill_id:
                    installed_ids.append(sid)
            else:
                rolled_back: list[str] = []
                for rb_sid in reversed(installed_ids):
                    if rb_sid != skill_id:
                        self._rollback_install(rb_sid)
                        rolled_back.append(rb_sid)
                return {
                    "success": False,
                    "error": f"安装依赖 '{sid}' 失败: {result.get('error', '未知错误')}",
                    "failed_dependency": sid,
                    "rolled_back": rolled_back,
                    "installed_ids": installed_ids,
                }

        now = datetime.now(timezone.utc).isoformat()
        target_row = None
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        """拓扑排序依赖（DFS + 环检测）"""
        visited: set[str] = set()
        in_stack: set[str] = set()
        order: list[str] = []

        def _visit(sid: str, path: list[str]) -> None:
            if sid in visited:
                return
            if sid in in_stack:
                cycle = " → ".join(path + [sid])
                raise ValueError(f"依赖环: {cycle}")
            in_stack.add(sid)
            with sqlite3.connect(str(self._db.db_path)) as conn:
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
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        """回滚单个技能的安装"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.execute(
                "UPDATE skills SET installed_at = '', local_version = '' WHERE id = ?",
                (skill_id,),
            )
            conn.commit()
        skill_dir = self._skills_dir / skill_id
        if skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)
        logger.info("回滚安装: %s", skill_id)

    async def uninstall_skill(self, skill_id: str) -> dict[str, Any]:
        """卸载技能"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        skill_dir = self._skills_dir / skill_id
        if skill_dir.exists():
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
        """搜索技能"""
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

        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} "  # nosec B608
                f"ORDER BY rating DESC, install_count DESC {limit_clause}",
                params if limit <= 0 else [*params, limit],
            ).fetchall()

        skills = [self._db.row_to_dict(r) for r in rows]
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
        """V2 统一搜索 — FTS5 全文检索 + 12 维筛选 + 分页"""
        start = time.monotonic()
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        conditions: list[str] = []
        params: list[Any] = []
        fts_ids: list[str] | None = None

        if query and query.strip():
            fts_ids = self._fts_search(query.strip())
            if fts_ids is not None:
                if not fts_ids:
                    conditions.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
                    like_q = f"%{query}%"
                    params.extend([like_q, like_q, like_q])
                else:
                    placeholders = ",".join("?" * len(fts_ids))
                    conditions.append(f"id IN ({placeholders})")
                    params.extend(fts_ids)
            else:
                conditions.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q])

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

        sort_map = {
            "relevance": "rating DESC, install_count DESC",
            "rating": "rating DESC, rating_count DESC",
            "downloads": "install_count DESC",
            "updated": "updated_at DESC",
            "name": "name ASC",
            "stars": "stars DESC, rating DESC",
        }
        if query and fts_ids:
            order_clause = f"CASE id {' '.join(['WHEN ? THEN ' + str(i) for i in range(len(fts_ids))])} ELSE {len(fts_ids)} END"
            order_params = list(fts_ids)
        else:
            order_clause = sort_map.get(sort_by, sort_map["relevance"])
            order_params = []

        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        skills = [self._db.row_to_dict(r) for r in rows]
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
        """执行 FTS5 全文搜索"""
        fts_query = self._tokenize_for_fts(query)
        if not fts_query:
            return None
        try:
            with sqlite3.connect(str(self._db.db_path)) as conn:
                match_expr = " AND ".join(
                    f'"{w}"*' if " " not in w and not w.startswith('"') else w
                    for w in fts_query.split() if w
                )
                rows = conn.execute(
                    "SELECT skill_id FROM skills_fts "
                    "WHERE skills_fts MATCH ? "
                    "ORDER BY bm25(skills_fts) "
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
        try:
            import jieba  # type: ignore[import-not-found]
            tokens = [t for t in jieba.cut(query, cut_all=False) if t.strip()]
            return " ".join(tokens)
        except ImportError:
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
        """列出技能，支持排序和分类过滤"""
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

        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where_clause} ORDER BY {order_clause} LIMIT ?",  # nosec B608
                [*params, limit],
            ).fetchall()

        skills = [self._db.row_to_dict(r) for r in rows]
        return {"skills": skills, "total": len(skills)}

    # ── 技能详情 ──────────────────────────────────

    async def get_skill(self, skill_id: str) -> dict[str, Any]:
        """获取技能详情（含 Markdown 内容 + V2 扩展数据）"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            if not row:
                return {"error": f"技能 '{skill_id}' 不存在"}

        skill_dict = self._db.row_to_dict(row)
        file_content = self._load_skill_content(skill_id)
        skill_dict["markdown_content"] = file_content or row["markdown_content"]

        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            screenshots = conn.execute(
                "SELECT url, caption, sort_order FROM skill_screenshots "
                "WHERE skill_id = ? ORDER BY sort_order ASC, id ASC",
                (skill_id,),
            ).fetchall()
            skill_dict["screenshots"] = [
                {"url": s["url"], "caption": s["caption"]} for s in screenshots
            ]

        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        with sqlite3.connect(str(self._db.db_path)) as conn:
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

        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        with sqlite3.connect(str(self._db.db_path)) as conn:
            try:
                conn.execute(
                    "INSERT INTO skill_versions "
                    "(skill_id, version, released_at, changelog, download_url) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (skill_id, version, released_at, changelog, download_url),
                )
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
        """更新技能信息"""
        allowed_fields = {
            "name", "version", "description", "author", "category",
            "tags", "dependencies", "markdown_content",
        }
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
        if not update_fields:
            return {"success": False, "error": "没有可更新的字段"}

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

        with sqlite3.connect(str(self._db.db_path)) as conn:
            cursor = conn.execute(
                f"UPDATE skills SET {', '.join(set_clauses)} WHERE id = ?",  # nosec B608
                params,
            )
            if cursor.rowcount == 0:
                return {"success": False, "error": f"技能 '{skill_id}' 不存在"}
            conn.commit()

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
        """为技能评分（V2 — 单事务原子更新 + UNIQUE 约束防刷分）"""
        if rating < 1 or rating > 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}

        now = datetime.now(timezone.utc).isoformat()
        is_update = False
        old_rating = 0
        enforce_unique = user_id != "anonymous"

        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")

            try:
                row = conn.execute(
                    "SELECT id FROM skills WHERE id = ?", (skill_id,)
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

                if enforce_unique:
                    existing = conn.execute(
                        "SELECT rating FROM skill_reviews "
                        "WHERE skill_id = ? AND user_id = ?",
                        (skill_id, user_id),
                    ).fetchone()
                    if existing:
                        is_update = True
                        old_rating = existing["rating"]
                        conn.execute(
                            "UPDATE skill_reviews SET rating = ?, review_text = ?, "
                            "updated_at = ? WHERE skill_id = ? AND user_id = ?",
                            (rating, review_text, now, skill_id, user_id),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO skill_reviews "
                            "(skill_id, user_id, user_name, rating, review_text, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (skill_id, user_id, user_name, rating, review_text, now, now),
                        )
                else:
                    conn.execute(
                        "INSERT INTO skill_reviews "
                        "(skill_id, user_id, user_name, rating, review_text, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (skill_id, user_id, user_name, rating, review_text, now, now),
                    )

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

                if not is_update:
                    conn.execute(
                        "INSERT INTO ratings (skill_id, rating, user) VALUES (?, ?, ?)",
                        (skill_id, rating, user_id),
                    )

                updated = conn.execute(
                    "SELECT rating, rating_count FROM skills WHERE id = ?",
                    (skill_id,),
                ).fetchone()
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as e:
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
        """提交评价（评分 + 评论正文）— rate_skill 的别名"""
        return await self.rate_skill(
            skill_id, rating,
            user_id=user_id, user_name=user_name, review_text=review_text,
        )

    async def get_reviews(
        self,
        skill_id: str,
        *,
        sort_by: str = "recent",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """获取技能评论列表"""
        sort_map = {
            "recent": "created_at DESC",
            "helpful": "helpful_count DESC, created_at DESC",
            "rating_desc": "rating DESC, created_at DESC",
            "rating_asc": "rating ASC, created_at DESC",
        }
        order_clause = sort_map.get(sort_by, "created_at DESC")

        with sqlite3.connect(str(self._db.db_path)) as conn:
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

    # ── 异步安装任务 ──────────────────────────────

    async def create_install_task(
        self,
        skill_id: str,
        *,
        user_id: str = "anonymous",
        install_dependencies: bool = True,
    ) -> dict[str, Any]:
        """创建异步安装任务"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.execute(
                "INSERT INTO install_tasks (task_id, skill_id, status, user_id) "
                "VALUES (?, ?, 'pending', ?)",
                (task_id, skill_id, user_id),
            )
            conn.commit()

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
        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.execute(
                f"UPDATE install_tasks SET {', '.join(sets)} WHERE task_id = ?",  # nosec B608
                params,
            )
            conn.commit()

    async def get_install_task(self, task_id: str) -> dict[str, Any]:
        """查询安装任务进度"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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

    # ── 版本检查与更新 ────────────────────────────

    async def check_updates(self, skill_id: str | None = None) -> dict[str, Any]:
        """检查可用更新"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        """更新单个技能到 remote_version"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        """批量更新所有有可用更新的技能"""
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

    # ── 远程 Registry 同步 ────────────────────────

    async def sync_from_registry(
        self,
        client: Any,
        *,
        progress: Any = None,
    ) -> dict[str, Any]:
        """从远程 Registry 同步技能到本地数据库"""
        from pycoder.skills.registry_client import SyncResult

        result = SyncResult()
        skills = await client.fetch_all(progress)
        result.total = len(skills)

        for s in skills:
            try:
                with sqlite3.connect(str(self._db.db_path)) as conn:
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
        """将远程技能 upsert 到本地数据库"""
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT id, install_count, rating, rating_count, rating_sum, "
                "installed_at, local_version, is_builtin, created_at, markdown_content "
                "FROM skills WHERE id = ?",
                (remote.id,),
            ).fetchone()

            if existing is None:
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
                self._db.save_skill_to_db(sd, mark_as_installed=False)
                self._save_skill_content(sd)
            else:
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
                sd_for_fts = SkillDefinition(
                    id=remote.id,
                    name=remote.name,
                    description=remote.description,
                    tags=remote.tags,
                )
                self._db._upsert_fts(conn, sd_for_fts)
                if remote.markdown_content:
                    sd_content = SkillDefinition(
                        id=remote.id,
                        name=remote.name,
                        markdown_content=remote.markdown_content,
                    )
                    self._save_skill_content(sd_content)
                conn.commit()

    # ── 收藏 ──────────────────────────────────────

    async def toggle_favorite(
        self, skill_id: str, user_id: str = "anonymous"
    ) -> dict[str, Any]:
        """收藏/取消收藏"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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
        with sqlite3.connect(str(self._db.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT s.* FROM skills s "
                "JOIN skill_favorites f ON s.id = f.skill_id "
                "WHERE f.user_id = ? ORDER BY f.created_at DESC",
                (user_id,),
            ).fetchall()
        return {"skills": [self._db.row_to_dict(r) for r in rows], "total": len(rows)}

    # ── 分类与统计 ────────────────────────────────

    async def list_categories(self) -> dict[str, Any]:
        """获取分类列表（含计数）"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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

    def get_stats(self) -> dict[str, Any]:
        """获取市场统计信息"""
        with sqlite3.connect(str(self._db.db_path)) as conn:
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

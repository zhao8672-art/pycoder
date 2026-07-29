"""
技能生命周期引擎 — Phase 2

功能:
1. 技能生命周期阶段分类 (Emerging → Growing → Mature → Declining)
2. Stack Overflow 年度调查数据导入与趋势计算
3. 每日 28 天趋势快照对比 → 生命周期标签生成

用法:
    from pycoder.server.skills_lifecycle import (
        SkillLifecycleEngine,
        LifecycleStage,
        get_lifecycle_engine,
    )
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pycoder.core.services.log import log


class LifecycleStage(StrEnum):
    """技能生命周期阶段"""

    EMERGING = "emerging"  # 新兴: 28天增速 > 50%, 社区热度快速上升
    GROWING = "growing"  # 增长: 增速 20-50%, 稳定上升
    MATURE = "mature"  # 成熟: 增速 < 20%, 已广泛采用
    DECLINING = "declining"  # 衰退: 增速为负
    STABLE = "stable"  # 稳定: 长期保持, 少量波动
    UNKNOWN = "unknown"  # 数据不足


@dataclass
class SkillSnapshot:
    """技能在某个时间点的快照"""

    skill_id: str
    skill_name: str
    category: str
    stars_28d: int  # 28天新增 star
    stars_total: int  # 总 star
    stars_rate: float  # 28天增速 (小数, 如 0.35)
    source: str  # 数据源
    timestamp: float  # 快照时间


@dataclass
class SkillTrend:
    """技能趋势分析结果"""

    skill_id: str
    skill_name: str
    category: str
    stage: LifecycleStage
    stars_28d: int
    stars_total: int
    growth_rate_28d: float  # 28天增长率
    growth_rate_prev: float  # 前28天增长率 (对比用)
    momentum: float  # 动量: 当前增速 - 前一期增速
    weeks_on_rise: int  # 持续上升周数
    peak_rank: int | None  # 历史最高排名
    current_rank: int  # 当前排名
    source: str

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "category": self.category,
            "stage": self.stage.value,
            "stars_28d": self.stars_28d,
            "stars_total": self.stars_total,
            "growth_rate_28d": round(self.growth_rate_28d, 4),
            "growth_rate_prev": round(self.growth_rate_prev, 4),
            "momentum": round(self.momentum, 4),
            "weeks_on_rise": self.weeks_on_rise,
            "peak_rank": self.peak_rank,
            "current_rank": self.current_rank,
            "source": self.source,
        }


# ── SO 年度调查数据 (2024-2025 趋势片段) ──
# 数据来源: Stack Overflow Developer Survey 2024/2025
# 字段: 技术名称 → [2024采用率%, 2025采用率%]
SO_SURVEY_ADOPTION: dict[str, list[float]] = {
    # 编程语言
    "JavaScript": [62.3, 60.4],
    "Python": [45.4, 51.0],
    "TypeScript": [38.9, 42.2],
    "HTML/CSS": [55.1, 52.8],
    "SQL": [51.5, 48.9],
    "Java": [30.6, 28.9],
    "Bash/Shell": [29.2, 27.1],
    "C#": [27.2, 25.6],
    "C++": [20.8, 21.0],
    "C": [19.2, 18.5],
    "Go": [14.2, 15.8],
    "Rust": [7.2, 9.3],
    "Kotlin": [6.5, 7.1],
    "Ruby": [5.9, 5.2],
    "PHP": [18.4, 15.8],
    "Swift": [4.8, 5.0],
    "R": [4.3, 3.8],
    "Dart": [3.5, 4.2],
    "Lua": [2.8, 3.5],
    "Zig": [0.5, 1.2],
    # Web 框架
    "Node.js": [42.7, 40.8],
    "React": [40.6, 42.5],
    "jQuery": [24.1, 19.5],
    "Express": [22.0, 20.2],
    "Next.js": [13.5, 17.2],
    "Vue.js": [15.2, 14.9],
    "Django": [12.8, 13.5],
    "Angular": [16.7, 14.3],
    "FastAPI": [7.2, 11.0],
    "Spring Boot": [9.8, 9.5],
    "Flask": [10.5, 9.8],
    "ASP.NET": [8.2, 7.5],
    "Svelte": [3.2, 5.1],
    "Solid.js": [0.8, 1.5],
    # AI/ML
    "TensorFlow": [12.8, 11.2],
    "PyTorch": [8.5, 12.1],
    "OpenAI API": [5.2, 9.8],
    "LangChain": [2.1, 5.5],
    "HuggingFace": [3.5, 6.2],
    "Scikit-learn": [12.1, 11.5],
    "Pandas": [15.2, 14.8],
    # 数据库
    "PostgreSQL": [36.0, 40.2],
    "MySQL": [37.5, 35.8],
    "SQLite": [31.2, 33.5],
    "MongoDB": [24.5, 22.8],
    "Redis": [17.8, 18.5],
    "Elasticsearch": [10.5, 9.2],
    "DuckDB": [0.8, 3.5],
    # 云/DevOps
    "Docker": [34.8, 36.2],
    "Kubernetes": [21.2, 22.5],
    "AWS": [44.2, 42.5],
    "Azure": [27.5, 28.2],
    "GitHub Actions": [18.5, 22.8],
    "Terraform": [12.5, 14.2],
    # 工具
    "VS Code": [73.7, 75.2],
    "Git": [93.5, 92.8],
    "Copilot": [18.2, 32.1],
    "ChatGPT": [22.5, 38.2],
    "Claude": [3.2, 12.5],
}


def classify_so_technology(name: str) -> str:
    """将 SO 技术名映射到 ONET 分类"""
    text = name.lower()
    map_to_onet = {
        "programming-language": [
            "javascript",
            "python",
            "typescript",
            "java",
            "c#",
            "c++",
            "go",
            "rust",
            "kotlin",
            "ruby",
            "php",
            "swift",
            "dart",
            "lua",
            "zig",
            "r",
            "bash",
            "shell",
            "html",
            "css",
            "sql",
        ],
        "ai-ml": [
            "tensorflow",
            "pytorch",
            "openai",
            "langchain",
            "huggingface",
            "scikit-learn",
            "pandas",
            "chatgpt",
            "claude",
            "copilot",
            "llm",
            "ml",
            "machine learning",
            "deep learning",
        ],
        "web": [
            "react",
            "vue",
            "angular",
            "svelte",
            "next.js",
            "node.js",
            "express",
            "django",
            "flask",
            "fastapi",
            "jquery",
            "solid.js",
            "spring",
            "asp.net",
        ],
        "database": [
            "postgresql",
            "mysql",
            "sqlite",
            "mongodb",
            "redis",
            "elasticsearch",
            "duckdb",
            "cassandra",
            "mariadb",
        ],
        "devops": [
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "github actions",
            "terraform",
            "ansible",
            "jenkins",
            "ci/cd",
        ],
        "testing": ["jest", "pytest", "cypress", "playwright", "selenium", "mocha", "vitest"],
        "mcp-tools": ["vscode", "copilot", "git", "chatgpt", "claude"],
    }
    for category, keywords in map_to_onet.items():
        if any(kw in text for kw in keywords):
            return category
    return "other"


# ── 技能生命周期引擎 ──


class SkillLifecycleEngine:
    """技能生命周期分析引擎

    工作原理:
        1. 定期从 OSSInsight / GitHub Search 获取技能快照
        2. 对比前后快照计算增长率
        3. 根据增长率阈值划分生命周期阶段
        4. 维护 SQLite 历史数据库
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.home() / ".pycoder" / "skills_lifecycle.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 数据库"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    stars_28d INTEGER DEFAULT 0,
                    stars_total INTEGER DEFAULT 0,
                    stars_rate REAL DEFAULT 0.0,
                    source TEXT DEFAULT '',
                    timestamp REAL NOT NULL,
                    UNIQUE(skill_id, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_skill
                    ON snapshots(skill_id);
                CREATE INDEX IF NOT EXISTS idx_snapshots_time
                    ON snapshots(timestamp);
                CREATE TABLE IF NOT EXISTS lifecycle_labels (
                    skill_id TEXT PRIMARY KEY,
                    skill_name TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    stage TEXT DEFAULT 'unknown',
                    growth_rate_28d REAL DEFAULT 0.0,
                    growth_rate_prev REAL DEFAULT 0.0,
                    momentum REAL DEFAULT 0.0,
                    weeks_on_rise INTEGER DEFAULT 0,
                    current_rank INTEGER DEFAULT 0,
                    last_updated REAL DEFAULT 0,
                    source TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS so_adoption (
                    technology TEXT PRIMARY KEY,
                    adoption_2024 REAL DEFAULT 0,
                    adoption_2025 REAL DEFAULT 0,
                    growth_rate REAL DEFAULT 0,
                    category TEXT DEFAULT ''
                );
            """)
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            log.warning("lifecycle_db_init_failed", error=str(e))

    # ── 快照管理 ──

    def save_snapshot(self, snapshot: SkillSnapshot):
        """保存技能快照"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute(
                "INSERT OR IGNORE INTO snapshots "
                "(skill_id, skill_name, category, stars_28d, stars_total, "
                " stars_rate, source, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.skill_id,
                    snapshot.skill_name,
                    snapshot.category,
                    snapshot.stars_28d,
                    snapshot.stars_total,
                    snapshot.stars_rate,
                    snapshot.source,
                    snapshot.timestamp,
                ),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            log.debug("snapshot_save_failed", skill=snapshot.skill_id, error=str(e))

    def save_snapshots_batch(self, snapshots: list[SkillSnapshot]):
        """批量保存快照"""
        now = time.time()
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.execute("BEGIN")
            for s in snapshots:
                conn.execute(
                    "INSERT OR IGNORE INTO snapshots "
                    "(skill_id, skill_name, category, stars_28d, stars_total, "
                    " stars_rate, source, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        s.skill_id,
                        s.skill_name,
                        s.category,
                        s.stars_28d,
                        s.stars_total,
                        s.stars_rate,
                        s.source,
                        s.timestamp or now,
                    ),
                )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            log.warning("snapshots_batch_save_failed", count=len(snapshots), error=str(e))

    def get_latest_snapshot(self, skill_id: str) -> SkillSnapshot | None:
        """获取技能的最新快照"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            cursor = conn.execute(
                "SELECT skill_id, skill_name, category, stars_28d, stars_total, "
                "       stars_rate, source, timestamp "
                "FROM snapshots WHERE skill_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (skill_id,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return SkillSnapshot(*row)
        except sqlite3.Error:
            pass
        return None

    def get_previous_snapshot(self, skill_id: str, before: float) -> SkillSnapshot | None:
        """获取指定时间之前的快照 (用于对比)"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            cursor = conn.execute(
                "SELECT skill_id, skill_name, category, stars_28d, stars_total, "
                "       stars_rate, source, timestamp "
                "FROM snapshots WHERE skill_id = ? AND timestamp < ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (skill_id, before),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return SkillSnapshot(*row)
        except sqlite3.Error:
            pass
        return None

    # ── 生命周期分析 ──

    @staticmethod
    def classify_stage(growth_rate_28d: float, momentum: float) -> LifecycleStage:
        """根据增长率和动量分类生命周期阶段

        Args:
            growth_rate_28d: 28天增长率 (小数)
            momentum: 当前增速 - 前一期增速

        Returns:
            LifecycleStage 枚举值
        """
        if growth_rate_28d > 0.50:
            return LifecycleStage.EMERGING
        elif growth_rate_28d > 0.20:
            return LifecycleStage.GROWING
        elif growth_rate_28d < -0.05:
            return LifecycleStage.DECLINING
        elif growth_rate_28d > 0.05:
            if momentum > 0.05:
                return LifecycleStage.GROWING
            return LifecycleStage.MATURE
        elif growth_rate_28d > -0.05:
            return LifecycleStage.STABLE
        return LifecycleStage.UNKNOWN

    def analyze_trends(
        self,
        current_items: list[dict],
        source: str = "ossinsight",
    ) -> list[SkillTrend]:
        """分析当前排名数据 → 生成技能趋势 (含生命周期标签)

        Args:
            current_items: 当前排名 [{id, name, category, stars_28d, stars_total}]
            source: 数据源标识

        Returns:
            SkillTrend 列表
        """
        now = time.time()
        trends: list[SkillTrend] = []

        # 先保存当前快照
        snapshots = []
        for item in current_items:
            stars_28d = item.get("stars_28d", 0)
            stars_total = item.get("stars_total", 0) or 1
            stars_rate = stars_28d / max(stars_total, 1)

            snapshots.append(
                SkillSnapshot(
                    skill_id=item["id"],
                    skill_name=item.get("name", ""),
                    category=item.get("category", ""),
                    stars_28d=stars_28d,
                    stars_total=stars_total,
                    stars_rate=stars_rate,
                    source=source,
                    timestamp=now,
                )
            )
        self.save_snapshots_batch(snapshots)

        # 分析趋势
        for i, item in enumerate(current_items):
            sid = item["id"]
            latest = self.get_latest_snapshot(sid)
            if not latest:
                continue

            stars_rate = latest.stars_rate

            # 获取前一次快照 (28天前)
            prev = self.get_previous_snapshot(sid, now - 28 * 86400)
            if prev:
                prev_rate = prev.stars_rate
            else:
                prev_rate = 0.0

            momentum = stars_rate - prev_rate

            # 持续上升周数 (简化: 根据历史快照粗略估算)
            weeks_on_rise = 1 if momentum > 0 else 0

            stage = self.classify_stage(stars_rate, momentum)

            trends.append(
                SkillTrend(
                    skill_id=sid,
                    skill_name=item.get("name", ""),
                    category=item.get("category", ""),
                    stage=stage,
                    stars_28d=latest.stars_28d,
                    stars_total=latest.stars_total,
                    growth_rate_28d=stars_rate,
                    growth_rate_prev=prev_rate,
                    momentum=momentum,
                    weeks_on_rise=weeks_on_rise,
                    peak_rank=None,
                    current_rank=i + 1,
                    source=source,
                )
            )

        return trends

    def save_trends(self, trends: list[SkillTrend]):
        """保存趋势分析结果到 lifecycle_labels 表"""
        now = time.time()
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.execute("BEGIN")
            for t in trends:
                conn.execute(
                    "INSERT OR REPLACE INTO lifecycle_labels "
                    "(skill_id, skill_name, category, stage, growth_rate_28d, "
                    " growth_rate_prev, momentum, weeks_on_rise, current_rank, "
                    " last_updated, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        t.skill_id,
                        t.skill_name,
                        t.category,
                        t.stage.value,
                        t.growth_rate_28d,
                        t.growth_rate_prev,
                        t.momentum,
                        t.weeks_on_rise,
                        t.current_rank,
                        now,
                        t.source,
                    ),
                )
            conn.commit()
            conn.close()
            log.info("lifecycle_trends_saved", count=len(trends))
        except sqlite3.Error as e:
            log.warning("trends_save_failed", error=str(e))

    # ── SO 数据导入 ──

    def import_so_survey(self) -> dict:
        """导入 Stack Overflow 调查数据到本地数据库

        使用内置的 SO_SURVEY_ADOPTION 数据集。
        返回导入统计。
        """
        count = 0
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.execute("BEGIN")
            for tech, (adopt_2024, adopt_2025) in SO_SURVEY_ADOPTION.items():
                growth_rate = (adopt_2025 - adopt_2024) / max(adopt_2024, 0.1)
                category = classify_so_technology(tech)
                conn.execute(
                    "INSERT OR REPLACE INTO so_adoption "
                    "(technology, adoption_2024, adoption_2025, growth_rate, category) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tech, adopt_2024, adopt_2025, round(growth_rate, 4), category),
                )
                count += 1
            conn.commit()
            conn.close()
            log.info("so_survey_imported", count=count)
            return {"success": True, "count": count}
        except sqlite3.Error as e:
            log.warning("so_survey_import_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_so_trends(self, category: str = "") -> list[dict]:
        """获取 Stack Overflow 趋势数据

        Args:
            category: 按 ONET 分类筛选

        Returns:
            趋势列表, 按增长率降序
        """
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            query = "SELECT * FROM so_adoption"
            params = []
            if category:
                query += " WHERE category = ?"
                params.append(category)
            query += " ORDER BY growth_rate DESC"
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return [
                {
                    "technology": r[0],
                    "adoption_2024": r[1],
                    "adoption_2025": r[2],
                    "growth_rate": r[3],
                    "category": r[4],
                    "stage": (
                        "emerging"
                        if r[3] > 0.3
                        else "growing" if r[3] > 0.1 else "declining" if r[3] < -0.05 else "mature"
                    ),
                }
                for r in rows
            ]
        except sqlite3.Error as e:
            log.debug("so_trends_query_failed", error=str(e))
            return []

    def get_lifecycle_by_category(self) -> dict[str, list[dict]]:
        """按分类获取生命周期分布统计"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            cursor = conn.execute(
                "SELECT category, stage, COUNT(*) as cnt "
                "FROM lifecycle_labels GROUP BY category, stage "
                "ORDER BY category, cnt DESC"
            )
            rows = cursor.fetchall()
            conn.close()
            result: dict[str, list[dict]] = {}
            for category, stage, cnt in rows:
                if category not in result:
                    result[category] = []
                result[category].append({"stage": stage, "count": cnt})
            return result
        except sqlite3.Error:
            return {}

    def get_stats(self) -> dict:
        """获取引擎统计"""
        so_count = len(SO_SURVEY_ADOPTION)
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            label_count = conn.execute("SELECT COUNT(*) FROM lifecycle_labels").fetchone()[0]
            conn.close()
        except sqlite3.Error:
            snap_count = 0
            label_count = 0
        return {
            "so_technologies": so_count,
            "snapshots": snap_count,
            "lifecycle_labels": label_count,
            "db_path": str(self._db_path),
        }


# 全局单例
_lifecycle_engine: SkillLifecycleEngine | None = None


def get_lifecycle_engine() -> SkillLifecycleEngine:
    global _lifecycle_engine
    if _lifecycle_engine is None:
        _lifecycle_engine = SkillLifecycleEngine()
    return _lifecycle_engine

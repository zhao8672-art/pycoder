"""
Pycoder 统一数据库架构 (Unified Database Schema)

设计原则:
    1. 单文件多表 — 所有模块共享 ~/.pycoder/unified.db
    2. 命名空间隔离 — 表名按模块前缀分组 (sessions_*, metrics_*, memory_*, ...)
    3. 双引擎兼容 — 同时支持 sqlite3 原生和 SQLAlchemy ORM
    4. 向后兼容 — 迁移脚本自动从旧多库合并数据
    5. WAL + FK — 生产级并发配置
    6. 可扩展 — 预留 plugin_data / app_config 通用表

数据库文件: ~/.pycoder/unified.db
环境变量: PYCODER_DB_PATH 可覆盖路径
"""

from __future__ import annotations

from pathlib import Path

# ══════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════

DB_VERSION = 2  # 数据库版本号（每次 schema 变更递增）

UNIFIED_DB_PATH = Path.home() / ".pycoder" / "unified.db"


def _get_env_db_path() -> Path:
    """读取环境变量覆盖"""
    import os

    env_path = os.environ.get("PYCODER_DB_PATH", "")
    if env_path:
        return Path(env_path)
    return UNIFIED_DB_PATH


# ══════════════════════════════════════════════════════════
# 完整 Schema — Schema SQL for sqlite3
# ══════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- ╔══════════════════════════════════════════════════════════╗
-- ║  Pycoder 统一数据库 Schema v2                         ║
-- ║  所有模块共享单文件 unified.db                        ║
-- ╚══════════════════════════════════════════════════════════╝

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;


-- ──── 元数据 ────
CREATE TABLE IF NOT EXISTS db_version (
    version     INTEGER PRIMARY KEY,
    description TEXT    DEFAULT '',
    applied_at  REAL    DEFAULT (strftime('%s','now'))
);


-- ──── 会话 + 消息 (from session_store) ────
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    created_at      REAL    DEFAULT (strftime('%s','now')),
    updated_at      REAL    DEFAULT (strftime('%s','now')),
    model           TEXT    DEFAULT 'auto',
    project_path    TEXT    DEFAULT '',
    title           TEXT    DEFAULT '',
    message_count   INTEGER DEFAULT 0,
    metadata        TEXT    DEFAULT '{}',
    task_goal       TEXT    DEFAULT '',       -- P6: 任务目标
    task_phase      TEXT    DEFAULT 'idle',   -- P6: 任务阶段
    task_progress   INTEGER DEFAULT 0        -- P6: 任务进度百分比
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    role            TEXT    NOT NULL,        -- user|assistant|system|tool
    content         TEXT    NOT NULL,
    timestamp       REAL    NOT NULL,
    metadata        TEXT    DEFAULT '{}',
    importance      REAL    DEFAULT 0.5,      -- P6: 重要性评分
    is_decision     INTEGER DEFAULT 0,        -- P6: 是否关键决策
    is_milestone    INTEGER DEFAULT 0,        -- P6: 是否里程碑
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);


-- ──── 长期记忆 (from memory_augmentor + agent_memory) ────
CREATE TABLE IF NOT EXISTS memory_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    DEFAULT '',
    project         TEXT    DEFAULT '',
    key             TEXT    NOT NULL,
    content         TEXT    DEFAULT '',
    fact_type       TEXT    DEFAULT '',        -- decision|error|file_ref|user_intent
    tags            TEXT    DEFAULT '[]',
    importance      REAL    DEFAULT 0.5,
    access_count    INTEGER DEFAULT 0,
    created_at      REAL    DEFAULT (strftime('%s','now')),
    last_accessed   REAL    DEFAULT (strftime('%s','now')),
    ttl_days        INTEGER DEFAULT 90
);

CREATE INDEX IF NOT EXISTS idx_memory_key ON memory_items(project, key);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_items(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_items(session_id);


-- ──── 进化与指标 (from knowledge_base + metrics_tracker) ────
CREATE TABLE IF NOT EXISTS evolution_error_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    error_signature TEXT UNIQUE NOT NULL,
    error_type      TEXT    DEFAULT '',
    fix_template    TEXT    DEFAULT '',
    file_pattern    TEXT    DEFAULT '',
    success_count   INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    last_seen       REAL    DEFAULT 0,
    created_at      REAL    DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS evolution_fix_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    DEFAULT '',
    error_signature TEXT    DEFAULT '',
    error_message   TEXT    DEFAULT '',
    file_path       TEXT    DEFAULT '',
    fix_content     TEXT    DEFAULT '',
    outcome         TEXT    DEFAULT '',
    test_result     TEXT    DEFAULT '',
    quality_score   REAL    DEFAULT 0,
    tokens_used     INTEGER DEFAULT 0,
    duration_ms     REAL    DEFAULT 0,
    agent_role      TEXT    DEFAULT '',
    timestamp       REAL    DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS evolution_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    DEFAULT '',
    operation       TEXT    DEFAULT '',
    outcome         TEXT    DEFAULT '',
    lines_changed   INTEGER DEFAULT 0,
    lines_added     INTEGER DEFAULT 0,
    lines_removed   INTEGER DEFAULT 0,
    bugs_found      INTEGER DEFAULT 0,
    bugs_fixed      INTEGER DEFAULT 0,
    test_passed     INTEGER DEFAULT 0,
    test_failures   INTEGER DEFAULT 0,
    quality_score   REAL    DEFAULT 0,
    tokens_used     INTEGER DEFAULT 0,
    cost_usd        REAL    DEFAULT 0,
    duration_seconds REAL   DEFAULT 0,
    rollback_count  INTEGER DEFAULT 0,
    tags            TEXT    DEFAULT '[]',
    timestamp       REAL    DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS evolution_quality_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    DEFAULT (strftime('%s','now')),
    lint_score      REAL    DEFAULT 100,
    security_score  REAL    DEFAULT 100,
    complexity_score REAL   DEFAULT 100,
    test_coverage   REAL    DEFAULT 0,
    total_score     REAL    DEFAULT 100,
    file_count      INTEGER DEFAULT 0,
    issue_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evolution_learning_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT    DEFAULT '',
    description     TEXT    DEFAULT '',
    data            TEXT    DEFAULT '{}',
    timestamp       REAL    DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_evo_ts ON evolution_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_evo_outcome ON evolution_records(outcome);
CREATE INDEX IF NOT EXISTS idx_evo_err_sig ON evolution_error_patterns(error_signature);
CREATE INDEX IF NOT EXISTS idx_evo_fix_ts ON evolution_fix_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_qual_ts ON evolution_quality_snapshots(timestamp);


-- ──── 云端用户体系 (from cloud_service) ────
CREATE TABLE IF NOT EXISTS cloud_users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT    DEFAULT '',
    password_hash   TEXT    NOT NULL,
    plan            TEXT    DEFAULT 'free',
    tokens_used_today INTEGER DEFAULT 0,
    tokens_total    INTEGER DEFAULT 0,
    requests_today  INTEGER DEFAULT 0,
    created_at      REAL    DEFAULT (strftime('%s','now')),
    last_active_at  REAL    DEFAULT (strftime('%s','now')),
    api_key_pool_id TEXT    DEFAULT '',
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cloud_api_keys (
    id              TEXT PRIMARY KEY,
    provider        TEXT    NOT NULL,
    api_key_encrypted TEXT  NOT NULL,
    tokens_used     INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    rate_limit      INTEGER DEFAULT 60,
    added_at        REAL    DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS cloud_usage_log (
    id              TEXT PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    model           TEXT    DEFAULT '',
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    tokens_total    INTEGER DEFAULT 0,
    duration_ms     REAL    DEFAULT 0,
    created_at      REAL    DEFAULT (strftime('%s','now')),
    FOREIGN KEY (user_id) REFERENCES cloud_users(id)
);


-- ──── 团队协作 (from team_workspace) ────
CREATE TABLE IF NOT EXISTS team_workspaces (
    id              TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    created_by      TEXT    DEFAULT '',
    created_at      REAL    DEFAULT (strftime('%s','now')),
    settings_json   TEXT    DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS team_members (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT    NOT NULL,
    display_name    TEXT    NOT NULL,
    role            TEXT    DEFAULT 'member',
    joined_at       REAL    DEFAULT (strftime('%s','now')),
    last_active_at  REAL    DEFAULT (strftime('%s','now')),
    FOREIGN KEY (workspace_id) REFERENCES team_workspaces(id)
);

CREATE TABLE IF NOT EXISTS team_review_requests (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    file_path       TEXT    DEFAULT '',
    code_snippet    TEXT    DEFAULT '',
    description     TEXT    DEFAULT '',
    requested_by    TEXT    DEFAULT '',
    assigned_to     TEXT    DEFAULT '[]',
    status          TEXT    DEFAULT 'open',
    created_at      REAL    DEFAULT (strftime('%s','now')),
    resolved_at     REAL,
    comments        TEXT    DEFAULT '[]',
    FOREIGN KEY (workspace_id) REFERENCES team_workspaces(id)
);

CREATE TABLE IF NOT EXISTS team_activities (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    user_name       TEXT    DEFAULT '',
    action          TEXT    NOT NULL,
    detail          TEXT    DEFAULT '',
    timestamp       REAL    DEFAULT (strftime('%s','now')),
    FOREIGN KEY (workspace_id) REFERENCES team_workspaces(id)
);


-- ──── 应用配置（键值对 flexible storage） ────
CREATE TABLE IF NOT EXISTS app_config (
    key             TEXT PRIMARY KEY,
    value           TEXT    NOT NULL,
    kind            TEXT    DEFAULT 'string',   -- string|json|int|float|bool
    description     TEXT    DEFAULT '',
    updated_at      REAL    DEFAULT (strftime('%s','now'))
);


-- ──── 通用扩展数据（Plugin/Extension 数据存储） ────
CREATE TABLE IF NOT EXISTS plugin_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id       TEXT    NOT NULL,
    key             TEXT    NOT NULL,
    value           TEXT    DEFAULT '',
    kind            TEXT    DEFAULT 'json',     -- json|blob|text
    created_at      REAL    DEFAULT (strftime('%s','now')),
    updated_at      REAL    DEFAULT (strftime('%s','now')),
    UNIQUE(plugin_id, key)
);


-- ──── 综合索引 ────
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_user ON cloud_usage_log(user_id);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_date ON cloud_usage_log(created_at);
CREATE INDEX IF NOT EXISTS idx_team_members_ws ON team_members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_team_reviews_ws ON team_review_requests(workspace_id);
CREATE INDEX IF NOT EXISTS idx_team_activities_ws ON team_activities(workspace_id);
CREATE INDEX IF NOT EXISTS idx_plugin_data_plugin ON plugin_data(plugin_id, key);
"""


# ══════════════════════════════════════════════════════════
# 表名常量（供 DAL 引用）
# ══════════════════════════════════════════════════════════


class Tables:
    """统一数据库表名常量"""

    DB_VERSION = "db_version"
    SESSIONS = "sessions"
    MESSAGES = "messages"
    MEMORY_ITEMS = "memory_items"
    EVO_ERROR_PATTERNS = "evolution_error_patterns"
    EVO_FIX_HISTORY = "evolution_fix_history"
    EVO_RECORDS = "evolution_records"
    EVO_QUALITY = "evolution_quality_snapshots"
    EVO_LEARNING = "evolution_learning_events"
    CLOUD_USERS = "cloud_users"
    CLOUD_API_KEYS = "cloud_api_keys"
    CLOUD_USAGE_LOG = "cloud_usage_log"
    TEAM_WORKSPACES = "team_workspaces"
    TEAM_MEMBERS = "team_members"
    TEAM_REVIEW = "team_review_requests"
    TEAM_ACTIVITIES = "team_activities"
    APP_CONFIG = "app_config"
    PLUGIN_DATA = "plugin_data"

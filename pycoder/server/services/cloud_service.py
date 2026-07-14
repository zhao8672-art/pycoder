"""
PyCoder Cloud — 用户注册/认证/用量追踪/API 代理

功能:
  1. 用户注册 & 登录 (JWT Token)
  2. 用量追踪 (按 Token/请求计数)
  3. API Key 代理池 (不需要用户自备 Key)
  4. 免费额度 / 套餐升级

存储: SQLite (pycoder_cloud.db)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import bcrypt

# ── 配置 ──

JWT_SECRET_KEY = os.environ.get("PYCODER_CLOUD_SECRET", "")
if not JWT_SECRET_KEY:
    import secrets as _secrets

    JWT_SECRET_KEY = _secrets.token_hex(32)
    import logging

    _logger = logging.getLogger(__name__)
    _logger.warning(
        "PYCODER_CLOUD_SECRET 未设置，使用随机临时密钥。" "请设置环境变量以保证 Token 持久化。"
    )
FREE_DAILY_TOKENS = 100_000  # 免费用户每日 Token 限额
FREE_MAX_SESSIONS = 5  # 免费用户最大会话数
TOKEN_WARNING_THRESHOLD = 0.8  # 用量 80% 时提醒
DB_PATH = Path.home() / ".pycoder" / "cloud.db"


# ── 数据模型 ──


@dataclass
class CloudUser:
    id: str
    username: str
    email: str = ""
    password_hash: str = ""
    plan: str = "free"  # free | pro | team
    tokens_used_today: int = 0
    tokens_total: int = 0
    requests_today: int = 0
    created_at: float = 0.0
    last_active_at: float = 0.0
    api_key_pool_id: str = ""
    is_active: bool = True


@dataclass
class ApiKeyPool:
    """API Key 池 — Cloud 统一管理"""

    id: str
    provider: str  # deepseek | qwen | glm
    api_key_encrypted: str
    tokens_used: int = 0
    is_active: bool = True
    rate_limit: int = 60  # RPM
    added_at: float = 0.0


# ══════════════════════════════════════════════════════════
# Cloud Service
# ══════════════════════════════════════════════════════════


class CloudService:
    """PyCoder Cloud 服务 — 单例"""

    def __init__(self):
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                plan TEXT DEFAULT 'free',
                tokens_used_today INTEGER DEFAULT 0,
                tokens_total INTEGER DEFAULT 0,
                requests_today INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s','now')),
                last_active_at REAL DEFAULT (strftime('%s','now')),
                api_key_pool_id TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                rate_limit INTEGER DEFAULT 60,
                added_at REAL DEFAULT (strftime('%s','now'))
            );
            CREATE TABLE IF NOT EXISTS usage_log (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                tokens_total INTEGER DEFAULT 0,
                duration_ms REAL DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s','now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(created_at);
        """)
        conn.commit()

    # ── Auth ──

    def register(self, username: str, password: str, email: str = "") -> dict:
        """用户注册"""
        if len(username) < 3:
            return {"success": False, "error": "用户名至少 3 个字符"}
        if len(password) < 6:
            return {"success": False, "error": "密码至少 6 个字符"}

        conn = self._get_conn()
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            return {"success": False, "error": "用户名已存在"}

        user_id = str(uuid.uuid4())[:12]
        pwd_hash = self._hash_password(password)
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, username, email, pwd_hash),
        )
        conn.commit()

        token = self._generate_token(user_id, username)
        return {
            "success": True,
            "user_id": user_id,
            "username": username,
            "token": token,
            "plan": "free",
        }

    def login(self, username: str, password: str) -> dict:
        """用户登录"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()
        if not row:
            return {"success": False, "error": "用户不存在"}

        if not self._check_password(password, row["password_hash"]):
            return {"success": False, "error": "密码错误"}

        # 更新最后活跃时间
        conn.execute(
            "UPDATE users SET last_active_at = ? WHERE id = ?",
            (time.time(), row["id"]),
        )
        conn.commit()

        token = self._generate_token(row["id"], row["username"])
        return {
            "success": True,
            "user_id": row["id"],
            "username": row["username"],
            "token": token,
            "plan": row["plan"],
            "tokens_used_today": row["tokens_used_today"],
            "tokens_total": row["tokens_total"],
        }

    def verify_token(self, token: str) -> dict:
        """验证 JWT Token"""
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return {"valid": False, "error": "格式错误"}
            payload_b64, signature = parts
            expected = hmac.new(
                JWT_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return {"valid": False, "error": "签名无效"}
            payload = json.loads(base64_decode(payload_b64))
            if payload.get("exp", 0) < time.time():
                return {"valid": False, "error": "Token 已过期"}
            return {"valid": True, "user_id": payload["uid"], "username": payload["un"]}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_user_info(self, token: str) -> dict:
        """获取用户信息"""
        verified = self.verify_token(token)
        if not verified["valid"]:
            return {"success": False, "error": verified.get("error", "Token 无效")}

        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, username, email, plan, tokens_used_today, "
            "tokens_total, requests_today, created_at FROM users WHERE id = ?",
            (verified["user_id"],),
        ).fetchone()
        if not row:
            return {"success": False, "error": "用户不存在"}
        return {"success": True, "user": dict(row)}

    # ── Usage ──

    def check_quota(self, token: str) -> dict:
        """检查用户配额"""
        verified = self.verify_token(token)
        if not verified["valid"]:
            return {"success": False, "error": "Token 无效"}

        conn = self._get_conn()
        row = conn.execute(
            "SELECT plan, tokens_used_today, tokens_total FROM users WHERE id = ?",
            (verified["user_id"],),
        ).fetchone()
        if not row:
            return {"success": False, "error": "用户不存在"}

        plan = row["plan"]
        daily_limit = (
            FREE_DAILY_TOKENS
            if plan == "free"
            else {
                "pro": 1_000_000,
                "team": 10_000_000,
            }.get(plan, FREE_DAILY_TOKENS)
        )

        used = row["tokens_used_today"]
        remaining = max(0, daily_limit - used)
        pct = round(used / daily_limit * 100, 1) if daily_limit > 0 else 0

        return {
            "success": True,
            "plan": plan,
            "daily_limit": daily_limit,
            "used_today": used,
            "remaining": remaining,
            "usage_pct": pct,
            "tokens_total": row["tokens_total"],
            "near_limit": pct >= TOKEN_WARNING_THRESHOLD * 100,
        }

    def track_usage(self, token: str, model: str, tokens_in: int, tokens_out: int) -> dict:
        """记录用量"""
        verified = self.verify_token(token)
        if not verified["valid"]:
            return {"success": False, "error": "Token 无效"}

        total = tokens_in + tokens_out
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET tokens_used_today = tokens_used_today + ?, "
            "tokens_total = tokens_total + ?, requests_today = requests_today + 1 "
            "WHERE id = ?",
            (total, total, verified["user_id"]),
        )
        conn.execute(
            "INSERT INTO usage_log (id, user_id, model, tokens_in, tokens_out, "
            "tokens_total, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4())[:12], verified["user_id"], model, tokens_in, tokens_out, total, 0),
        )
        conn.commit()
        return {"success": True}

    def get_usage_history(self, token: str, days: int = 7) -> dict:
        """获取用量历史"""
        verified = self.verify_token(token)
        if not verified["valid"]:
            return {"success": False, "error": "Token 无效"}

        cutoff = time.time() - days * 86400
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT model, tokens_total, created_at FROM usage_log "
            "WHERE user_id = ? AND created_at > ? ORDER BY created_at DESC LIMIT 100",
            (verified["user_id"], cutoff),
        ).fetchall()
        total = sum(r["tokens_total"] for r in rows)
        by_model: dict[str, int] = {}
        for r in rows:
            by_model[r["model"]] = by_model.get(r["model"], 0) + r["tokens_total"]
        return {
            "success": True,
            "total_tokens": total,
            "request_count": len(rows),
            "by_model": by_model,
            "records": [dict(r) for r in rows[:30]],
        }

    # ── Admin: API Key Pool ──

    def add_api_key(self, provider: str, api_key: str) -> dict:
        """添加 API Key 到池中"""
        kid = str(uuid.uuid4())[:8]
        encrypted = self._encrypt_key(api_key)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO api_keys (id, provider, api_key_encrypted) VALUES (?, ?, ?)",
            (kid, provider, encrypted),
        )
        conn.commit()
        return {"success": True, "key_id": kid, "provider": provider}

    def list_api_keys(self) -> list[dict]:
        """列出所有 API Key (脱敏)"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, provider, tokens_used, is_active, rate_limit, added_at "
            "FROM api_keys ORDER BY added_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Internal helpers ──

    def _generate_token(self, user_id: str, username: str) -> str:
        payload = {
            "uid": user_id,
            "un": username,
            "iat": time.time(),
            "exp": time.time() + 86400 * 30,  # 30 days
        }
        payload_b64 = base64_encode(json.dumps(payload))
        signature = hmac.new(
            JWT_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload_b64}.{signature}"

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _check_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def _encrypt_key(self, key: str) -> str:
        """简单加密 API Key (非生产级, 仅防明文存储)"""
        return base64_encode(
            hashlib.blake2b(key.encode(), key=JWT_SECRET_KEY.encode(), digest_size=32).hexdigest()
            + ":"
            + key[-4:]  # 保留后4位用于识别
        )

    def get_proxy_key(self, provider: str) -> str | None:
        """从池中获取一个可用的 API Key"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, api_key_encrypted FROM api_keys "
            "WHERE provider = ? AND is_active = 1 LIMIT 1",
            (provider,),
        ).fetchone()
        if not row:
            return None
        # Proxy 模式下不需要返回真实 key, 仅标记使用
        conn.execute(
            "UPDATE api_keys SET tokens_used = tokens_used + 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return row["id"]

    def get_plan_upgrade_info(self) -> list[dict]:
        """获取套餐信息"""
        return [
            {
                "name": "free",
                "label": "免费版",
                "price": "¥0/月",
                "daily_tokens": FREE_DAILY_TOKENS,
                "max_sessions": FREE_MAX_SESSIONS,
                "features": ["DeepSeek 模型", "5 个会话"],
            },
            {
                "name": "pro",
                "label": "专业版",
                "price": "¥30/月",
                "daily_tokens": 1_000_000,
                "max_sessions": 100,
                "features": ["所有模型", "无限会话", "Run & Fix", "测试生成"],
            },
            {
                "name": "team",
                "label": "团队版",
                "price": "¥99/月/人",
                "daily_tokens": 10_000_000,
                "max_sessions": 1000,
                "features": ["专业版全部", "团队工作区", "统一计费"],
            },
        ]

    def upgrade_plan(self, token: str, plan: str) -> dict:
        """升级套餐（模拟 — 真实需对接支付）"""
        verified = self.verify_token(token)
        if not verified["valid"]:
            return {"success": False, "error": "Token 无效"}
        valid_plans = ("free", "pro", "team")
        if plan not in valid_plans:
            return {"success": False, "error": f"无效套餐: {plan}"}
        conn = self._get_conn()
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, verified["user_id"]))
        conn.commit()
        return {"success": True, "plan": plan}


import base64  # noqa: E402

# ── Base64 helpers ──


def base64_encode(data: str) -> str:
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii")


def base64_decode(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8")


# ── Global singleton ──

_service: CloudService | None = None


def get_cloud_service() -> CloudService:
    global _service
    if _service is None:
        _service = CloudService()
    return _service

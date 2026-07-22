"""持久化用户/项目记忆引擎 — 解决 P0-2

三层记忆架构：
1. 会话级 (SessionMemory 已有) - 单次对话上下文
2. 用户级 (UserMemory) - 跨项目长期记忆（编码风格、偏好）
3. 项目级 (ProjectMemory) - 单项目长期记忆（架构决策、技术栈、约定）

特性：
- 自动持久化到 JSON 文件
- 自动敏感信息过滤（API Key、密码、token 等）
- 启动时加载 + 自动注入到 system prompt
- LLM 摘要提炼（可选）
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── 敏感信息检测 ─────────────────────────────
# 匹配 API Key、token、password 等敏感字段名
_SENSITIVE_FIELD_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|pwd|credential|access[_-]?key|private[_-]?key)",
)
# 常见密钥格式（启发式）
_SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"^sk-[A-Za-z0-9]{16,}$"),  # OpenAI / DeepSeek
    re.compile(r"^sk-ant-[A-Za-z0-9-]{16,}$"),  # Anthropic
    re.compile(r"^ghp_[A-Za-z0-9]{20,}$"),  # GitHub PAT
    re.compile(r"^xox[baprs]-[A-Za-z0-9-]{10,}$"),  # Slack
    re.compile(r"^AIza[A-Za-z0-9_-]{30,}$"),  # Google
    re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$"),  # 通用 base64 长串
]


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否属于敏感信息."""
    return bool(_SENSITIVE_FIELD_RE.search(key))


def is_sensitive_value(value: Any) -> bool:
    """判断值是否像敏感信息."""
    if not isinstance(value, str) or len(value) < 16:
        return False
    return any(pat.match(value) for pat in _SENSITIVE_VALUE_PATTERNS)


def sanitize_dict(data: dict, *, _depth: int = 0) -> dict:
    """递归过滤 dict 中的敏感信息.

    规则:
    - 键名含 api_key/secret/token/password 等 → 替换为 [REDACTED]
    - 值匹配常见密钥格式 → 替换为 [REDACTED]
    - 限制递归深度防止栈溢出
    """
    if _depth > 8:
        return {"_truncated": True}
    if not isinstance(data, dict):
        return data
    out: dict[str, Any] = {}
    for k, v in data.items():
        if is_sensitive_key(k):
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = sanitize_dict(v, _depth=_depth + 1)
        elif isinstance(v, list):
            out[k] = [
                sanitize_dict(x, _depth=_depth + 1) if isinstance(x, dict) else x
                for x in v
            ]
        elif is_sensitive_value(v):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


# ── 数据模型 ─────────────────────────────


@dataclass
class UserMemory:
    """用户级记忆 — 跨项目持久化."""

    user_id: str = "default"
    created_at: str = ""
    updated_at: str = ""

    # 编码偏好
    preferred_language: str = ""  # 主要编程语言 (e.g., "python", "typescript")
    code_style: dict = field(default_factory=dict)  # 缩进、引号、行长度等
    preferred_frameworks: list[str] = field(default_factory=list)  # 偏好框架
    testing_framework: str = ""  # 测试框架 (pytest/unittest/jest)

    # 行为偏好
    communication_style: str = ""  # 简洁/详细/技术/通俗
    response_language: str = "zh"  # 默认中文
    detail_level: str = "normal"  # brief/normal/verbose

    # 统计
    total_sessions: int = 0
    total_messages: int = 0
    most_used_models: list[str] = field(default_factory=list)

    # 自由键值对（用户可自定义）
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UserMemory":
        # 过滤敏感字段
        clean = sanitize_dict(data)
        # 仅保留已知字段，其余放入 custom
        known_fields = {f for f in cls.__dataclass_fields__}
        custom = {k: v for k, v in clean.items() if k not in known_fields}
        clean_main = {k: v for k, v in clean.items() if k in known_fields}
        clean_main["custom"] = custom
        return cls(**clean_main)


@dataclass
class ProjectMemory:
    """项目级记忆 — 单项目持久化."""

    project_name: str = ""
    project_root: str = ""
    created_at: str = ""
    updated_at: str = ""

    # 技术栈
    primary_language: str = ""
    frameworks: list[str] = field(default_factory=list)
    package_manager: str = ""  # pip / npm / cargo
    python_version: str = ""

    # 架构决策记录 (ADR)
    architecture_decisions: list[dict] = field(default_factory=list)
    # 已知约束
    constraints: list[str] = field(default_factory=list)
    # 常用命令（项目级）
    common_commands: list[str] = field(default_factory=list)
    # 已发现的项目约定
    conventions: list[str] = field(default_factory=list)
    # TODO/技术债务
    tech_debt: list[str] = field(default_factory=list)

    # 重要文件路径
    key_files: list[str] = field(default_factory=list)
    # 最近修改的模块
    recent_modules: list[str] = field(default_factory=list)

    # 自由键值对
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMemory":
        clean = sanitize_dict(data)
        known_fields = {f for f in cls.__dataclass_fields__}
        custom = {k: v for k, v in clean.items() if k not in known_fields}
        clean_main = {k: v for k, v in clean.items() if k in known_fields}
        clean_main["custom"] = custom
        return cls(**clean_main)


# ── 记忆引擎 ─────────────────────────────


class PersistentMemoryEngine:
    """持久化记忆引擎 — 管理用户/项目级记忆.

    存储位置：
    - 用户记忆: ~/.pycoder/user_profile.json
    - 项目记忆: <project_root>/.pycoder/project_memory.json

    用法:
        engine = PersistentMemoryEngine()
        await engine.load()
        user = engine.get_user_memory()
        engine.update_user(language="python", test_framework="pytest")
        await engine.save_user()
    """

    def __init__(self, user_id: str = "default", project_root: Path | None = None) -> None:
        self._user_id = user_id
        self._project_root = project_root
        self._user_dir = Path.home() / ".pycoder"
        self._user_path = self._user_dir / "user_profile.json"
        self._project_path = (
            project_root / ".pycoder" / "project_memory.json" if project_root else None
        )
        self._user_memory: UserMemory | None = None
        self._project_memory: ProjectMemory | None = None
        self._lock = threading.RLock()

    # ── 加载 ──
    def load(self) -> None:
        """从磁盘加载所有记忆."""
        with self._lock:
            self._user_memory = self._load_user()
            self._project_memory = self._load_project()

    def _load_user(self) -> UserMemory:
        if not self._user_path.is_file():
            logger.info("user_memory_not_found, creating default")
            return UserMemory(
                user_id=self._user_id,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
        try:
            data = json.loads(self._user_path.read_text(encoding="utf-8"))
            return UserMemory.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            logger.warning("user_memory_load_failed: %s, using default", e)
            return UserMemory(user_id=self._user_id)

    def _load_project(self) -> ProjectMemory | None:
        if not self._project_path:
            return None
        if not self._project_path.is_file():
            logger.info("project_memory_not_found, creating default")
            return ProjectMemory(
                project_root=str(self._project_root),
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
        try:
            data = json.loads(self._project_path.read_text(encoding="utf-8"))
            return ProjectMemory.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            logger.warning("project_memory_load_failed: %s, using default", e)
            return ProjectMemory(project_root=str(self._project_root))

    # ── 保存 ──
    def save_user(self) -> bool:
        """保存用户记忆."""
        if not self._user_memory:
            return False
        with self._lock:
            try:
                self._user_dir.mkdir(parents=True, exist_ok=True)
                self._user_memory.updated_at = datetime.now().isoformat()
                data = sanitize_dict(self._user_memory.to_dict())
                self._user_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
            except OSError as e:
                logger.error("user_memory_save_failed: %s", e)
                return False

    def save_project(self) -> bool:
        """保存项目记忆."""
        if not self._project_memory or not self._project_path:
            return False
        with self._lock:
            try:
                self._project_path.parent.mkdir(parents=True, exist_ok=True)
                self._project_memory.updated_at = datetime.now().isoformat()
                data = sanitize_dict(self._project_memory.to_dict())
                self._project_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
            except OSError as e:
                logger.error("project_memory_save_failed: %s", e)
                return False

    def save_all(self) -> dict[str, bool]:
        """保存全部记忆."""
        return {
            "user": self.save_user(),
            "project": self.save_project(),
        }

    # ── 访问 ──
    def get_user_memory(self) -> UserMemory:
        if self._user_memory is None:
            self._user_memory = self._load_user()
        return self._user_memory

    def get_project_memory(self) -> ProjectMemory | None:
        if self._project_path is None:
            return None
        if self._project_memory is None:
            self._project_memory = self._load_project()
        return self._project_memory

    # ── 更新 ──
    def update_user(self, **fields: Any) -> UserMemory:
        """更新用户记忆字段."""
        with self._lock:
            mem = self.get_user_memory()
            clean = sanitize_dict(fields)
            for k, v in clean.items():
                if k == "custom" and isinstance(v, dict):
                    mem.custom.update(v)
                elif hasattr(mem, k):
                    setattr(mem, k, v)
                else:
                    mem.custom[k] = v
            mem.updated_at = datetime.now().isoformat()
            return mem

    def update_project(self, **fields: Any) -> ProjectMemory | None:
        """更新项目记忆字段."""
        if not self._project_path:
            return None
        with self._lock:
            mem = self.get_project_memory()
            if not mem:
                return None
            clean = sanitize_dict(fields)
            for k, v in clean.items():
                if k == "custom" and isinstance(v, dict):
                    mem.custom.update(v)
                elif hasattr(mem, k):
                    setattr(mem, k, v)
                else:
                    mem.custom[k] = v
            mem.updated_at = datetime.now().isoformat()
            return mem

    # ── 上下文注入 ──
    def build_context_prompt(self) -> str:
        """生成注入到 system prompt 的记忆上下文."""
        lines: list[str] = ["## 持久化记忆（自动加载）"]
        user = self.get_user_memory()
        if user:
            lines.append("### 用户偏好")
            if user.preferred_language:
                lines.append(f"- 主要语言: {user.preferred_language}")
            if user.testing_framework:
                lines.append(f"- 测试框架: {user.testing_framework}")
            if user.preferred_frameworks:
                lines.append(f"- 偏好框架: {', '.join(user.preferred_frameworks)}")
            if user.communication_style:
                lines.append(f"- 沟通风格: {user.communication_style}")
            if user.detail_level != "normal":
                lines.append(f"- 详细程度: {user.detail_level}")
            if user.code_style:
                style = ", ".join(f"{k}={v}" for k, v in user.code_style.items())
                lines.append(f"- 代码风格: {style}")

        proj = self.get_project_memory()
        if proj:
            lines.append("### 项目记忆")
            if proj.primary_language:
                lines.append(f"- 主语言: {proj.primary_language}")
            if proj.frameworks:
                lines.append(f"- 框架: {', '.join(proj.frameworks)}")
            if proj.package_manager:
                lines.append(f"- 包管理器: {proj.package_manager}")
            if proj.python_version:
                lines.append(f"- Python 版本: {proj.python_version}")
            if proj.constraints:
                lines.append("- 约束:")
                for c in proj.constraints[:5]:
                    lines.append(f"  - {c}")
            if proj.architecture_decisions:
                lines.append("- 关键架构决策:")
                for ad in proj.architecture_decisions[:3]:
                    lines.append(f"  - {ad.get('title', '')}: {ad.get('decision', '')}")
            if proj.conventions:
                lines.append("- 项目约定:")
                for c in proj.conventions[:3]:
                    lines.append(f"  - {c}")
        return "\n".join(lines) if len(lines) > 1 else ""


# ── 全局单例 ──
_engine: PersistentMemoryEngine | None = None
_engine_lock = threading.Lock()


def get_persistent_memory(project_root: Path | None = None) -> PersistentMemoryEngine:
    """获取持久化记忆引擎全局单例."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = PersistentMemoryEngine(project_root=project_root)
            _engine.load()
        return _engine


__all__ = [
    "PersistentMemoryEngine",
    "ProjectMemory",
    "UserMemory",
    "get_persistent_memory",
    "is_sensitive_key",
    "is_sensitive_value",
    "sanitize_dict",
]

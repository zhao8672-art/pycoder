"""
前缀缓存与增量进化引擎 — Phase 1: 算法效率优化

职责:
    1. AST 扫描结果缓存 — 文件未变化时跳过重复扫描
    2. 热规则优先级调度 — 高频使用的修复规则优先加载
    3. 增量差异化扫描 — 只扫描上次扫描后有变化的文件
    4. LRU 淘汰 + 文件指纹快速鉴别

目标:
    自进化延迟: 1420ms → <400ms
    重复计算削减: 70%+

用法:
    from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache
    cache = EvoCache()
    cache.mark_scanned("pycoder/server/app.py", "hash123")
    if cache.is_cached("pycoder/server/app.py", "hash123"):
        return cache.get_cached_issues("pycoder/server/app.py")
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path.home() / ".pycoder" / "evo_cache"
MAX_CACHE_SIZE = 500  # 最多缓存 500 个文件
MAX_HOT_RULES = 100  # 最多保留 100 条热规则
CACHE_TTL_SECONDS = 3600  # 缓存有效期 1h


@dataclass
class CachedScan:
    """文件扫描缓存条目"""

    file_path: str
    content_hash: str  # SHA256 前 12 位
    issues_found: int
    issues_json: str  # JSON 序列化的 CodeIssue 列表
    scanned_at: float  # 扫描时间戳
    line_count: int = 0


@dataclass
class HotRule:
    """热规则 — 高频使用的修复规则"""

    rule_id: str
    error_signature: str
    fix_template: str
    success_rate: float  # 成功率 0-1
    use_count: int
    last_used: float
    priority: float = 0.0  # 综合优先级(越大越优先)


class EvoCache:
    """前缀缓存与增量进化管理器

    LRU 缓存 + 热规则优先级调度 + 文件指纹差异化扫描
    """

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._scans: OrderedDict[str, CachedScan] = OrderedDict()
        self._hot_rules: list[HotRule] = []
        self._file_timestamps: dict[str, float] = {}
        self._load_persisted()

    # ══════════════════════════════════════════════════════
    # 文件缓存
    # ══════════════════════════════════════════════════════

    @staticmethod
    def compute_hash(file_path: str | Path) -> str:
        """计算文件内容哈希（SHA256 前 12 位）"""
        try:
            content = Path(file_path).read_bytes()
            return hashlib.sha256(content).hexdigest()[:12]
        except (OSError, PermissionError):
            return ""

    def is_cached(self, file_path: str, content_hash: str = "") -> bool:
        """检查文件是否在缓存中且未变化"""
        cached = self._scans.get(file_path)
        if cached is None:
            return False
        if time.time() - cached.scanned_at > CACHE_TTL_SECONDS:
            return False
        if content_hash and cached.content_hash != content_hash:
            return False
        return True

    def get_cached_issues(self, file_path: str) -> list[dict]:
        """从缓存获取上次扫描发现的问题"""
        cached = self._scans.get(file_path)
        if cached is None:
            return []
        try:
            return json.loads(cached.issues_json)
        except (json.JSONDecodeError, TypeError):
            return []

    def mark_scanned(self, file_path: str, content_hash: str, issues: list = None) -> None:
        """标记文件已扫描并缓存结果"""
        if file_path in self._scans:
            del self._scans[file_path]

        # LRU 淘汰
        while len(self._scans) >= MAX_CACHE_SIZE:
            oldest = next(iter(self._scans))
            del self._scans[oldest]

        self._scans[file_path] = CachedScan(
            file_path=file_path,
            content_hash=content_hash,
            issues_found=len(issues) if issues else 0,
            issues_json=json.dumps(issues or [], ensure_ascii=False),
            scanned_at=time.time(),
        )
        self._file_timestamps[file_path] = time.time()

    # ══════════════════════════════════════════════════════
    # 增量扫描
    # ══════════════════════════════════════════════════════

    def get_changed_files(self, target_dir: str, extension: str = ".py") -> list[str]:
        """获取自上次扫描后有变化的文件列表

        Returns:
            变化的文件路径列表，新文件也计入
        """
        changed: list[str] = []
        target = Path(target_dir)

        for f in target.rglob(f"*{extension}"):
            fpath = str(f)
            if self._is_skippable(f):
                continue

            current_hash = self.compute_hash(fpath)
            if not current_hash:
                continue

            cached = self._scans.get(fpath)
            if cached is None:
                changed.append(fpath)  # 新文件
            elif cached.content_hash != current_hash:
                changed.append(fpath)  # 内容变化
            elif time.time() - cached.scanned_at > CACHE_TTL_SECONDS:
                changed.append(fpath)  # 缓存过期

        return changed

    @staticmethod
    def _is_skippable(file_path: Path) -> bool:
        skip_parts = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pycoder_snapshots"}
        return any(p in skip_parts for p in file_path.parts)

    # ══════════════════════════════════════════════════════
    # 热规则管理
    # ══════════════════════════════════════════════════════

    def register_hot_rule(
        self,
        error_signature: str,
        fix_template: str,
        success_rate: float = 1.0,
    ) -> None:
        """注册/更新热规则"""
        for rule in self._hot_rules:
            if rule.error_signature == error_signature:
                rule.use_count += 1
                rule.last_used = time.time()
                rule.success_rate = rule.success_rate * 0.8 + success_rate * 0.2  # 指数移动平均
                rule.priority = self._calc_priority(rule)
                return

        # 新规则
        rule = HotRule(
            rule_id=f"HR-{int(time.time() * 1000) % 100000:05d}",
            error_signature=error_signature,
            fix_template=fix_template,
            success_rate=success_rate,
            use_count=1,
            last_used=time.time(),
        )
        rule.priority = self._calc_priority(rule)
        self._hot_rules.append(rule)

        # 淘汰低优先级规则
        while len(self._hot_rules) > MAX_HOT_RULES:
            self._hot_rules.sort(key=lambda r: r.priority)
            self._hot_rules.pop(0)

    def get_top_rules(self, limit: int = 10) -> list[HotRule]:
        """获取优先级最高的热规则"""
        # 按优先级降序
        self._hot_rules.sort(key=lambda r: r.priority, reverse=True)
        return self._hot_rules[:limit]

    def find_rule(self, error_signature: str) -> HotRule | None:
        """根据错误签名查找匹配的热规则"""
        for rule in self._hot_rules:
            if rule.error_signature == error_signature:
                return rule
        # 模糊匹配
        sig_lower = error_signature.lower()
        for rule in self._hot_rules:
            if (
                rule.error_signature.lower() in sig_lower
                or sig_lower in rule.error_signature.lower()
            ):
                return rule
        return None

    @staticmethod
    def _calc_priority(rule: HotRule) -> float:
        """综合优先级 = 成功率*0.5 + 使用频率*0.3 + 时效性*0.2"""
        recency = max(0, 1.0 - (time.time() - rule.last_used) / 86400)  # 24h 内
        frequency = min(rule.use_count / 50, 1.0)  # 50 次封顶
        return rule.success_rate * 0.5 + frequency * 0.3 + recency * 0.2

    # ══════════════════════════════════════════════════════
    # 持久化
    # ══════════════════════════════════════════════════════

    _CACHE_FILE = "evo_cache.json"

    def _load_persisted(self) -> None:
        cache_file = CACHE_DIR / self._CACHE_FILE
        if not cache_file.exists():
            return
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for item in data.get("hot_rules", [])[-MAX_HOT_RULES:]:
                rule = HotRule(**item)
                self._hot_rules.append(rule)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    def save(self) -> None:
        cache_file = CACHE_DIR / self._CACHE_FILE
        data = {
            "hot_rules": [
                {
                    "rule_id": r.rule_id,
                    "error_signature": r.error_signature,
                    "fix_template": r.fix_template,
                    "success_rate": r.success_rate,
                    "use_count": r.use_count,
                    "last_used": r.last_used,
                    "priority": r.priority,
                }
                for r in self._hot_rules
            ],
            "saved_at": time.time(),
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_stats(self) -> dict:
        return {
            "cached_files": len(self._scans),
            "hot_rules": len(self._hot_rules),
            "top_rule_priority": (
                max(r.priority for r in self._hot_rules) if self._hot_rules else 0
            ),
        }

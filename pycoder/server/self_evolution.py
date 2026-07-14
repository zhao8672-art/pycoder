"""
自我进化引擎 — 向后兼容重导出

已迁移至 V2 能力模块: pycoder.capabilities.self_evo.engine
此文件保留 V1 特有方法（备份/恢复/清单管理）以保持向后兼容。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from pycoder.capabilities.self_evo.engine import (  # noqa: F401
    CodeIssue,
    EvolutionRecord,
    EvolutionStats,
    EvolutionTask,
    FixProposal,
    FixResult,
    ScanReport,
    SelfEvolutionEngine as _V2SelfEvolutionEngine,
)

# 从 V2 引擎继承常量
EVOLUTION_TOKEN_DIR = _V2SelfEvolutionEngine._EVOLUTION_TOKEN_DIR
EVOLUTION_TOKEN_FILE = _V2SelfEvolutionEngine._EVOLUTION_TOKEN_FILE
EVOLUTION_TOKEN_TTL = _V2SelfEvolutionEngine._EVOLUTION_TOKEN_TTL
CORE_FILE_PATTERNS = ["self_evolution.py", "self_evolution", "evolution.py", "self_optimizer.py"]
GITHUB_TOKEN_FILE = Path.home() / ".pycoder" / "github_token"
SELF_EVOLVE_SYSTEM_PROMPT = _V2SelfEvolutionEngine.SELF_EVOLVE_SYSTEM_PROMPT


class EvolutionReport:
    """进化报告（V1 兼容）"""

    def __init__(self):
        self.total_issues: int = 0
        self.fixes: list[dict] = []
        self.tests_passed: bool = False
        self.duration_seconds: float = 0.0


class SelfEvolutionEngine(_V2SelfEvolutionEngine):
    """
    V1 兼容的 SelfEvolutionEngine — 继承 V2 引擎并添加 V1 特有方法。

    V1 特有方法:
    - _git_stash_backup / _git_stash_pop / _fallback_restore_all_evobak
    - _cleanup_evobak_files
    - _load_backup_manifest / _save_backup_manifest
    - _compute_project_hash
    - _check_git_changes
    - _static_scan_async
    - _record_learning (V1 签名)
    - _watch_loop
    - start_watcher / stop_watcher / get_watch_status
    - list_tasks / get_task (V1 签名)
    """

    def __init__(self, v2_engine=None, llm_provider=None, project_root=None):
        super().__init__(v2_engine, llm_provider, project_root)
        self._watch_active = False
        self._watch_interval = 300
        self._last_watch_hash = ""
        self._watch_task = None

    # ══════════════════════════════════════════════════════
    # V1 备份/恢复系统（.evobak + 清单）
    # ══════════════════════════════════════════════════════

    def _git_stash_backup(self) -> str:
        """创建 .evobak 备份并记录到清单"""
        backup_id = hashlib.sha256(
            f"{time.time()}:{uuid.uuid4()}".encode()
        ).hexdigest()[:12]
        pycoder_dir = self._project_root / "pycoder"
        backed_up: list[str] = []

        if pycoder_dir.exists():
            for py_file in pycoder_dir.rglob("*.py"):
                if "__pycache__" in str(py_file):
                    continue
                bak = py_file.with_suffix(py_file.suffix + ".evobak")
                try:
                    bak.write_text(py_file.read_text(encoding="utf-8"), encoding="utf-8")
                    backed_up.append(str(py_file.relative_to(self._project_root)))
                except (OSError, UnicodeDecodeError):
                    pass

        manifest = self._load_backup_manifest()
        manifest["backups"].append({
            "id": backup_id,
            "files": backed_up,
            "timestamp": time.time(),
        })
        self._save_backup_manifest(manifest)
        return backup_id

    def _git_stash_pop(self, backup_id: str) -> bool:
        """从 .evobak 恢复文件"""
        manifest = self._load_backup_manifest()
        target = None
        for b in manifest["backups"]:
            if b["id"] == backup_id:
                target = b
                break
        if target is None:
            return self._fallback_restore_all_evobak()

        for fpath in target["files"]:
            src = self._project_root / fpath
            bak = src.with_suffix(src.suffix + ".evobak")
            if bak.exists():
                try:
                    src.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
                    bak.unlink(missing_ok=True)
                except (OSError, UnicodeDecodeError):
                    pass
        return True

    def _fallback_restore_all_evobak(self) -> bool:
        """降级恢复：遍历所有 .evobak 文件恢复"""
        pycoder_dir = self._project_root / "pycoder"
        if not pycoder_dir.exists():
            return False
        found = False
        for bak in pycoder_dir.rglob("*.evobak"):
            original = bak.with_suffix("")
            try:
                original.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
                bak.unlink(missing_ok=True)
                found = True
            except (OSError, UnicodeDecodeError):
                pass
        return found

    def _cleanup_evobak_files(self) -> int:
        """清理所有 .evobak 残留文件"""
        pycoder_dir = self._project_root / "pycoder"
        if not pycoder_dir.exists():
            return 0
        count = 0
        for bak in pycoder_dir.rglob("*.evobak"):
            try:
                bak.unlink(missing_ok=True)
                count += 1
            except OSError:
                pass
        return count

    def _load_backup_manifest(self) -> dict:
        """加载备份清单"""
        manifest_path = self._project_root / ".evo_backups.json"
        if not manifest_path.exists():
            return {"backups": []}
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "backups" in data:
                # 保留策略：最多 5 个
                data["backups"] = data["backups"][-5:]
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return {"backups": []}

    def _save_backup_manifest(self, data: dict) -> None:
        """保存备份清单"""
        manifest_path = self._project_root / ".evo_backups.json"
        try:
            manifest_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ══════════════════════════════════════════════════════
    # V1 项目哈希
    # ══════════════════════════════════════════════════════

    def _compute_project_hash(self) -> str:
        """计算项目文件哈希"""
        pycoder_dir = self._project_root / "pycoder"
        if not pycoder_dir.exists():
            return hashlib.sha256(b"empty").hexdigest()
        hasher = hashlib.sha256()
        for py_file in sorted(pycoder_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            try:
                hasher.update(py_file.read_bytes())
            except (OSError, UnicodeDecodeError):
                pass
        return hasher.hexdigest()

    # ══════════════════════════════════════════════════════
    # V1 Git 变更检测
    # ══════════════════════════════════════════════════════

    def _check_git_changes(self) -> list[str]:
        """检测 Git 变更"""
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                return [line.strip() for line in r.stdout.split("\n") if line.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return []

    # ══════════════════════════════════════════════════════
    # V1 静态扫描
    # ══════════════════════════════════════════════════════

    async def _static_scan_async(self) -> list[dict]:
        """异步静态分析（ruff 优先）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff", "check", "--output-format", "json",
                str(self._project_root / "pycoder"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                return []
            if proc.returncode == 0 and stdout:
                data = json.loads(stdout.decode("utf-8", errors="replace"))
                return [
                    {
                        "source": "ruff",
                        "file": item.get("filename", ""),
                        "line": item.get("location", {}).get("row", 0),
                        "message": item.get("message", ""),
                    }
                    for item in data
                ]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return []

    # ══════════════════════════════════════════════════════
    # V1 学习记录
    # ══════════════════════════════════════════════════════

    def _record_learning(
        self,
        task,
        fixes: list[dict],
        test_passed: bool,
        error_msg: str = "",
        quality_score: float = 0,
    ) -> None:
        """记录学习经验（V1 签名）"""
        try:
            from pycoder.capabilities.self_evo.learning import get_learning_engine

            engine = get_learning_engine()
            engine.on_task_complete(
                task_id=task.id if hasattr(task, "id") else str(uuid.uuid4())[:8],
                outcome="success" if test_passed else "failure",
                task_type=task.type if hasattr(task, "type") else "fix",
                description=task.description if hasattr(task, "description") else "",
                error_msg=error_msg,
                file_paths=[f.get("file", "") for f in fixes],
                fix_content="\n".join(f.get("modified", "")[:500] for f in fixes),
                test_passed=test_passed,
                quality_score=quality_score,
            )
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            import logging
            logging.getLogger(__name__).debug("record_learning_failed: %s", e)

    # ══════════════════════════════════════════════════════
    # V1 监控
    # ══════════════════════════════════════════════════════

    @property
    def watch_active(self) -> bool:
        return self._watch_active

    def start_watcher(self, interval: int = 300) -> dict:
        if self._watch_active:
            return {"success": True, "message": "自动监控已在运行", "interval": self._watch_interval}
        self._watch_interval = max(interval, 60)
        self._watch_active = True
        self._last_watch_hash = self._compute_project_hash()
        return {"success": True, "message": "已启动自动监控", "interval": self._watch_interval}

    def stop_watcher(self) -> dict:
        if not self._watch_active:
            return {"success": True, "message": "监控未在运行"}
        self._watch_active = False
        return {"success": True, "message": "已停止自动监控"}

    def get_watch_status(self) -> dict:
        return {
            "active": self._watch_active,
            "interval": self._watch_interval,
        }

    async def _watch_loop(self) -> None:
        """后台监控循环"""
        import logging
        log = logging.getLogger(__name__)
        while self._watch_active:
            try:
                await asyncio.sleep(self._watch_interval)
                current_hash = self._compute_project_hash()
                if current_hash != self._last_watch_hash:
                    self._last_watch_hash = current_hash
                    self._stats.last_run = time.time()
                    changes = self._check_git_changes()
                    if changes:
                        log.info("watch_changes_detected count=%d", len(changes))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("watch_loop_error: %s", e)

    # ══════════════════════════════════════════════════════
    # V1 公共 API
    # ══════════════════════════════════════════════════════

    def get_stats(self) -> dict[str, Any]:
        """获取进化统计（V1 兼容 — 返回 EvolutionStats.to_dict()）"""
        return self._stats.to_dict()

    def list_tasks(self, limit: int = 20) -> list[dict]:
        return [
            t.to_dict() for t in self._tasks[-limit:]
        ] if hasattr(self, "_tasks") else super().list_tasks(limit=limit)

    def get_task(self, task_id: str) -> dict | None:
        if hasattr(self, "_tasks"):
            for t in self._tasks:
                if t.id == task_id:
                    return t.to_dict()
        return super().get_task(task_id) if hasattr(super(), "get_task") else None


# ══════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════

_engine: SelfEvolutionEngine | None = None


def get_evolution_engine() -> SelfEvolutionEngine:
    global _engine
    if _engine is None:
        _engine = SelfEvolutionEngine()
    return _engine
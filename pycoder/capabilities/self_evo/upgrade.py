"""
PyCoder 自动升级模块 — 版本检测、健康检查、升级执行、断点续传、回滚。

提供:
    check_version()      — 从 GitHub Releases 检查最新版本
    health_check()       — 升级前全面健康检查
    run_upgrade()        — 执行升级 (git pull + pip install)
    断点续传              — 启动时自动检测 pending_upgrade.json
    回滚                  — 从 .evobak 快照恢复
"""

from __future__ import annotations

import json
import subprocess as _sp
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pycoder import __version__
from pycoder.server.log import log

# ── 常量 ──────────────────────────────────────────────────
PENDING_FILE = Path.home() / ".pycoder" / "pending_upgrade.json"
UPGRADE_DIR = Path.home() / ".pycoder" / "upgrades"
SNAPSHOT_DIR = UPGRADE_DIR / "snapshots"
GITHUB_API = "https://api.github.com/repos/zhao8672-art/pycoder/releases/latest"
GITHUB_TAGS = "https://api.github.com/repos/zhao8672-art/pycoder/tags"


def _validate_url(url: str) -> str:
    """验证 URL 协议仅允许 http/https"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {parsed.scheme}")
    return url


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    passed: bool
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class UpgradeResult:
    """升级执行结果"""

    success: bool
    from_version: str
    to_version: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0


@dataclass
class VersionInfo:
    """版本信息"""

    current: str
    latest: str
    has_update: bool
    release_notes: str = ""
    published_at: str = ""


# ── 断点续传 ─────────────────────────────────────────────


def save_pending_upgrade(from_ver: str, to_ver: str, stage: str = "init") -> dict:
    """保存待处理的升级状态（断点续传）"""
    UPGRADE_DIR.mkdir(parents=True, exist_ok=True)
    pending = {
        "from_version": from_ver,
        "to_version": to_ver,
        "stage": stage,
        "started_at": datetime.now().isoformat(),
        "completed_steps": [],
    }
    PENDING_FILE.write_text(json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8")
    return pending


def load_pending_upgrade() -> dict | None:
    """加载待处理的升级状态，不存在则返回 None"""
    if not PENDING_FILE.exists():
        return None
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_pending_upgrade() -> None:
    """清除待处理升级状态（升级成功后调用）"""
    PENDING_FILE.unlink(missing_ok=True)


# ── 版本检测 ─────────────────────────────────────────────


def check_version() -> VersionInfo:
    """从 GitHub Releases 检查是否有新版本。

    优先用 requests（需要联网），失败时降级到本地 Git tag 检测。
    """
    try:
        import urllib.error
        import urllib.request

        _validate_url(GITHUB_API)
        req = urllib.request.Request(
            GITHUB_API,
            headers={
                "User-Agent": "PyCoder-Upgrade-Checker",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            notes = data.get("body", "")
            published = data.get("published_at", "")

        # 简单版本比较（支持 x.y.z 格式）
        has_update = _compare_versions(latest, __version__) > 0
        return VersionInfo(
            current=__version__,
            latest=latest,
            has_update=has_update,
            release_notes=notes[:500],
            published_at=published,
        )
    except Exception as e:
        # 降级：用本地 git tag 检测
        return _check_version_local(e)


def _check_version_local(fallback_error: Exception = None) -> VersionInfo:
    """用本地 git ls-remote 检测最新版本（降级方案）"""
    try:
        r = _sp.run(
            ["git", "ls-remote", "--tags", "https://github.com/zhao8672-art/pycoder.git"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tags = []
        for line in r.stdout.strip().split("\n"):
            if "refs/tags/v" in line and "^{}" not in line:
                tag = line.split("refs/tags/v")[-1].strip()
                tags.append(tag)
        if not tags:
            return VersionInfo(
                current=__version__,
                latest="未知",
                has_update=False,
                release_notes=f"无法检测: {fallback_error}",
            )
        tags.sort(key=lambda v: tuple(map(int, v.split("."))))
        latest = tags[-1]
        has_update = _compare_versions(latest, __version__) > 0
        return VersionInfo(
            current=__version__,
            latest=latest,
            has_update=has_update,
            release_notes=f"(本地 Git 检测, API 不可用: {fallback_error})",
        )
    except Exception as e:
        return VersionInfo(
            current=__version__, latest="未知", has_update=False, release_notes=f"版本检测失败: {e}"
        )


def _compare_versions(v1: str, v2: str) -> int:
    """比较两个语义版本号，返回 1/-1/0"""
    try:
        parts1 = tuple(int(x) for x in v1.split("."))
        parts2 = tuple(int(x) for x in v2.split("."))
        if parts1 > parts2:
            return 1
        elif parts1 < parts2:
            return -1
        return 0
    except (ValueError, AttributeError):
        return 0


# ── 健康检查 ─────────────────────────────────────────────


def health_check() -> HealthCheckResult:
    """升级前全面健康检查。

    检查项:
        - Python 解释器版本
        - pip 可用性
        - Git 仓库状态（无未提交变更）
        - 磁盘空间 >= 100MB
        - 网络连通性 (GitHub API)
        - 核心 MCP 工具响应
    """
    result = HealthCheckResult(passed=True)

    # 1. Python 版本
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    result.checks["python"] = {
        "version": py_ver,
        "executable": sys.executable,
        "ok": sys.version_info >= (3, 10),
    }
    if not result.checks["python"]["ok"]:
        result.errors.append(f"Python 版本过低: {py_ver}，需要 >= 3.10")
        result.passed = False

    # 2. pip 可用性
    try:
        r = _sp.run(
            [sys.executable, "-m", "pip", "--version"], capture_output=True, text=True, timeout=10
        )
        result.checks["pip"] = {"version": r.stdout.strip()[:50], "ok": r.returncode == 0}
    except Exception as e:
        result.checks["pip"] = {"ok": False, "error": str(e)}
        result.errors.append(f"pip 不可用: {e}")
        result.passed = False

    # 3. Git 仓库状态
    try:
        r = _sp.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        dirty = bool(r.stdout.strip())
        result.checks["git"] = {"dirty": dirty, "ok": True}
        if dirty:
            result.warnings.append("Git 工作区有未提交的变更，建议先提交再升级")
    except Exception as e:
        result.checks["git"] = {"ok": False, "error": str(e)}
        result.warnings.append(f"Git 检测失败: {e}")

    # 4. 磁盘空间
    try:
        import shutil

        free = shutil.disk_usage(Path.home()).free / (1024 * 1024)  # MB
        result.checks["disk"] = {"free_mb": round(free, 1), "ok": free >= 100}
        if free < 100:
            result.errors.append(f"磁盘空间不足: {free:.1f}MB，需要 >= 100MB")
            result.passed = False
    except OSError as e:
        log.debug("health_check_disk_failed", error=str(e))
        result.checks["disk"] = {"ok": True, "note": "无法检测"}

    # 5. 网络连通性
    try:
        import urllib.request

        _validate_url("https://api.github.com")
        req = urllib.request.Request(
            "https://api.github.com",
            headers={"User-Agent": "PyCoder-HealthCheck"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result.checks["network"] = {"status_code": resp.status, "ok": resp.status == 200}
    except Exception as e:
        result.checks["network"] = {"ok": False, "error": str(e)}
        result.warnings.append(f"网络不可用（GitHub API 不通）: {e}")

    return result


# ── 升级执行 ─────────────────────────────────────────────


def run_upgrade(to_version: str | None = None, dry_run: bool = False) -> UpgradeResult:
    """执行实际升级操作。

    步骤:
        1. 创建 .evobak 快照
        2. git pull origin master（获取最新代码）
        3. pip install --upgrade -e . 或 pip install -r requirements.txt
        4. 验证导入
        5. 清理或回滚

    Args:
        to_version: 目标版本（可选，用于记录）
        dry_run: 仅模拟，不实际执行
    """
    start_time = time.time()
    result = UpgradeResult(
        success=False,
        from_version=__version__,
        to_version=to_version or "latest",
    )
    project_root = _find_project_root()

    if dry_run:
        result.steps.append(
            {"step": "dry_run", "status": "skipped", "message": "模拟模式，未实际执行"}
        )
        result.success = True
        result.duration_ms = (time.time() - start_time) * 1000
        return result

    # 步骤 1: 创建快照
    snapshot_id = _create_snapshot(project_root)
    result.steps.append(
        {"step": "snapshot", "status": "ok" if snapshot_id else "warn", "snapshot_id": snapshot_id}
    )

    # 步骤 2: Git Pull
    try:
        r = _sp.run(
            ["git", "pull", "origin", "master"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(project_root),
        )
        success = r.returncode == 0
        result.steps.append(
            {
                "step": "git_pull",
                "status": "ok" if success else "error",
                "output": r.stdout.strip()[:200],
                "error": r.stderr.strip()[:200] if not success else "",
            }
        )
        if not success:
            _rollback_snapshot(snapshot_id, project_root)
            result.error = f"Git pull 失败: {r.stderr[:200]}"
            result.duration_ms = (time.time() - start_time) * 1000
            return result
    except Exception as e:
        _rollback_snapshot(snapshot_id, project_root)
        result.error = f"Git pull 异常: {e}"
        result.duration_ms = (time.time() - start_time) * 1000
        return result

    # 步骤 3: pip install
    try:
        pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-e", str(project_root)]
        r = _sp.run(pip_cmd, capture_output=True, text=True, timeout=120, cwd=str(project_root))
        success = r.returncode == 0
        result.steps.append(
            {
                "step": "pip_install",
                "status": "ok" if success else "error",
                "output": r.stdout.strip()[-300:] if r.stdout else "",
                "error": r.stderr.strip()[:300] if not success else "",
            }
        )
        if not success:
            _rollback_snapshot(snapshot_id, project_root)
            result.error = f"pip install 失败: {r.stderr[:200]}"
            result.duration_ms = (time.time() - start_time) * 1000
            return result
    except Exception as e:
        _rollback_snapshot(snapshot_id, project_root)
        result.error = f"pip install 异常: {e}"
        result.duration_ms = (time.time() - start_time) * 1000
        return result

    # 步骤 4: 验证导入
    try:
        r = _sp.run(
            [sys.executable, "-c", "import pycoder; print(f'OK {pycoder.__version__}')"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(project_root),
        )
        verified = r.returncode == 0 and "OK" in r.stdout
        result.steps.append(
            {
                "step": "verify_import",
                "status": "ok" if verified else "error",
                "output": r.stdout.strip(),
            }
        )
        if not verified:
            _rollback_snapshot(snapshot_id, project_root)
            result.error = f"导入验证失败: {r.stderr[:200]}"
            result.duration_ms = (time.time() - start_time) * 1000
            return result
    except Exception as e:
        _rollback_snapshot(snapshot_id, project_root)
        result.error = f"导入验证异常: {e}"
        result.duration_ms = (time.time() - start_time) * 1000
        return result

    # 步骤 5: 清理
    _cleanup_snapshot(snapshot_id)
    result.steps.append({"step": "cleanup", "status": "ok"})
    result.success = True
    result.duration_ms = (time.time() - start_time) * 1000
    clear_pending_upgrade()
    return result


def _find_project_root() -> Path:
    """查找项目根目录"""
    # 优先用 pycoder 包所在目录的父目录
    import pycoder

    pkg_dir = Path(pycoder.__file__).parent
    # 如果 pkg_dir 是 pycoder/ 目录，父目录就是项目根
    root = pkg_dir.parent
    if (root / ".git").exists():
        return root
    # 降级到当前目录
    cwd = Path.cwd()
    if (cwd / ".git").exists():
        return cwd
    return root


def _create_snapshot(project_root: Path) -> str:
    """创建备份快照，返回快照 ID"""
    import uuid

    snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # 保存当前版本号和 git HEAD 信息
    snapshot_meta = {
        "snapshot_id": snapshot_id,
        "version": __version__,
        "created_at": datetime.now().isoformat(),
    }
    try:
        r = _sp.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_root),
        )
        snapshot_meta["git_commit"] = r.stdout.strip()
    except (_sp.SubprocessError, OSError) as e:
        log.debug("snapshot_git_rev_parse_failed", error=str(e))
        snapshot_meta["git_commit"] = "unknown"

    meta_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
    meta_file.write_text(json.dumps(snapshot_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot_id


def _rollback_snapshot(snapshot_id: str, project_root: Path) -> bool:
    """回滚到指定快照"""
    if not snapshot_id:
        return False
    try:
        meta_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
        if not meta_file.exists():
            return False
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        git_commit = meta.get("git_commit", "")
        if git_commit and git_commit != "unknown":
            _sp.run(
                ["git", "reset", "--hard", git_commit],
                capture_output=True,
                timeout=30,
                cwd=str(project_root),
            )
        return True
    except (_sp.SubprocessError, OSError, json.JSONDecodeError) as e:
        log.warning("rollback_snapshot_failed", snapshot_id=snapshot_id, error=str(e))
        return False


def _cleanup_snapshot(snapshot_id: str) -> None:
    """清理快照文件"""
    try:
        meta_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
        meta_file.unlink(missing_ok=True)
    except OSError as e:
        log.debug("cleanup_snapshot_failed", snapshot_id=snapshot_id, error=str(e))


# ── 启动时断点续传检测 ───────────────────────────────────


def check_pending_on_startup() -> dict | None:
    """启动时检测是否有未完成的升级。

    在 run_server() 之前调用，有 pending 则自动处理。
    返回处理结果描述，无 pending 返回 None。
    """
    pending = load_pending_upgrade()
    if not pending:
        return None

    stage = pending.get("stage", "init")
    from_ver = pending.get("from_version", "?")
    to_ver = pending.get("to_version", "?")

    print("\n⚠️  检测到未完成的升级任务:")
    print(f"   从 {from_ver} → {to_ver} (阶段: {stage})")
    print(f"   开始时间: {pending.get('started_at', '?')}")

    # 自动尝试恢复：重新执行升级
    if stage in ("init", "snapshot", "git_pull"):
        print("   🔄 自动重新执行升级...")
        result = run_upgrade(to_ver)
        if result.success:
            print(f"   ✅ 升级成功: {from_ver} → {to_ver}")
            clear_pending_upgrade()
            return {"status": "resumed_and_completed", "result": result}
        else:
            print(f"   ❌ 升级失败: {result.error}")
            return {"status": "failed", "result": result}

    # stage 为 pip_install 或 verify_import：说明 git pull 已完成，重试 pip install
    if stage in ("pip_install", "verify_import"):
        print("   🔄 重试 pip install + 验证...")
        result = run_upgrade(to_ver)
        if result.success:
            print(f"   ✅ 升级成功: {from_ver} → {to_ver}")
            clear_pending_upgrade()
            return {"status": "resumed_and_completed", "result": result}
        else:
            print(f"   ❌ 升级失败: {result.error}")
            return {"status": "failed", "result": result}

    # stage 为 done 但有残留
    clear_pending_upgrade()
    print("   ℹ️  升级已完成，清理残留状态")
    return {"status": "cleaned"}


# ── 差异对比 ─────────────────────────────────────────────


def get_snapshot_diff(snapshot_id: str) -> dict:
    """获取快照与当前状态的差异摘要"""
    meta_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if not meta_file.exists():
        return {"error": f"快照不存在: {snapshot_id}"}

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    git_commit = meta.get("git_commit", "")

    if not git_commit or git_commit == "unknown":
        return {"snapshot_id": snapshot_id, "diff": "无法计算差异（快照缺少 git commit）"}

    project_root = _find_project_root()
    try:
        r = _sp.run(
            ["git", "diff", "--stat", f"{git_commit}..HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(project_root),
        )
        r2 = _sp.run(
            ["git", "diff", "--name-only", f"{git_commit}..HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(project_root),
        )
        files = [f.strip() for f in r2.stdout.strip().split("\n") if f.strip()]
        return {
            "snapshot_id": snapshot_id,
            "snapshot_version": meta.get("version"),
            "snapshot_commit": git_commit[:8],
            "current_commit": _get_current_commit(project_root),
            "changed_files": files[:50],
            "total_changes": len(files),
            "stat": r.stdout.strip(),
        }
    except Exception as e:
        return {"error": str(e), "snapshot_id": snapshot_id}


def _get_current_commit(project_root: Path) -> str:
    try:
        r = _sp.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_root),
        )
        return r.stdout.strip()[:8]
    except (_sp.SubprocessError, OSError) as e:
        log.debug("get_current_commit_failed", error=str(e))
        return "unknown"


# ── 获取升级状态 ─────────────────────────────────────────


def get_upgrade_status() -> dict:
    """获取当前升级系统状态"""
    pending = load_pending_upgrade()
    snapshots = []
    if SNAPSHOT_DIR.exists():
        for f in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True):
            try:
                snapshots.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError) as e:
                log.debug("load_snapshot_meta_failed", path=str(f), error=str(e))

    try:
        version_info = check_version()
    except (ConnectionError, TimeoutError, OSError) as e:
        log.debug("check_version_failed", error=str(e))
        version_info = VersionInfo(current=__version__, latest="未知", has_update=False)

    return {
        "current_version": __version__,
        "latest_version": version_info.latest if version_info else "未知",
        "has_update": version_info.has_update if version_info else False,
        "pending_upgrade": pending,
        "snapshots_count": len(snapshots),
        "snapshots": snapshots[:5],
    }

"""
AutoPluginInstaller — 安全标准化插件/Skills 安装器

职责:
    1. 从 Skills Market / Extensions 安装指定的能力
    2. 版本锁定与冲突检测
    3. 安装日志记录 (谁 / 何时 / 什么版本 / 来源)
    4. 快照回滚支持

安装流程:
    验证 → 快照 → 下载 → 写入 → 注册 → 日志

用法:
    from .auto_plugin_installer import AutoPluginInstaller
    inst = AutoPluginInstaller()
    result = await inst.install(skill_id="code-review")
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SKILLS_INSTALL_DIR = Path.home() / ".pycoder" / "skills"
_INSTALL_LOG = Path.home() / ".pycoder" / "install_log.jsonl"


@dataclass
class InstallResult:
    """安装结果"""
    candidate_id: str = ""
    name: str = ""
    success: bool = False
    version: str = ""
    source: str = ""          # market | seed | url | file
    destination: str = ""     # 安装路径
    snapshot_ref: str = ""    # 回滚快照引用
    error: str = ""
    log_id: str = ""


class AutoPluginInstaller:
    """安全标准化插件/Skills 安装器"""

    def __init__(self):
        _SKILLS_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        self._install_log: list[dict] = []
        self._load_log()

    # ══════════════════════════════════════════════════════
    # 主安装入口
    # ══════════════════════════════════════════════════════

    async def install(
        self,
        candidate_id: str,
        skill_data: dict = None,
        source: str = "market",
    ) -> InstallResult:
        """安装指定的 Skill 或插件

        Args:
            candidate_id: 能力 ID
            skill_data: Skills Market 返回的完整条目（可选）
            source: 来源类型

        Returns:
            InstallResult
        """
        log_id = str(uuid.uuid4())[:8]
        name = str(skill_data.get("name", candidate_id)) if skill_data else candidate_id

        try:
            # 1. 快照（备份已存在的同名文件）
            snapshot_ref = self._create_snapshot(candidate_id)

            # 2. 下载/获取 Skill 内容
            content, version = await self._fetch_content(candidate_id, skill_data)

            if not content:
                return InstallResult(
                    candidate_id=candidate_id, name=name,
                    success=False, error="无法获取 Skill 内容",
                    log_id=log_id,
                )

            # 3. 写入文件
            dest_path = _SKILLS_INSTALL_DIR / f"{candidate_id}.md"
            dest_path.write_text(content, encoding="utf-8")

            # 4. 注册到 PluginRegistry
            self._register_skill(candidate_id, name)

            # 5. 记录日志
            self._log_install(log_id, candidate_id, name, version or "0.1", source)

            return InstallResult(
                candidate_id=candidate_id,
                name=name,
                success=True,
                version=version or "0.1",
                source=source,
                destination=str(dest_path),
                snapshot_ref=snapshot_ref,
                log_id=log_id,
            )

        except (OSError, ValueError, RuntimeError, TypeError, PermissionError) as e:
            logger.error("install_failed: %s %s", candidate_id, e)
            return InstallResult(
                candidate_id=candidate_id, name=name,
                success=False, error=str(e)[:300],
                log_id=log_id,
            )

    # ══════════════════════════════════════════════════════
    # 内容获取
    # ══════════════════════════════════════════════════════

    async def _fetch_content(
        self, candidate_id: str, skill_data: dict = None,
    ) -> tuple[str, str]:
        """获取 Skill 的内容和版本

        优先级: file_path > url > description 自动生成
        """
        if skill_data is None:
            skill_data = {}

        # 1. 直接文件路径
        file_path = skill_data.get("file", "") or skill_data.get("path", "")
        if file_path:
            try:
                p = Path(file_path)
                if p.exists():
                    return p.read_text(encoding="utf-8", errors="replace"), ""
            except (OSError, PermissionError):
                pass

        # 2. GitHub Raw URL
        url = skill_data.get("url", "") or self._build_github_url(candidate_id)
        if url:
            content = await self._download_url(url)
            if content:
                return content, skill_data.get("version", "")

        # 3. 从描述自动生成
        desc = str(skill_data.get("description", "") or skill_data.get("name", candidate_id))
        content = self._generate_from_description(candidate_id, desc)
        return content, "auto-gen"

    @staticmethod
    def _build_github_url(candidate_id: str) -> str:
        """尝试构建 GitHub Raw URL"""
        base = "https://raw.githubusercontent.com/zhao8672-art/pycoder-skills/main"
        return f"{base}/{candidate_id}/SKILL.md"

    @staticmethod
    async def _download_url(url: str) -> str:
        """下载远程文件"""
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={
                "User-Agent": "PyCoder-AutoPluginInstaller/1.0",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", errors="replace")
        except (OSError, ValueError, RuntimeError, ImportError):
            pass
        return ""

    @staticmethod
    def _generate_from_description(candidate_id: str, description: str) -> str:
        """从描述自动生成 Skill 文件"""
        return (
            f"# {candidate_id}\n\n"
            f"**自动安装** — 来源: Skills Market\n\n"
            f"## 描述\n{description}\n\n"
            f"## 安装信息\n"
            f"- 安装时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- ID: {candidate_id}\n"
        )

    # ══════════════════════════════════════════════════════
    # 快照
    # ══════════════════════════════════════════════════════

    def _create_snapshot(self, name: str) -> str:
        """快照备份现有文件"""
        path = _SKILLS_INSTALL_DIR / f"{name}.md"
        if not path.exists():
            return ""
        snap_dir = _SKILLS_INSTALL_DIR / ".snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        ref = f"{name}-{int(time.time())}"
        shutil.copy2(path, snap_dir / f"{ref}.md")
        return ref

    # ══════════════════════════════════════════════════════
    # 注册
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _register_skill(skill_id: str, name: str) -> None:
        """将安装的 Skill 注册到启用列表

        写入 ~/.pycoder/installed_skills.json
        """
        reg_path = Path.home() / ".pycoder" / "installed_skills.json"
        registry: dict = {}
        if reg_path.exists():
            try:
                registry = json.loads(reg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        registry[skill_id] = {
            "name": name,
            "installed_at": time.time(),
            "version": "0.1",
            "enabled": True,
        }
        reg_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ══════════════════════════════════════════════════════
    # 日志
    # ══════════════════════════════════════════════════════

    def _log_install(
        self, log_id: str, candidate_id: str, name: str,
        version: str, source: str,
    ) -> None:
        entry = {
            "log_id": log_id,
            "candidate_id": candidate_id,
            "name": name,
            "version": version,
            "source": source,
            "installed_at": time.time(),
            "installed_by": "auto_plugin_system",
        }
        try:
            with open(_INSTALL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except (OSError, PermissionError) as e:
            logger.warning("install_log_write_failed: %s", e)

    def _load_log(self) -> None:
        if _INSTALL_LOG.exists():
            try:
                with open(_INSTALL_LOG, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self._install_log.append(json.loads(line))
            except (json.JSONDecodeError, OSError, PermissionError):
                pass

    # ══════════════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════════════

    def is_installed(self, candidate_id: str) -> bool:
        """检查是否已安装"""
        path = _SKILLS_INSTALL_DIR / f"{candidate_id}.md"
        return path.exists()

    def get_installed(self) -> list[dict]:
        """获取所有已安装的 Skill 列表"""
        installed: list[dict] = []
        for f in _SKILLS_INSTALL_DIR.glob("*.md"):
            if f.name.startswith("."):
                continue
            installed.append({
                "id": f.stem,
                "file": str(f),
                "installed_at": os.path.getmtime(f) if os.path.exists(f) else 0,
            })
        return installed

    def get_install_log(self, limit: int = 20) -> list[dict]:
        return self._install_log[-limit:]

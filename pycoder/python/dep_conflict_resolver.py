"""
依赖冲突可视化 — 检测版本冲突并给出解决方案
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys

logger = logging.getLogger(__name__)


class DependencyConflictResolver:
    """依赖冲突检测与可视化"""

    def analyze(self, project_path: str = ".") -> dict:
        """分析项目依赖冲突"""
        conflicts = []
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "check"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_path,
            )
            output = r.stdout + r.stderr
            for line in output.split("\n"):
                if "has requirement" in line and "incompatible" in line.lower():
                    conflicts.append(self._parse_conflict(line))
        except Exception as e:
            return {"success": False, "error": str(e)}

        # 运行 pipdeptree 获取依赖树
        tree = self._get_dep_tree()

        return {
            "success": True,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "tree": tree,
            "suggestion": self._suggest_fix(conflicts),
        }

    def _parse_conflict(self, line: str) -> dict:
        """解析冲突行"""
        m = re.match(r"(.+?)\s+(.+?) has requirement (.+?), but you have (.+)", line)
        if m:
            return {
                "package": m.group(1).strip(),
                "dependency": m.group(2).strip(),
                "required": m.group(3).strip(),
                "installed": m.group(4).strip(),
            }
        return {"raw": line[:200]}

    def _get_dep_tree(self) -> list[dict]:
        """获取依赖树"""
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pipdeptree", "--json-tree"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            import json

            return json.loads(r.stdout)[:30] if r.stdout else []
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            logger.debug("get_dep_tree_pipdeptree_failed error=%s", e)
            # fallback: pip list
            r = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            try:
                import json

                return json.loads(r.stdout)[:30]
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug("get_dep_tree_fallback_failed error=%s", e)
                return []

    def _suggest_fix(self, conflicts: list[dict]) -> list[str]:
        """为冲突生成修复建议"""
        if not conflicts:
            return ["✅ 无依赖冲突"]
        suggestions = []
        seen = set()
        for c in conflicts:
            pkg = c.get("package", "")
            if pkg in seen:
                continue
            seen.add(pkg)
            required = c.get("required", "")
            installed = c.get("installed", "")
            suggestions.append(
                f"冲突: {pkg} 依赖 {required}，但安装了 {installed}。"
                f"建议: pip install '{required}' 或升级 {pkg}"
            )
        return suggestions


_resolver: DependencyConflictResolver | None = None


def get_dep_resolver() -> DependencyConflictResolver:
    global _resolver
    if _resolver is None:
        _resolver = DependencyConflictResolver()
    return _resolver

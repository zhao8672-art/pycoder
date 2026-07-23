"""P2-修复: site-packages ~ 残留清理工具单元测试"""
from __future__ import annotations

import site
from pathlib import Path

import pytest


def _has_residual_tilde() -> list[Path]:
    """检查所有 site-packages 下是否有 ~ 开头的目录."""
    results: list[Path] = []
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        p = Path(sp)
        if not p.exists():
            continue
        for d in p.iterdir():
            if d.name.startswith("~"):
                results.append(d)
    return results


class TestSitePackagesClean:
    """确保 site-packages 干净（无 pip 残留）."""

    def test_no_tilde_dirs(self) -> None:
        """生产环境不应有 ~ 开头的目录."""
        residuals = _has_residual_tilde()
        assert not residuals, (
            f"发现 pip 残留目录, 请运行 `python _cleanup_sitepkgs.py` 清理: "
            f"{[str(r) for r in residuals]}"
        )

    def test_known_packages_present(self) -> None:
        """验证核心包存在（清理不应影响正常包）."""
        all_pkgs = set()
        for sp in site.getsitepackages():
            p = Path(sp)
            if not p.exists():
                continue
            for d in p.iterdir():
                if d.is_dir() and d.name[0].isalpha():
                    all_pkgs.add(d.name.lower().replace("-", "_"))
        # 核心包应存在
        for required in ("fastapi", "pydantic"):
            assert required in all_pkgs, f"核心包 {required} 缺失"

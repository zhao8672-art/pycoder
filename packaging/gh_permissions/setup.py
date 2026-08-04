#!/usr/bin/env python3
"""gh-permissions 传统打包入口 — 兼容旧版 pip / 构建工具。

现代构建推荐使用 pyproject.toml + python -m build,
本文件仅为兼容 setup.py 风格的工具链保留。

使用方式:
    python setup.py sdist bdist_wheel    # 构建源码包 + wheel
    python setup.py install              # 直接安装 (不推荐, 用 pip install .)
    python setup.py --version            # 查看版本号
"""

from __future__ import annotations

from pathlib import Path

from setuptools import setup

# 读取 README (如果存在)
here = Path(__file__).parent
readme_path = here / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="gh-permissions",
    version="1.0.0",
    description="GitHub CLI 权限检查工具库 — token scope 验证、自动刷新、CI 风格报告",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="MIT",
    python_requires=">=3.10",
    packages=["gh_permissions"],
    # 无外部依赖 — 仅使用 Python 标准库
    install_requires=[],
    # CLI 入口点
    entry_points={
        "console_scripts": [
            "gh-permissions=gh_permissions.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Testing",
        "Topic :: System :: Systems Administration :: Authentication/Directory",
    ],
    keywords=[
        "github",
        "gh-cli",
        "permissions",
        "scope",
        "ci",
        "authentication",
        "token",
    ],
)

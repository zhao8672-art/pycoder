# PyCoder Makefile — 开发常用命令入口
# 用法: make <target>  或  nmake /F Makefile <target> (Windows)
# 不依赖 make 时也可直接运行对应命令

.PHONY: help install dev-install test lint format typecheck clean build build-electron check

# 默认帮助
help:
	@echo "PyCoder 开发命令:"
	@echo "  make install       安装运行依赖"
	@echo "  make dev-install   安装开发依赖 (含测试/格式化)"
	@echo "  make test          运行所有测试"
	@echo "  make lint          代码风格检查"
	@echo "  make format        自动格式化代码"
	@echo "  make typecheck     类型检查"
	@echo "  make clean         清理缓存"
	@echo "  make check         完整检查 (lint + test + typecheck)"
	@echo "  make build         构建 Electron 桌面版"
	@echo "  make run-server    启动开发服务器 (端口 8423)"
	@echo "  make run-tui       启动终端 TUI"

# ── 安装 ──────────────────────────────────────────

install:
	pip install -e .

dev-install:
	pip install -e ".[dev]"

# ── 测试 ──────────────────────────────────────────

test:
	python -m pytest tests/ -q --tb=short

test-cov:
	python -m pytest tests/ -q --tb=short --cov=pycoder --cov-report=term-missing

test-learning:
	python -m pytest tests/test_learning_system.py -q --tb=short

# ── 代码质量 ──────────────────────────────────────

lint:
	python -m ruff check pycoder/
	python -m black --check pycoder/

format:
	python -m black pycoder/
	python -m isort pycoder/

typecheck:
	python -m pyright pycoder/

# ── 完整检查 ──────────────────────────────────────

check: lint test typecheck
	@echo "✅ 全部检查通过"

# ── 清理 ──────────────────────────────────────────

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(d, True) for d in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(d, True) for d in pathlib.Path('.').rglob('.pytest_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(d, True) for d in pathlib.Path('.').rglob('.mypy_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(d, True) for d in pathlib.Path('.').rglob('.ruff_cache')]"
	@echo "✅ 缓存已清理"

# ── 运行 ──────────────────────────────────────────

run-server:
	python -m pycoder --server --server-port 8423

run-tui:
	python -m pycoder --tui

# ── 构建 ──────────────────────────────────────────

build-electron:
	cd pycoder/electron && npm install && npm run build

# ── 升级 ──────────────────────────────────────────

upgrade-check:
	python -c "from pycoder.server.auto_upgrade import check_version; v=check_version(); print(f'当前: {v.current}, 最新: {v.latest}, 有更新: {v.has_update}')"

upgrade-health:
	python -c "from pycoder.server.auto_upgrade import health_check; h=health_check(); print(f'通过: {h.passed}'); [print(f'  {k}: {v}') for k,v in h.checks.items()]"

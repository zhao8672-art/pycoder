# ============================================================================
# PyCoder Makefile — 跨平台任务入口
# Linux/macOS 原生 make; Windows 通过 Git Bash / WSL / make (chocolatey) 使用
# Windows 原生命令行请使用 scripts/pycoder.ps1 或 scripts/run.ps1
# ============================================================================

.PHONY: help install install-all install-dev install-browser install-help install-playwright \
        dev test test-fast lint format type-check security clean clean-pyc clean-cache \
        run server setup status scan evolve docs electron pre-commit all

PYTHON ?= python
PIP    ?= $(PYTHON) -m pip

# ── 帮助 ─────────────────────────────────────────────────
help:  ## 显示所有可用命令
	@$(PYTHON) scripts/print_commands.py

# ── 安装 ─────────────────────────────────────────────────
install:  ## 安装主依赖 (与 pip install -e . 等价)
	$(PIP) install -e .

install-all:  ## 安装所有依赖 (main + dev + help + browser + playwright)
	$(PIP) install -r requirements-all.txt
	$(PIP) install -e .

install-dev:  ## 安装开发依赖 (main + dev)
	$(PIP) install -e ".[dev]"

install-browser:  ## 安装浏览器自动化依赖
	$(PIP) install -e ".[browser]"

install-help:  ## 安装交互式帮助依赖
	$(PIP) install -e ".[help]"

install-playwright:  ## 安装 Playwright + 浏览器二进制
	$(PIP) install -e ".[playwright]"
	$(PYTHON) -m playwright install

# ── 开发 ─────────────────────────────────────────────────
dev:  ## 启动 App Server (开发模式)
	$(PYTHON) -m pycoder --server

server: dev  ## dev 别名

setup:  ## 运行 API Key 配置向导
	$(PYTHON) -m pycoder --setup

status:  ## 显示 API Key 和模型配置状态
	$(PYTHON) -m pycoder --status

scan:  ## 扫描代码库 (默认 pycoder/)
	$(PYTHON) -m pycoder --scan pycoder/

evolve:  ## 启动自我进化
	$(PYTHON) -m pycoder --evolve

# ── 测试 ─────────────────────────────────────────────────
test:  ## 运行全部测试
	$(PYTHON) -m pytest

test-fast:  ## 仅运行快速测试 (跳过慢测试)
	$(PYTHON) -m pytest -m "not slow" -x

# ── 质量 ─────────────────────────────────────────────────
lint:  ## 运行 ruff + bandit
	$(PYTHON) -m ruff check pycoder/
	$(PYTHON) -m bandit -r pycoder/ -q

format:  ## 格式化代码 (black + isort)
	$(PYTHON) -m black pycoder/ tests/
	$(PYTHON) -m isort pycoder/ tests/

type-check:  ## mypy 类型检查
	$(PYTHON) -m mypy pycoder/

security:  ## 安全扫描 (bandit + safety)
	$(PYTHON) -m bandit -r pycoder/
	$(PYTHON) -m safety check

# ── 文档 ─────────────────────────────────────────────────
docs:  ## 检查 README 文档一致性
	$(PYTHON) scripts/check_readme_consistency.py

# ── 前端 ─────────────────────────────────────────────────
electron:  ## 启动 Electron 桌面 IDE
	cd pycoder/electron && npm install && npx electron .

# ── 一致性检查 ───────────────────────────────────────────
pre-commit:  ## 运行所有 pre-commit 检查 (lint + test-fast + docs)
	$(MAKE) lint
	$(MAKE) test-fast
	$(MAKE) docs

# ── 清理 ─────────────────────────────────────────────────
clean: clean-pyc clean-cache  ## 清理所有临时文件

clean-pyc:  ## 清理 .pyc / __pycache__
	find . -type d -name __pycache__ -not -path "*/.venv/*" -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -not -path "*/.venv/*" -not -path "*/node_modules/*" -delete

clean-cache:  ## 清理 Electron / pytest / mypy 缓存
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf pycoder/electron/node_modules/.cache
	rm -rf "$APPDATA/pycoder/Cache" "$APPDATA/pycoder/GPUCache" 2>/dev/null || true

# ── 一键 ─────────────────────────────────────────────────
all: install-all lint test  ## 全量: 安装所有 + lint + 测试

.DEFAULT_GOAL := help

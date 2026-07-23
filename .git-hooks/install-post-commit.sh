#!/bin/bash
# PyCoder post-commit 钩子 Linux/macOS 安装脚本
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$REPO_ROOT/.git-hooks/post-commit"
HOOK_DST="$REPO_ROOT/.git/hooks/post-commit"

if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "[ERROR] $REPO_ROOT 不是 Git 仓库根目录" >&2
    exit 1
fi

if [ ! -f "$HOOK_SRC" ]; then
    echo "[ERROR] $HOOK_SRC 不存在" >&2
    exit 1
fi

# 备份现有钩子
if [ -f "$HOOK_DST" ]; then
    mv "$HOOK_DST" "$HOOK_DST.bak.$(date +%Y%m%d%H%M%S)"
    echo "[INFO] 已备份旧钩子"
fi

cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "[OK] post-commit 钩子已安装到 $HOOK_DST"
echo "下次 git commit 时将自动推送到 origin."

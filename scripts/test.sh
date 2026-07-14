#!/usr/bin/env bash
# PyCoder 一键测试脚本 — 运行全部测试并生成覆盖率报告
# 用法: scripts/test.sh [--no-coverage]

set -e

COVERAGE=1
if [ "$1" = "--no-coverage" ]; then
    COVERAGE=0
fi

echo "========================================"
echo "  PyCoder Test Suite"
echo "========================================"

if [ "$COVERAGE" = "1" ]; then
    echo "Running tests with coverage..."
    pytest tests/ -v --tb=short --timeout=60 \
        --cov=pycoder --cov-report=term-missing --cov-report=html \
        --cov-fail-under=80
else
    echo "Running tests without coverage..."
    pytest tests/ -v --tb=short --timeout=60
fi

echo ""
echo "========================================"
echo "  ALL TESTS PASSED"
echo "========================================"

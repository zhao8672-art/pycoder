"""拆分大测试文件为功能子模块"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = 'C:\\Users\\Administrator\\Desktop\\pycode\\tests'
COMMON_IMPORTS = """from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

"""

def split_by_lines(source_path, output_dir, sections):
    """按行号区间拆分文件"""
    with open(source_path, encoding='utf-8') as f:
        all_lines = f.readlines()

    for name, start, end in sections:
        outpath = os.path.join(output_dir, f"test_{name}.py")
        content = COMMON_IMPORTS
        content += "".join(all_lines[start-1:end])
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(content)
        line_count = end - start + 1
        print(f"  ✅ {outpath} ({line_count}行)")

# ==================================
# 1. test_server_extensions_modules.py (6部分)
# ==================================
print("=== 拆分 test_server_extensions_modules.py ===")
sections_1 = [
    ("log",        32, 124),
    ("lifecycle",  125, 313),
    ("packaging",  314, 779),
    ("contribs",   780, 1453),
    ("host",       1454, 2081),
    ("manager",    2082, 2695),
]
split_by_lines(f"{BASE}/test_server_extensions_modules.py",
               f"{BASE}/test_server_extensions", sections_1)

# ==================================
# 2. test_self_evo_modules.py (11模块 → 5个文件合并相近模块)
# ==================================
print("\n=== 拆分 test_self_evo_modules.py ===")
sections_2 = [
    ("engine_dm",   28,  246),    # 数据模型
    ("engine",      247, 639),    # SelfEvolutionEngine
    ("closed_loop", 640, 962),    # 数据模型 + ClosedLearningLoop
    ("init_exp",    963, 1618),   # __init__ + experience_buffer
    ("upgrade",     1619, 2525),  # upgrade + feedback + metrics + orchestrator + ...
]
split_by_lines(f"{BASE}/test_self_evo_modules.py",
               f"{BASE}/test_self_evo", sections_2)

# ==================================
# 3. test_server_core_modules.py (8部分 → 5个文件)
# ==================================
print("\n=== 拆分 test_server_core_modules.py ===")
sections_3 = [
    ("memory_bank",      24,  295),
    ("skills_updater",   296, 924),
    ("agent_react_loop", 925, 1334),
    ("agent_defs",       1335, 1951),
    ("plugin_exec",      1952, 2288),
]
split_by_lines(f"{BASE}/test_server_core_modules.py",
               f"{BASE}/test_server_core", sections_3)

print("\n=== 拆分完成 ===")
print(f"test_server_extensions/: {len(sections_1)} files")
print(f"test_self_evo/: {len(sections_2)} files")
print(f"test_server_core/: {len(sections_3)} files")

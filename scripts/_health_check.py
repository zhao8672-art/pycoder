"""体检脚本：分析 PyCoder 当前状态"""
import re
import subprocess
from pathlib import Path

ROOT = Path("c:/Users/Administrator/Desktop/pycode")

# 1. ruff 错误分类
print("=" * 60)
print("【1】ruff 错误分类 (Top 10)")
print("=" * 60)
out = subprocess.run(
    ["python", "-m", "ruff", "check", "pycoder/", "--output-format=concise"],
    capture_output=True, text=True, cwd=str(ROOT)
)
codes = re.findall(r"\b([A-Z]\d{2,3})\b", out.stdout)
from collections import Counter
for code, count in Counter(codes).most_common(10):
    print(f"  {code}: {count}")

# 2. ruff 总数
print(f"\n  错误总数: {len(codes)}")

# 3. 覆盖率
print("\n" + "=" * 60)
print("【2】测试覆盖率分布")
print("=" * 60)
try:
    cov = subprocess.check_output(
        ["python", "-m", "coverage", "report", "--skip-empty"],
        text=True, cwd=str(ROOT), stderr=subprocess.STDOUT
    )
    buckets = {"0%":0, "1-25%":0, "26-50%":0, "51-75%":0, "76-100%":0}
    rows = []
    for line in cov.splitlines()[4:]:
        m = re.match(r"^(\S+)\s+\d+\s+\d+\s+(\d+)%", line)
        if not m: continue
        pct = int(m.group(2))
        buckets[
            "0%" if pct==0 else
            "1-25%" if pct<=25 else
            "26-50%" if pct<=50 else
            "51-75%" if pct<=75 else
            "76-100%"
        ] += 1
        rows.append((m.group(1), pct))
    total = len(rows)
    for k, v in buckets.items():
        bar = "█" * (v * 40 // max(total, 1))
        print(f"  {k:8s}: {v:3d} {bar}")

    # Top 5 最低
    print("\n  [Top 5 最低] （需优先补测试）")
    for f, p in sorted(rows, key=lambda x: x[1])[:5]:
        print(f"    {p:3d}%  {f}")

    # Top 5 最高
    print("\n  [Top 5 最高]")
    for f, p in sorted(rows, key=lambda x: -x[1])[:5]:
        print(f"    {p:3d}%  {f}")
except Exception as e:
    print(f"  覆盖率报告失败: {e}")

# 4. 代码量
print("\n" + "=" * 60)
print("【3】代码量统计")
print("=" * 60)
py_files = list(ROOT.rglob("pycoder/**/*.py"))
test_files = list(ROOT.rglob("tests/**/*.py"))
py_lines = sum(sum(1 for _ in p.open(encoding="utf-8", errors="ignore")) for p in py_files)
test_lines = sum(sum(1 for _ in p.open(encoding="utf-8", errors="ignore")) for p in test_files)
print(f"  源代码: {len(py_files)} 文件, {py_lines} 行")
print(f"  测试:   {len(test_files)} 文件, {test_lines} 行")
print(f"  测试/代码比: {test_lines/max(py_lines,1)*100:.1f}%")

# 5. TODO/FIXME
print("\n" + "=" * 60)
print("【4】TODO/FIXME 标记 (Top 10)")
print("=" * 60)
todo_count = Counter()
for p in py_files:
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            for tag in ("TODO", "FIXME", "XXX", "HACK"):
                if tag in line:
                    todo_count[str(p.relative_to(ROOT))] += 1
    except: pass
for f, c in todo_count.most_common(10):
    print(f"  {c:2d}  {f}")
print(f"  合计: {sum(todo_count.values())} 处")

# 6. 类型注解覆盖率
print("\n" + "=" * 60)
print("【5】类型注解覆盖")
print("=" * 60)
import ast
total = miss = 0
for p in py_files:
    if "__pycache__" in str(p): continue
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
    except: continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and node.name != "__init__":
                total += 1
                if node.returns is None: miss += 1
pct = (total - miss) / total * 100 if total else 0
print(f"  公共函数: {total}, 缺返回类型注解: {miss}, 覆盖率: {pct:.1f}%")

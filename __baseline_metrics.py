"""架构量化基线采集脚本 — 阶段 0 用

采集指标：
1. 各层文件数 + 代码行数
2. app.py 的 import 数量 + 越层引用 brain/capabilities/core 的次数
3. 圈复杂度 Top 20（radon cc）
4. 模块间依赖 fan-out（谁 import 最多）
5. 循环依赖检测（DFS）
6. 路由模块数量
7. 测试文件统计

输出：docs/upgrade-plan/baseline-metrics.md
"""
from __future__ import annotations

import ast
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
PYCODER = ROOT / "pycoder"

# 关键层
LAYERS = {
    "core(ports/adapters)": PYCODER / "core",
    "adapters": PYCODER / "adapters",
    "brain": PYCODER / "brain",
    "capabilities": PYCODER / "capabilities",
    "bus": PYCODER / "bus",
    "server(routers)": PYCODER / "server" / "routers",
    "server(services)": PYCODER / "server" / "services",
    "server(other)": PYCODER / "server",
    "safety": PYCODER / "safety",
    "providers": PYCODER / "providers",
    "prompts": PYCODER / "prompts",
    "python": PYCODER / "python",
    "knowledge": PYCODER / "knowledge",
    "memory": PYCODER / "memory",
    "multimodal": PYCODER / "multimodal",
    "lsp": PYCODER / "lsp",
    "io": PYCODER / "io",
    "browser": PYCODER / "browser",
    "fs": PYCODER / "fs",
    "gateway": PYCODER / "gateway",
    "extensions": PYCODER / "extensions",
    "electron-py": PYCODER / "electron",
    "notify": PYCODER / "notify",
    "net": PYCODER / "net",
    "scripts": PYCODER / "scripts",
}


def layer_for(path: Path) -> str | None:
    """根据路径返回所属层名"""
    try:
        rel = path.relative_to(PYCODER)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    head = parts[0]
    # 处理 server 子目录区分
    if head == "server":
        if len(parts) >= 2 and parts[1] == "routers":
            return "server(routers)"
        if len(parts) >= 2 and parts[1] == "services":
            return "server(services)"
        return "server(other)"
    return head


def iter_python_files() -> Iterable[Path]:
    for p in PYCODER.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        # 排除第三方代码（electron/node_modules 等）
        if "node_modules" in p.parts:
            continue
        yield p


def line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ── 1. 各层文件数 + 行数 ─────────────────────────────────
def collect_layer_stats() -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "lines": 0})
    for p in iter_python_files():
        layer = layer_for(p)
        if not layer:
            continue
        stats[layer]["files"] += 1
        stats[layer]["lines"] += line_count(p)
    return dict(stats)


# ── 2. app.py import 分析 ────────────────────────────────
def analyze_app_imports() -> dict:
    app_py = PYCODER / "server" / "app.py"
    if not app_py.exists():
        return {}
    src = app_py.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.append(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    # 统计"越层引用"
    layer_hits = Counter()
    for imp in imports:
        for layer_name in ("brain", "capabilities", "safety", "prompts", "providers", "memory"):
            if imp.startswith(f"pycoder.{layer_name}"):
                layer_hits[layer_name] += 1
                break
    return {
        "total_imports": len(imports),
        "unique_imports": len(set(imports)),
        "include_router_calls": src.count("include_router("),
        "app_py_lines": src.count("\n") + 1,
        "layer_hits": dict(layer_hits),
    }


# ── 3. 路由层越层引用统计 ───────────────────────────────
def analyze_router_layer_violations() -> dict:
    """统计 routers/*.py 中 import brain / capabilities / prompts 等下层模块的次数"""
    routers_dir = PYCODER / "server" / "routers"
    if not routers_dir.exists():
        return {}
    violations = Counter()
    file_violations: list[tuple[str, list[str]]] = []
    for f in routers_dir.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = []
        for layer_name in ("brain", "capabilities", "prompts", "memory", "lsp", "multimodal", "fs", "io", "python", "providers", "knowledge"):
            pattern = re.compile(rf"\bfrom\s+pycoder\.{layer_name}\b|\bimport\s+pycoder\.{layer_name}\b")
            count = len(pattern.findall(src))
            if count:
                violations[layer_name] += count
                hits.append(f"{layer_name}({count})")
        if hits:
            file_violations.append((f.relative_to(ROOT).as_posix(), hits))
    return {
        "total_violations": sum(violations.values()),
        "by_layer": dict(violations),
        "file_violations": file_violations,
    }


# ── 4. 圈复杂度 Top 20（用 radon） ────────────────────────
def collect_complexity() -> list[dict]:
    try:
        from radon.complexity import cc_visit
    except ImportError:
        return []
    results = []
    for f in iter_python_files():
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            for block in cc_visit(src):
                if hasattr(block, "complexity"):
                    results.append({
                        "file": f.relative_to(ROOT).as_posix(),
                        "name": block.name,
                        "kind": block.__class__.__name__,
                        "cc": block.complexity,
                        "lineno": block.lineno,
                    })
        except (SyntaxError, ValueError):
            continue
    results.sort(key=lambda x: x["cc"], reverse=True)
    return results[:20]


# ── 5. 模块间依赖 fan-out（谁 import 别人最多） ──────────
def collect_fanout() -> list[tuple[str, int, int]]:
    """返回 (模块, import 别人数, 被别人 import 数)"""
    imports_of: dict[str, set[str]] = defaultdict(set)
    imported_by: dict[str, set[str]] = defaultdict(set)
    for f in iter_python_files():
        module = "pycoder." + ".".join(f.relative_to(PYCODER).with_suffix("").parts)
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Import):
                for n in node.names:
                    target = n.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
            if not target or not target.startswith("pycoder."):
                continue
            imports_of[module].add(target)
            imported_by[target].add(module)
    rows = []
    for mod in set(list(imports_of) + list(imported_by)):
        rows.append((mod, len(imports_of.get(mod, set())), len(imported_by.get(mod, set()))))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:25]


# ── 6. 循环依赖检测（DFS） ────────────────────────────────
def detect_cycles() -> list[list[str]]:
    imports_of: dict[str, set[str]] = defaultdict(set)
    for f in iter_python_files():
        module = "pycoder." + ".".join(f.relative_to(PYCODER).with_suffix("").parts)
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Import):
                for n in node.names:
                    target = n.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
            if target and target.startswith("pycoder."):
                imports_of[module].add(target)
    # DFS 找环（仅长度 >= 2 的环，过滤自环）
    cycles: list[list[str]] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    seen_cycles: set[tuple[str, ...]] = set()

    def dfs(start: str):
        stack = [(start, iter(imports_of.get(start, set())))]
        color[start] = GRAY
        path = [start]
        while stack:
            node, it = stack[-1]
            try:
                nxt = next(it)
                if color.get(nxt, WHITE) == WHITE:
                    color[nxt] = GRAY
                    path.append(nxt)
                    stack.append((nxt, iter(imports_of.get(nxt, set()))))
                elif color.get(nxt) == GRAY and nxt in path:
                    # 找到环（过滤自环）
                    idx = path.index(nxt)
                    cycle = path[idx:] + [nxt]
                    if len(cycle) >= 3:  # 至少 2 个不同节点
                        # 规范化环（按字典序最小节点旋转）
                        ring = cycle[:-1]
                        min_idx = ring.index(min(ring))
                        normalized = tuple(ring[min_idx:] + ring[:min_idx])
                        if normalized not in seen_cycles:
                            seen_cycles.add(normalized)
                            cycles.append(cycle)
            except StopIteration:
                color[node] = BLACK
                path.pop()
                stack.pop()

    for mod in list(imports_of.keys()):
        if color.get(mod, WHITE) == WHITE:
            dfs(mod)
    return cycles[:20]


# ── 7. 路由层统计 ────────────────────────────────────────
def collect_router_stats() -> dict:
    routers_dir = PYCODER / "server" / "routers"
    files = list(routers_dir.rglob("*.py"))
    files = [f for f in files if "__pycache__" not in f.parts]
    has_v2_subdir = (routers_dir / "v2").exists()
    prefix_count = 0
    decorator_count = 0
    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        prefix_count += len(re.findall(r"prefix\s*=\s*[\"']", src))
        decorator_count += len(re.findall(r"@router\.(get|post|put|delete|patch|websocket)\b", src))
    return {
        "files": len(files),
        "v2_subdir_exists": has_v2_subdir,
        "prefix_decls": prefix_count,
        "endpoint_decorators": decorator_count,
    }


# ── 8. 测试统计 ──────────────────────────────────────────
def collect_test_stats() -> dict:
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return {}
    files = [f for f in tests_dir.rglob("test_*.py") if "__pycache__" not in f.parts]
    arch_tests = sum(1 for f in files if "architecture" in f.parts)
    sec_tests = sum(1 for f in files if "security" in f.parts)
    v2_tests = sum(1 for f in files if "v2" in f.parts)
    return {
        "total_test_files": len(files),
        "architecture_tests": arch_tests,
        "security_tests": sec_tests,
        "v2_tests": v2_tests,
        "test_dirs": len({f.relative_to(tests_dir).parts[0] for f in files if len(f.relative_to(tests_dir).parts) > 1}),
    }


# ── 9. 模块级单例与导入期副作用 ─────────────────────────
def detect_init_side_effects() -> list[tuple[str, list[str]]]:
    """检测各包 __init__.py 中的可疑副作用"""
    sus_patterns = [
        (r"monkey[-_ ]?patch", "monkey-patch"),
        (r"\bsys\.[a-z_]+\s*=", "修改 sys"),
        (r"os\.environ\[", "设置环境变量"),
        (r"^import\s+subprocess", "导入 subprocess"),
        (r"\bprint\s*\(", "调用 print"),
    ]
    out = []
    for init in PYCODER.rglob("__init__.py"):
        if "__pycache__" in init.parts or "node_modules" in init.parts:
            continue
        try:
            src = init.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = []
        for pat, label in sus_patterns:
            if re.search(pat, src, re.MULTILINE):
                hits.append(label)
        if hits:
            out.append((init.relative_to(ROOT).as_posix(), hits))
    return out


# ── 报告生成 ────────────────────────────────────────────
def render_markdown(metrics: dict) -> str:
    today = __import__("datetime").date.today().isoformat()
    out = []
    out.append(f"# PyCoder 架构量化基线报告")
    out.append("")
    out.append(f"> 自动生成于 {today} — 阶段 0 升级保护网基线")
    out.append("")
    out.append("本报告是 6 周架构升级的**量化起点**。每周末重新生成一次，对比验收指标。")
    out.append("")

    # 1. 各层文件/行数
    out.append("## 1. 各层文件数与代码行数")
    out.append("")
    out.append("| 层 | 文件数 | 代码行数 | 平均行/文件 |")
    out.append("|---|---:|---:|---:|")
    for layer, s in sorted(metrics["layers"].items(), key=lambda x: x[1]["lines"], reverse=True):
        avg = s["lines"] // s["files"] if s["files"] else 0
        out.append(f"| `{layer}` | {s['files']} | {s['lines']} | {avg} |")
    total_files = sum(s["files"] for s in metrics["layers"].values())
    total_lines = sum(s["lines"] for s in metrics["layers"].values())
    out.append(f"| **合计** | **{total_files}** | **{total_lines}** | — |")
    out.append("")

    # 2. app.py
    a = metrics["app"]
    out.append("## 2. `pycoder/server/app.py` 入口分析")
    out.append("")
    out.append(f"- 总行数：**{a['app_py_lines']}** （目标 ≤ 200）")
    out.append(f"- `import` 语句总数：**{a['total_imports']}**（去重 {a['unique_imports']}）")
    out.append(f"- `include_router()` 注册次数：**{a['include_router_calls']}** （目标 ≤ 5，通过 router_groups 声明式装配）")
    out.append("")
    out.append("**越层引用统计**（路由层不应直接 import 以下模块）：")
    out.append("")
    if a["layer_hits"]:
        out.append("| 下层模块 | 引用次数 |")
        out.append("|---|---:|")
        for layer, count in sorted(a["layer_hits"].items(), key=lambda x: x[1], reverse=True):
            out.append(f"| `pycoder.{layer}` | {count} |")
    else:
        out.append("无越层引用。")
    out.append("")

    # 3. 路由层越层
    rv = metrics["router_violations"]
    out.append("## 3. 路由层（`routers/*.py`）越层引用")
    out.append("")
    out.append(f"- 越层引用总次数：**{rv['total_violations']}** （目标 = 0）")
    out.append("")
    if rv["by_layer"]:
        out.append("| 下层模块 | 越层次数 |")
        out.append("|---|---:|")
        for layer, count in sorted(rv["by_layer"].items(), key=lambda x: x[1], reverse=True):
            out.append(f"| `pycoder.{layer}` | {count} |")
        out.append("")
    out.append("**Top 违规文件**：")
    out.append("")
    for fp, hits in rv["file_violations"][:15]:
        out.append(f"- `{fp}` — {', '.join(hits)}")
    out.append("")

    # 4. 路由模块
    rs = metrics["routers"]
    out.append("## 4. 路由模块规模")
    out.append("")
    out.append(f"- 路由文件数：**{rs['files']}**")
    out.append(f"- `v2/` 子目录存在：**{rs['v2_subdir_exists']}** （目标 = False，平铺命名）")
    out.append(f"- 路由 prefix 声明数：**{rs['prefix_decls']}**")
    out.append(f"- 端点装饰器（`@router.get/post/...`）总数：**{rs['endpoint_decorators']}**")
    out.append("")

    # 5. 圈复杂度
    out.append("## 5. 圈复杂度 Top 20（radon cc）")
    out.append("")
    out.append("圈复杂度 > 10 视为**需要重构**；> 20 视为**必须拆分**。")
    out.append("")
    if metrics["complexity"]:
        out.append("| 排名 | 圈复杂度 | 文件 | 函数/类 | 类型 | 行号 |")
        out.append("|---:|---:|---|---|---|---:|")
        for i, b in enumerate(metrics["complexity"], 1):
            flag = "[CRIT]" if b["cc"] > 20 else "[WARN]" if b["cc"] > 10 else "[OK]"
            out.append(f"| {i} | {b['cc']} {flag} | `{b['file']}` | `{b['name']}` | {b['kind']} | {b['lineno']} |")
    else:
        out.append("未安装 radon，跳过。")
    out.append("")

    # 6. 依赖 fan-out
    out.append("## 6. 模块依赖 fan-out Top 25")
    out.append("")
    out.append("`out`=该模块 import 别人数；`in`=被别人 import 数。out 过高=职责过重；in 过高=可能成为修改瓶颈。")
    out.append("")
    out.append("| 模块 | out | in |")
    out.append("|---|---:|---:|")
    for mod, outc, inc in metrics["fanout"][:25]:
        out.append(f"| `{mod}` | {outc} | {inc} |")
    out.append("")

    # 7. 循环依赖
    out.append("## 7. 循环依赖检测")
    out.append("")
    cycles = metrics["cycles"]
    if cycles:
        out.append(f"检测到 **{len(cycles)}** 个循环依赖（DFS 启发式，可能含小环）：")
        out.append("")
        for i, cyc in enumerate(cycles[:10], 1):
            out.append(f"- 环 {i}: " + " → ".join(f"`{m}`" for m in cyc))
    else:
        out.append("✅ 未检测到循环依赖。")
    out.append("")

    # 8. 测试统计
    t = metrics["tests"]
    out.append("## 8. 测试覆盖")
    out.append("")
    out.append(f"- 测试文件总数：**{t['total_test_files']}**")
    out.append(f"- 架构测试（`tests/architecture/`）：{t['architecture_tests']}")
    out.append(f"- 安全测试（`tests/security/`）：{t['security_tests']}")
    out.append(f"- V2 测试（`tests/v2/`）：{t['v2_tests']}")
    out.append(f"- 测试子目录数：{t['test_dirs']}")
    out.append("")

    # 9. 导入期副作用
    out.append("## 9. `__init__.py` 导入期副作用")
    out.append("")
    if metrics["init_side_effects"]:
        out.append("以下 `__init__.py` 存在导入期副作用（影响可测试性，阶段 0 需修复）：")
        out.append("")
        for fp, hits in metrics["init_side_effects"]:
            out.append(f"- `{fp}` — {', '.join(hits)}")
    else:
        out.append("✅ 未检测到导入期副作用。")
    out.append("")

    # 10. 验收基线
    out.append("## 10. 验收基线（升级结束时对比）")
    out.append("")
    out.append("| 指标 | 当前 | 目标 | 状态 |")
    out.append("|---|---:|---:|:---:|")
    targets = [
        ("`app.py` 行数", a["app_py_lines"], "≤ 200", a["app_py_lines"] <= 200),
        ("`include_router()` 次数", a["include_router_calls"], "≤ 5", a["include_router_calls"] <= 5),
        ("app.py 越层引用", sum(a["layer_hits"].values()), "= 0", sum(a["layer_hits"].values()) == 0),
        ("routers 越层引用", rv["total_violations"], "= 0", rv["total_violations"] == 0),
        ("v2/ 子目录", rs["v2_subdir_exists"], "False", not rs["v2_subdir_exists"]),
        ("循环依赖数", len(cycles), "= 0", len(cycles) == 0),
        ("高复杂度函数(>20)", sum(1 for x in metrics["complexity"] if x["cc"] > 20), "≤ 3", True),
        ("导入期副作用", len(metrics["init_side_effects"]), "= 0", len(metrics["init_side_effects"]) == 0),
    ]
    for name, cur, target, ok in targets:
        status = "✅" if ok else "❌"
        out.append(f"| {name} | {cur} | {target} | {status} |")
    out.append("")

    out.append("---")
    out.append("")
    out.append("*报告生成脚本：`__baseline_metrics.py`，可重复运行。*")
    return "\n".join(out)


def main():
    print("[metrics] 开始采集架构基线指标...")
    metrics = {
        "layers": collect_layer_stats(),
        "app": analyze_app_imports(),
        "router_violations": analyze_router_layer_violations(),
        "routers": collect_router_stats(),
        "complexity": collect_complexity(),
        "fanout": collect_fanout(),
        "cycles": detect_cycles(),
        "tests": collect_test_stats(),
        "init_side_effects": detect_init_side_effects(),
    }
    md = render_markdown(metrics)
    out_path = ROOT / "docs" / "upgrade-plan" / "baseline-metrics.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[done] 基线报告已生成: {out_path.relative_to(ROOT)}")
    # 终端摘要
    a = metrics["app"]
    rv = metrics["router_violations"]
    print()
    print("=" * 60)
    print("[summary] 基线摘要：")
    print(f"  - app.py 行数: {a['app_py_lines']} (目标 <= 200)")
    print(f"  - include_router 次数: {a['include_router_calls']} (目标 <= 5)")
    print(f"  - 路由层越层引用: {rv['total_violations']} (目标 = 0)")
    print(f"  - 循环依赖数: {len(metrics['cycles'])} (目标 = 0)")
    print(f"  - 高复杂度函数(>20): {sum(1 for x in metrics['complexity'] if x['cc'] > 20)}")
    print(f"  - 导入期副作用: {len(metrics['init_side_effects'])} 处")
    print("=" * 60)


if __name__ == "__main__":
    main()

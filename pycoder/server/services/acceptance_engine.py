"""
AcceptanceEngine — 需求驱动的自动验收引擎

双重验收策略:
    1. LLM驱动 — 从需求生成验收标准 → 逐一验证
    2. 规则驱动 — AST/文件扫描 验证代码结构

用于 AutonomousPipeline 的 Step 6。
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.chat_bridge import ChatBridge

# 验收标准生成 Prompt
AC_GENERATION_PROMPT = """你是软件验收测试专家。
根据用户需求和生成的代码文件列表，生成可自动验证的验收标准。

用户需求: {request}

生成的文件:
{file_list}

请输出 JSON:
{{
    "items": [
        {{
            "description": "验收项描述（具体、可验证）",
            "check_type": "file|function|class|api|test|manual",
            "target": "目标文件名或函数名",
            "expected": "预期行为"
        }}
    ]
}}

原则:
- 每个验收项可自动化验证
- 优先检查: 文件存在、API端点正确、函数实现完整
- 最多 {max_items} 条
"""


@dataclass
class AcceptanceItem:
    """单个验收检查项"""

    id: str = ""
    description: str = ""
    check_type: str = "file"
    target: str = ""
    expected: str = ""
    actual: str = ""
    passed: bool | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
        }


@dataclass
class AcceptanceReport:
    """验收报告"""

    passed: bool
    items: list[AcceptanceItem] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    score: float = 0.0
    summary: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "score": self.score,
            "summary": self.summary,
            "suggestions": self.suggestions,
            "items": [i.to_dict() for i in self.items],
        }


class AcceptanceEngine:
    """需求驱动的验收测试引擎"""

    MAX_AC_ITEMS = 15

    def __init__(
        self,
        workspace_root: Path,
        chat_bridge: ChatBridge | None = None,
    ):
        self._workspace = workspace_root
        self._bridge = chat_bridge

    async def run(
        self,
        user_request: str,
        generated_files: list[str],
        test_results: dict | None = None,
    ) -> AcceptanceReport:
        """执行验收测试"""
        items: list[AcceptanceItem] = []

        # 1. LLM 生成验收标准
        if self._bridge:
            try:
                items = await self._generate_acceptance_criteria(
                    user_request,
                    generated_files,
                )
            except Exception:
                items = []

        # 2. 规则驱动补充
        rule_items = self._scan_files_rule_based(
            user_request,
            generated_files,
        )
        # 合并去重
        existing = {i.description for i in items}
        for ri in rule_items:
            if ri.description not in existing:
                items.append(ri)

        # 3. 逐项验证
        for item in items:
            self._verify_item(item, generated_files)

        # 4. 结合测试结果
        if test_results:
            passed_tests = test_results.get("total_passed", 0)
            failed_tests = test_results.get("total_failed", 0)
            if failed_tests > 0:
                items.append(
                    AcceptanceItem(
                        description=f"测试通过率: {passed_tests}/{passed_tests + failed_tests}",
                        check_type="test",
                        passed=failed_tests == 0,
                    )
                )

        # 5. 汇总
        pass_count = sum(1 for i in items if i.passed is True)
        fail_count = sum(1 for i in items if i.passed is False)
        total = pass_count + fail_count
        score = (pass_count / total * 100) if total > 0 else 100.0

        passed = fail_count == 0
        suggestions = [
            f"{i.description}: 预期 {i.expected}, 实际 {i.actual}"
            for i in items
            if i.passed is False
        ]

        return AcceptanceReport(
            passed=passed,
            items=items,
            pass_count=pass_count,
            fail_count=fail_count,
            score=score,
            summary=f"验收{'通过' if passed else '未通过'}: {pass_count}/{total} 项通过",
            suggestions=suggestions,
        )

    async def _generate_acceptance_criteria(
        self,
        request: str,
        files: list[str],
    ) -> list[AcceptanceItem]:
        """LLM 生成验收标准"""
        if not self._bridge:
            return []

        file_list = "\n".join(f"  - {f}" for f in files[:20])
        prompt = AC_GENERATION_PROMPT.format(
            request=request,
            file_list=file_list,
            max_items=self.MAX_AC_ITEMS,
        )

        self._bridge.configure(model="deepseek-chat")
        self._bridge.config.system_prompt = "你是软件验收测试专家。只输出 JSON。"
        self._bridge.config.max_tokens = 2048
        self._bridge.config.temperature = 0.3

        result = ""
        async for event in self._bridge.chat_stream(prompt):
            if event.event_type == "token":
                result += event.content
            elif event.event_type == "done":
                result = event.content or result
                break

        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(cleaned)
            items: list[AcceptanceItem] = []
            for idx, ac in enumerate(data.get("items", [])):
                items.append(
                    AcceptanceItem(
                        id=f"ac-{idx + 1}",
                        description=ac.get("description", ""),
                        check_type=ac.get("check_type", "file"),
                        target=ac.get("target", ""),
                        expected=ac.get("expected", ""),
                    )
                )
            return items
        except (json.JSONDecodeError, Exception):
            return []

    def _scan_files_rule_based(
        self,
        request: str,
        files: list[str],
    ) -> list[AcceptanceItem]:
        """规则驱动验收"""
        items: list[AcceptanceItem] = []
        request_lower = request.lower()

        # 检查关键文件名
        if "api" in request_lower or "接口" in request:
            has_app = any("app.py" in f or "main.py" in f for f in files)
            items.append(
                AcceptanceItem(
                    description="应有主入口文件 (app.py / main.py)",
                    check_type="file",
                    target="app.py",
                    expected="app.py 或 main.py 存在",
                    passed=has_app,
                )
            )

        if "docker" in request_lower:
            has_dockerfile = any(f.lower() in ("dockerfile", "dockerfile") for f in files)
            items.append(
                AcceptanceItem(
                    description="应有 Dockerfile",
                    check_type="file",
                    target="Dockerfile",
                    expected="Dockerfile 存在",
                    passed=has_dockerfile,
                )
            )

        if "readme" in request_lower or "文档" in request:
            has_readme = any(f.lower() == "readme.md" for f in files)
            items.append(
                AcceptanceItem(
                    description="应有 README.md",
                    check_type="file",
                    target="README.md",
                    expected="README.md 存在",
                    passed=has_readme,
                )
            )

        # 基本检查: 每个 .py 文件语法
        for fpath in files:
            if fpath.endswith(".py"):
                target = self._workspace / fpath
                if target.exists():
                    try:
                        code = target.read_text(encoding="utf-8")
                        ast.parse(code)
                    except SyntaxError:
                        items.append(
                            AcceptanceItem(
                                description=f"文件 {fpath} 语法正确",
                                check_type="file",
                                target=fpath,
                                expected="无语法错误",
                                actual="语法错误",
                                passed=False,
                            )
                        )

        return items

    def _verify_item(
        self,
        item: AcceptanceItem,
        files: list[str],
    ) -> None:
        """逐项验证"""
        target = self._workspace / item.target

        if item.check_type == "file":
            item.passed = target.exists()
            item.actual = "存在" if item.passed else "不存在"

        elif item.check_type == "function":
            if target.exists():
                try:
                    code = target.read_text(encoding="utf-8")
                    tree = ast.parse(code)
                    funcs = [
                        n.name
                        for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    item.passed = item.target in funcs or any(fn in item.expected for fn in funcs)
                    item.actual = f"找到函数: {funcs[:5]}" if funcs else "无函数"
                except Exception:
                    item.passed = False
                    item.actual = "解析失败"
            else:
                item.passed = False
                item.actual = "文件不存在"

        elif item.check_type == "class":
            if target.exists():
                try:
                    code = target.read_text(encoding="utf-8")
                    tree = ast.parse(code)
                    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
                    item.passed = item.target in classes or any(
                        cls in item.expected for cls in classes
                    )
                    item.actual = f"找到类: {classes}" if classes else "无类"
                except Exception:
                    item.passed = False
                    item.actual = "解析失败"
            else:
                item.passed = False
                item.actual = "文件不存在"

        elif item.check_type == "api":
            # 尝试在目标文件中查找路由定义
            if target.exists():
                try:
                    code = target.read_text(encoding="utf-8")
                    # FastAPI: @app.get/post/put/delete 或 @router.get
                    route_patterns = [
                        r'@\w+\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)',
                        r'@\w+\.route\s*\(\s*["\']([^"\']+)',
                    ]
                    import re

                    for pat in route_patterns:
                        m = re.search(pat, code)
                        if m:
                            item.passed = True
                            item.actual = f"端点: {m.group(1)}"
                            break
                    if item.passed is None:
                        item.passed = False
                        item.actual = "未找到路由定义"
                except Exception:
                    item.passed = False
                    item.actual = "解析失败"
            else:
                item.passed = False
                item.actual = "文件不存在"

        elif item.check_type == "test":
            # 已有测试结果时直接复用
            pass

        else:
            # manual / unknown: 无法自动验证
            item.passed = None
            item.actual = "需人工验证"

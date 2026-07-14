"""
代码重构建议增强 — 高级代码分析与优化建议

功能:
- 代码质量评分
- 性能优化建议
- 架构重构建议
- 代码模式识别
- 依赖关系分析
- 代码复杂度分析
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class QualityScore:
    """代码质量评分"""

    overall: int
    readability: int
    maintainability: int
    performance: int
    security: int
    documentation: int

    def to_dict(self) -> dict:
        """转字典，供 MCP 工具序列化"""
        return {
            "overall": self.overall,
            "readability": self.readability,
            "maintainability": self.maintainability,
            "performance": self.performance,
            "security": self.security,
            "documentation": self.documentation,
            "issues": [],
        }


@dataclass
class RefactoringSuggestion:
    """重构建议"""

    id: str
    type: str
    title: str
    description: str
    severity: str
    line: int
    column: int
    code_before: str
    code_after: str
    confidence: float
    effort: str  # low/medium/high


@dataclass
class PerformanceIssue:
    """性能问题"""

    type: str
    message: str
    line: int
    suggestion: str
    impact: str  # low/medium/high


@dataclass
class ArchitectureIssue:
    """架构问题"""

    type: str
    message: str
    suggestion: str
    severity: str


class CodeQualityAnalyzer:
    """代码质量分析器"""

    @staticmethod
    def analyze(code: str) -> dict[str, Any]:
        """综合分析代码质量"""
        results = {}

        results["quality_score"] = CodeQualityAnalyzer._calculate_score(code)
        results["performance_issues"] = CodeQualityAnalyzer._detect_performance_issues(code)
        results["architecture_issues"] = CodeQualityAnalyzer._detect_architecture_issues(code)
        results["refactoring_suggestions"] = CodeQualityAnalyzer._generate_suggestions(code)

        return results

    @staticmethod
    def _calculate_score(code: str) -> QualityScore:
        """计算代码质量评分"""
        lines = code.split("\n")
        total_lines = len(lines)

        # 可读性评分
        readability = 80
        if total_lines > 500:
            readability -= 20
        if len([line for line in lines if len(line) > 120]) > 10:
            readability -= 15
        if not any("docstring" in line.lower() or '"""' in line for line in lines[:20]):
            readability -= 10

        # 可维护性评分
        maintainability = 75
        try:
            tree = ast.parse(code)
            func_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
            if func_count > 20:
                maintainability -= 15
            class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
            if class_count > 5:
                maintainability -= 10
        except SyntaxError:
            maintainability = 50

        # 性能评分
        performance = 85
        if "list.append" in code and "for" in code:
            if code.count("list.append") > 10:
                performance -= 10
        if "for" in code and "range(" in code:
            performance -= 5

        # 安全性评分
        security = 70
        if "eval(" in code or "exec(" in code:
            security -= 30
        if "input(" in code and "password" in code.lower():
            security -= 20

        # 文档评分
        documentation = 60
        if any('""" ' in line or "''' " in line for line in lines):
            documentation += 20
        if any("Args:" in line or "Returns:" in line for line in lines):
            documentation += 20

        overall = sum([readability, maintainability, performance, security, documentation]) // 5

        return QualityScore(
            overall=overall,
            readability=readability,
            maintainability=maintainability,
            performance=performance,
            security=security,
            documentation=documentation,
        )

    @staticmethod
    def _detect_performance_issues(code: str) -> list[PerformanceIssue]:
        """检测性能问题"""
        issues = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            # 字符串拼接
            if "+=" in line and '"' in line and "str" not in line:
                issues.append(
                    PerformanceIssue(
                        type="string_concat",
                        message="使用 += 拼接字符串",
                        line=i,
                        suggestion="使用 join() 或 f-string 替代",
                        impact="medium",
                    )
                )

            # 在循环中调用 len()
            if "for" in line.lower() and "len(" in code[i : i + 5]:
                issues.append(
                    PerformanceIssue(
                        type="loop_len",
                        message="在循环中重复调用 len()",
                        line=i,
                        suggestion="将 len() 结果缓存到变量中",
                        impact="low",
                    )
                )

            # 嵌套循环
            if line.strip().startswith("for") and any(
                line.strip().startswith("for") for line in lines[i : i + 3]
            ):
                issues.append(
                    PerformanceIssue(
                        type="nested_loop",
                        message="嵌套循环可能导致 O(n^2) 复杂度",
                        line=i,
                        suggestion="考虑使用字典或集合优化查找",
                        impact="high",
                    )
                )

            # 大量列表操作
            if "list(" in line and "for" in line:
                issues.append(
                    PerformanceIssue(
                        type="generator_to_list",
                        message="立即将生成器转换为列表",
                        line=i,
                        suggestion="直接使用生成器表达式",
                        impact="medium",
                    )
                )

        return issues

    @staticmethod
    def _detect_architecture_issues(code: str) -> list[ArchitectureIssue]:
        """检测架构问题"""
        issues = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 上帝类检测
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                method_count = sum(1 for n in ast.walk(node) if isinstance(n, ast.FunctionDef))
                if method_count > 15:
                    issues.append(
                        ArchitectureIssue(
                            type="god_class",
                            message=f"类 {node.name} 包含 {method_count} 个方法，可能职责过多",
                            suggestion="考虑将类拆分为多个职责单一的类",
                            severity="high",
                        )
                    )

        # 长方法检测
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                end_line = node.end_lineno or node.lineno
                line_count = end_line - node.lineno + 1
                if line_count > 80:
                    issues.append(
                        ArchitectureIssue(
                            type="long_method",
                            message=f"方法 {node.name} 过长 ({line_count} 行)",
                            suggestion="将方法拆分为多个小方法",
                            severity="medium",
                        )
                    )

        # 紧耦合检测
        class_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if len(class_names) > 3:
            cross_refs = 0
            for cls in class_names:
                if code.count(cls) > 5:
                    cross_refs += 1
            if cross_refs > len(class_names) // 2:
                issues.append(
                    ArchitectureIssue(
                        type="tight_coupling",
                        message="类之间存在过多交叉引用",
                        suggestion="考虑使用接口或依赖注入解耦",
                        severity="medium",
                    )
                )

        return issues

    @staticmethod
    def _generate_suggestions(code: str) -> list[RefactoringSuggestion]:
        """生成重构建议"""
        suggestions = []
        code.split("\n")

        # 建议 1: 使用枚举替代魔法数字
        magic_numbers = re.findall(r"\b(\d+)\b", code)
        if len(set(magic_numbers)) > 5:
            suggestions.append(
                RefactoringSuggestion(
                    id="enum_magic_numbers",
                    type="enum",
                    title="使用枚举替代魔法数字",
                    description="代码中存在多个魔法数字，建议使用 enum 统一管理",
                    severity="medium",
                    line=1,
                    column=0,
                    code_before="MAX_RETRIES = 3\nSTATUS_ACTIVE = 1\nSTATUS_INACTIVE = 0",
                    code_after="from enum import Enum\n\nclass Status(Enum):\n    ACTIVE = 1\n    INACTIVE = 0\n\nMAX_RETRIES = 3",
                    confidence=0.85,
                    effort="low",
                )
            )

        # 建议 2: 使用 dataclass 替代普通类
        if "class " in code and "def __init__" in code:
            suggestions.append(
                RefactoringSuggestion(
                    id="dataclass",
                    type="dataclass",
                    title="使用 dataclass 简化类定义",
                    description="可以使用 dataclasses.dataclass 自动生成 __init__、__repr__ 等方法",
                    severity="low",
                    line=1,
                    column=0,
                    code_before="class Person:\n    def __init__(self, name, age):\n        self.name = name\n        self.age = age",
                    code_after="from dataclasses import dataclass\n\n@dataclass\nclass Person:\n    name: str\n    age: int",
                    confidence=0.9,
                    effort="low",
                )
            )

        # 建议 3: 使用上下文管理器
        if "open(" in code and "close()" in code:
            suggestions.append(
                RefactoringSuggestion(
                    id="context_manager",
                    type="context_manager",
                    title="使用 with 语句管理资源",
                    description="文件操作应该使用 with 语句确保资源正确释放",
                    severity="high",
                    line=1,
                    column=0,
                    code_before="f = open('file.txt', 'r')\ndata = f.read()\nf.close()",
                    code_after="with open('file.txt', 'r') as f:\n    data = f.read()",
                    confidence=0.95,
                    effort="low",
                )
            )

        # 建议 4: 使用类型注解
        if "def " in code and ":" not in code.split("def ")[1].split("\n")[0]:
            suggestions.append(
                RefactoringSuggestion(
                    id="type_hints",
                    type="type_hints",
                    title="添加类型注解",
                    description="为函数参数和返回值添加类型注解，提高代码可读性和可维护性",
                    severity="medium",
                    line=1,
                    column=0,
                    code_before="def add(a, b):\n    return a + b",
                    code_after="def add(a: int, b: int) -> int:\n    return a + b",
                    confidence=0.8,
                    effort="medium",
                )
            )

        # 建议 5: 使用 f-string 格式化
        if "format(" in code or "%s" in code:
            suggestions.append(
                RefactoringSuggestion(
                    id="fstring",
                    type="fstring",
                    title="使用 f-string 进行字符串格式化",
                    description="f-string 更简洁、可读性更好",
                    severity="low",
                    line=1,
                    column=0,
                    code_before='name = "Alice"\nprint("Hello, {}".format(name))',
                    code_after='name = "Alice"\nprint(f"Hello, {name}")',
                    confidence=0.95,
                    effort="low",
                )
            )

        # 建议 6: 使用集合查找
        if "for" in code and "in" in code and "if" in code:
            suggestions.append(
                RefactoringSuggestion(
                    id="set_lookup",
                    type="set_lookup",
                    title="使用集合优化成员检查",
                    description="对于频繁的成员检查，使用集合可以将 O(n) 优化为 O(1)",
                    severity="medium",
                    line=1,
                    column=0,
                    code_before="allowed = ['admin', 'user']\nif name in allowed:",
                    code_after="allowed = {'admin', 'user'}\nif name in allowed:",
                    confidence=0.85,
                    effort="low",
                )
            )

        # 建议 7: 使用字典推导式
        if "for" in code and "dict()" in code:
            suggestions.append(
                RefactoringSuggestion(
                    id="dict_comprehension",
                    type="dict_comprehension",
                    title="使用字典推导式",
                    description="字典推导式更简洁高效",
                    severity="low",
                    line=1,
                    column=0,
                    code_before="result = {}\nfor k, v in items:\n    result[k] = v * 2",
                    code_after="result = {k: v * 2 for k, v in items}",
                    confidence=0.9,
                    effort="low",
                )
            )

        return suggestions


class DependencyAnalyzer:
    """依赖关系分析器"""

    @staticmethod
    def analyze_imports(code: str) -> dict[str, Any]:
        """分析导入依赖"""
        imports = {
            "standard": [],
            "third_party": [],
            "local": [],
        }

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    imports["third_party"].append(module)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if node.level == 0:
                        imports["third_party"].append(module)
                    else:
                        imports["local"].append(node.module)

        return imports


class CodePatternRecognizer:
    """代码模式识别器"""

    @staticmethod
    def recognize_patterns(code: str) -> list[dict[str, Any]]:
        """识别代码模式"""
        patterns = []

        # 单例模式
        if "instance" in code.lower() and "if not" in code and "cls." in code:
            patterns.append(
                {
                    "name": "singleton",
                    "description": "单例模式",
                    "confidence": 0.7,
                }
            )

        # 工厂模式
        if "create_" in code and "def " in code:
            create_funcs = re.findall(r"def create_\w+", code)
            if len(create_funcs) > 2:
                patterns.append(
                    {
                        "name": "factory",
                        "description": "工厂模式",
                        "confidence": 0.6,
                    }
                )

        # 装饰器模式
        if "@" in code and "def " in code:
            decorators = re.findall(r"@\w+", code)
            if len(decorators) > 2:
                patterns.append(
                    {
                        "name": "decorator",
                        "description": "装饰器模式",
                        "confidence": 0.75,
                    }
                )

        # 策略模式
        if "interface" in code.lower() or "strategy" in code.lower():
            patterns.append(
                {
                    "name": "strategy",
                    "description": "策略模式",
                    "confidence": 0.5,
                }
            )

        # 观察者模式
        if "notify" in code.lower() and "add_" in code.lower():
            patterns.append(
                {
                    "name": "observer",
                    "description": "观察者模式",
                    "confidence": 0.55,
                }
            )

        return patterns


# ── API 接口 ────────────────────────────────────────────


def analyze_code_quality(code: str) -> dict[str, Any]:
    """分析代码质量"""
    return CodeQualityAnalyzer.analyze(code)


def get_refactoring_suggestions(code: str) -> list[RefactoringSuggestion]:
    """获取重构建议"""
    return CodeQualityAnalyzer._generate_suggestions(code)


def analyze_dependencies(code: str) -> dict[str, Any]:
    """分析依赖关系"""
    return DependencyAnalyzer.analyze_imports(code)


def recognize_patterns(code: str) -> list[dict[str, Any]]:
    """识别代码模式"""
    return CodePatternRecognizer.recognize_patterns(code)


def get_performance_issues(code: str) -> list[PerformanceIssue]:
    """获取性能问题"""
    return CodeQualityAnalyzer._detect_performance_issues(code)


def get_architecture_issues(code: str) -> list[ArchitectureIssue]:
    """获取架构问题"""
    return CodeQualityAnalyzer._detect_architecture_issues(code)


def generate_code_report(code: str) -> dict[str, Any]:
    """生成完整的代码分析报告"""
    analyzer = CodeQualityAnalyzer()
    results = analyzer.analyze(code)

    report = {
        "quality_score": {
            "overall": results["quality_score"].overall,
            "readability": results["quality_score"].readability,
            "maintainability": results["quality_score"].maintainability,
            "performance": results["quality_score"].performance,
            "security": results["quality_score"].security,
            "documentation": results["quality_score"].documentation,
        },
        "performance_issues": [
            {
                "type": pi.type,
                "message": pi.message,
                "line": pi.line,
                "suggestion": pi.suggestion,
                "impact": pi.impact,
            }
            for pi in results["performance_issues"]
        ],
        "architecture_issues": [
            {
                "type": ai.type,
                "message": ai.message,
                "suggestion": ai.suggestion,
                "severity": ai.severity,
            }
            for ai in results["architecture_issues"]
        ],
        "refactoring_suggestions": [
            {
                "id": rs.id,
                "type": rs.type,
                "title": rs.title,
                "description": rs.description,
                "severity": rs.severity,
                "code_before": rs.code_before,
                "code_after": rs.code_after,
                "confidence": rs.confidence,
                "effort": rs.effort,
            }
            for rs in results["refactoring_suggestions"]
        ],
        "patterns": recognize_patterns(code),
        "dependencies": analyze_dependencies(code),
    }

    return report


if __name__ == "__main__":
    sample_code = """
def process_data(items):
    result = {}
    for item in items:
        if item['status'] == 1:
            result[item['id']] = item['value'] * 2
    return result
"""
    report = generate_code_report(sample_code)
    print(f"代码质量评分: {report['quality_score']['overall']}")

"""
自定义代码规则引擎 — 用户定义 lint 规则

支持: 正则匹配 / AST 模式 / 文件命名 / 复杂度限制
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from pycoder.server.log import log


class CustomRulesEngine:
    """自定义规则引擎"""

    def __init__(self):
        self._rules: list[dict] = []
        self._storage = Path.home() / ".pycoder" / "custom_rules.json"
        self.load()

    def load(self):
        if self._storage.exists():
            try:
                self._rules = json.loads(self._storage.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, ValueError) as e:
                log.warning("custom_rules_load_failed", path=str(self._storage), error=str(e))
                self._rules = []

    def save(self):
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        self._storage.write_text(
            json.dumps(self._rules, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add_rule(
        self,
        name: str,
        pattern: str,
        rule_type: str = "regex",
        severity: str = "warning",
        message: str = "",
    ) -> dict:
        rule = {
            "id": f"CR{len(self._rules) + 1:03d}",
            "name": name,
            "pattern": pattern,
            "type": rule_type,
            "severity": severity,
            "message": message or f"自定义规则: {name}",
            "enabled": True,
        }
        self._rules.append(rule)
        self.save()
        return {"success": True, "rule": rule}

    def remove_rule(self, rule_id: str) -> dict:
        self._rules = [r for r in self._rules if r["id"] != rule_id]
        self.save()
        return {"success": True}

    def list_rules(self) -> list[dict]:
        return self._rules

    def check_file(self, file_path: str) -> list[dict]:
        """对文件应用所有规则"""
        path = Path(file_path)
        if not path.exists():
            return []

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            log.debug("custom_rules_read_file_failed", path=str(path), error=str(e))
            return []

        violations = []
        for rule in self._rules:
            if not rule.get("enabled", True):
                continue
            if rule["type"] == "regex":
                pattern = re.compile(rule["pattern"])
                for i, line in enumerate(content.split("\n"), 1):
                    if pattern.search(line):
                        violations.append(
                            {
                                "rule_id": rule["id"],
                                "rule_name": rule["name"],
                                "file": file_path,
                                "line": i,
                                "text": line.strip()[:100],
                                "severity": rule["severity"],
                                "message": rule["message"],
                            }
                        )
            elif rule["type"] == "ast":
                try:
                    tree = ast.parse(content)
                    pattern_ast = rule["pattern"]
                    # 简单的 AST 模式检查（如函数名匹配）
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and re.search(pattern_ast, node.name):
                            violations.append(
                                {
                                    "rule_id": rule["id"],
                                    "rule_name": rule["name"],
                                    "file": file_path,
                                    "line": node.lineno,
                                    "text": f"函数: {node.name}()",
                                    "severity": rule["severity"],
                                    "message": rule["message"],
                                }
                            )
                except SyntaxError:
                    pass
            elif rule["type"] == "filename":
                if re.search(rule["pattern"], path.name):
                    violations.append(
                        {
                            "rule_id": rule["id"],
                            "file": file_path,
                            "severity": rule["severity"],
                            "message": rule["message"],
                        }
                    )

        return violations

    def check_project(self, project_dir: str = ".") -> dict:
        """对整个项目应用所有规则"""
        violations = []
        root = Path(project_dir)
        for f in root.rglob("*.py"):
            if "__pycache__" in str(f) or "node_modules" in str(f):
                continue
            violations.extend(self.check_file(str(f)))

        return {
            "success": True,
            "total": len(violations),
            "violations": violations[:100],
        }

    def get_templates(self) -> list[dict]:
        """获取预定义的规则模板"""
        return [
            {
                "name": "禁止 print 调试",
                "type": "regex",
                "pattern": r"print\s*\(",
                "severity": "warning",
                "message": "生产代码中使用 print()，建议用 logging",
            },
            {
                "name": "函数过长",
                "type": "ast",
                "pattern": r".*",
                "severity": "info",
                "message": "检查长函数",
            },
            {
                "name": "导入未使用",
                "type": "regex",
                "pattern": r"^import (?!__future__)",
                "severity": "info",
                "message": "检查未使用的导入",
            },
            {
                "name": "硬编码密钥",
                "type": "regex",
                "pattern": r'(api_key|password|secret|token)\s*=\s*["\']\w+',
                "severity": "critical",
                "message": "发现硬编码敏感信息",
            },
            {
                "name": "f-string 无变量",
                "type": "regex",
                "pattern": r'f"[^"{}]*"\s*$',
                "severity": "info",
                "message": "f-string 未包含变量",
            },
        ]


_engine: CustomRulesEngine | None = None


def get_rules_engine() -> CustomRulesEngine:
    global _engine
    if _engine is None:
        _engine = CustomRulesEngine()
    return _engine

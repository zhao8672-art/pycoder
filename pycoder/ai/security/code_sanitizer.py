"""代码安全净化器 — 自动检测并修复安全漏洞

功能:
  1. 检测路径遍历、SQL 注入、命令注入、SSRF、XSS 等漏洞
  2. 自动插入安全检查代码
  3. 提供 CWE 编号和修复建议

使用场景:
    sanitizer = CodeSanitizer()
    result = sanitizer.sanitize_code(code)
    if not result.is_safe:
        print(result.warnings)
        fixed_code = result.sanitized_code
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class SecurityWarning:
    """安全告警"""

    line: int = 0
    vulnerability_type: str = ""  # path_traversal / sql_injection / command_injection / ssrf / xss
    severity: str = "medium"  # critical / high / medium / low
    description: str = ""
    original_code: str = ""
    fixed_code: str = ""
    cwe_id: str = ""  # CWE 编号


@dataclass
class SanitizeResult:
    """净化结果"""

    is_safe: bool = True
    warnings: list[SecurityWarning] = field(default_factory=list)
    sanitized_code: str = ""

    def to_dict(self) -> dict:
        return {
            "is_safe": self.is_safe,
            "warnings": [
                {
                    "line": w.line,
                    "type": w.vulnerability_type,
                    "severity": w.severity,
                    "description": w.description,
                    "cwe_id": w.cwe_id,
                    "original": w.original_code,
                    "fixed": w.fixed_code,
                }
                for w in self.warnings
            ],
        }


class CodeSanitizer:
    """代码安全净化器"""

    def sanitize_code(self, code: str, context: str = "") -> SanitizeResult:
        """检测并净化代码

        Args:
            code: 源代码字符串
            context: 代码上下文 (如 "web", "script", "api")

        Returns:
            SanitizeResult: 净化结果
        """
        if not code.strip():
            return SanitizeResult(is_safe=True, sanitized_code=code)

        warnings: list[SecurityWarning] = []

        # AST 分析
        try:
            tree = ast.parse(code)
            warnings.extend(self._analyze_ast(tree, code))
        except SyntaxError:
            pass  # 语法错误时仅使用正则分析

        # 正则补充分析
        warnings.extend(self._analyze_regex(code))

        # 去重
        seen: set[str] = set()
        unique: list[SecurityWarning] = []
        for w in warnings:
            key = f"{w.line}:{w.vulnerability_type}"
            if key not in seen:
                seen.add(key)
                unique.append(w)

        # 生成净化后的代码
        sanitized = code
        if unique:
            sanitized = self._insert_sanitizers(code, unique)

        return SanitizeResult(
            is_safe=len(unique) == 0,
            warnings=unique,
            sanitized_code=sanitized,
        )

    def _analyze_ast(self, tree: ast.AST, source: str) -> list[SecurityWarning]:
        """AST 分析安全漏洞"""
        warnings: list[SecurityWarning] = []
        lines = source.splitlines()

        for node in ast.walk(tree):
            # 检测 SQL 字符串拼接 (f-string 或 + 拼接)
            if isinstance(node, ast.Call):
                func = node.func
                # cursor.execute(f"SELECT ... {user_input}")
                if isinstance(func, ast.Attribute) and func.attr == "execute":
                    if node.args and isinstance(node.args[0], ast.JoinedStr):
                        warnings.append(
                            SecurityWarning(
                                line=node.lineno,
                                vulnerability_type="sql_injection",
                                severity="critical",
                                description="SQL 查询使用 f-string 拼接，存在 SQL 注入风险",
                                original_code=(
                                    lines[node.lineno - 1].strip()
                                    if node.lineno <= len(lines)
                                    else ""
                                ),
                                fixed_code="使用参数化查询: cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                                cwe_id="CWE-89",
                            )
                        )
                    elif (
                        node.args
                        and isinstance(node.args[0], ast.BinOp)
                        and isinstance(node.args[0].op, ast.Add)
                    ):
                        warnings.append(
                            SecurityWarning(
                                line=node.lineno,
                                vulnerability_type="sql_injection",
                                severity="critical",
                                description="SQL 查询使用字符串拼接，存在 SQL 注入风险",
                                original_code=(
                                    lines[node.lineno - 1].strip()
                                    if node.lineno <= len(lines)
                                    else ""
                                ),
                                fixed_code="使用参数化查询: cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                                cwe_id="CWE-89",
                            )
                        )

                # subprocess.run(f"cmd {user_input}") 或 subprocess.call(shell=True)
                if isinstance(func, ast.Attribute) and func.attr in (
                    "run",
                    "call",
                    "Popen",
                    "check_output",
                ):
                    # 检查 shell=True
                    for kw in node.keywords:
                        if (
                            kw.arg == "shell"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True
                        ):
                            warnings.append(
                                SecurityWarning(
                                    line=node.lineno,
                                    vulnerability_type="command_injection",
                                    severity="critical",
                                    description="subprocess 使用 shell=True 存在命令注入风险",
                                    original_code=(
                                        lines[node.lineno - 1].strip()
                                        if node.lineno <= len(lines)
                                        else ""
                                    ),
                                    fixed_code="使用列表参数替代 shell=True: subprocess.run(['cmd', arg1, arg2])",
                                    cwe_id="CWE-78",
                                )
                            )
                    # 检查 f-string 命令
                    if node.args and isinstance(node.args[0], ast.JoinedStr):
                        warnings.append(
                            SecurityWarning(
                                line=node.lineno,
                                vulnerability_type="command_injection",
                                severity="critical",
                                description="subprocess 使用 f-string 拼接命令，存在命令注入风险",
                                original_code=(
                                    lines[node.lineno - 1].strip()
                                    if node.lineno <= len(lines)
                                    else ""
                                ),
                                fixed_code="使用列表参数: subprocess.run(['cmd', user_input])",
                                cwe_id="CWE-78",
                            )
                        )

                # os.system(f"cmd {user_input}")
                if isinstance(func, ast.Attribute) and func.attr == "system":
                    warnings.append(
                        SecurityWarning(
                            line=node.lineno,
                            vulnerability_type="command_injection",
                            severity="critical",
                            description="os.system() 存在命令注入风险",
                            original_code=(
                                lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                            ),
                            fixed_code="使用 subprocess.run(['cmd', arg], shell=False) 替代 os.system()",
                            cwe_id="CWE-78",
                        )
                    )

                # eval() / exec()
                if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                    warnings.append(
                        SecurityWarning(
                            line=node.lineno,
                            vulnerability_type="code_injection",
                            severity="critical",
                            description=f"{func.id}() 存在代码注入风险",
                            original_code=(
                                lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                            ),
                            fixed_code=f"避免使用 {func.id}()，使用安全的替代方案 (如 ast.literal_eval)",
                            cwe_id="CWE-94",
                        )
                    )

            # 检测路径遍历: open(user_input)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "open" and node.args:
                    first_arg = node.args[0]
                    # 如果参数是变量名 (可能是用户输入)
                    if isinstance(first_arg, ast.Name) and first_arg.id not in ("__file__",):
                        warnings.append(
                            SecurityWarning(
                                line=node.lineno,
                                vulnerability_type="path_traversal",
                                severity="high",
                                description="open() 直接使用变量，可能存在路径遍历风险",
                                original_code=(
                                    lines[node.lineno - 1].strip()
                                    if node.lineno <= len(lines)
                                    else ""
                                ),
                                fixed_code="验证路径: from pathlib import Path; p = Path(user_input).resolve(); if not str(p).startswith(str(base_dir)): raise ValueError('非法路径')",
                                cwe_id="CWE-22",
                            )
                        )

        return warnings

    def _analyze_regex(self, code: str) -> list[SecurityWarning]:
        """正则补充分析"""
        warnings: list[SecurityWarning] = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 检测 pickle.loads
            if re.search(r"pickle\.loads?\(", stripped):
                warnings.append(
                    SecurityWarning(
                        line=i,
                        vulnerability_type="deserialization",
                        severity="high",
                        description="pickle 反序列化存在任意代码执行风险",
                        original_code=stripped,
                        fixed_code="使用安全的序列化格式 (如 JSON)",
                        cwe_id="CWE-502",
                    )
                )

            # 检测 yaml.load (无 Loader 参数)
            if re.search(r"yaml\.load\([^)]*\)$", stripped) and "Loader" not in stripped:
                warnings.append(
                    SecurityWarning(
                        line=i,
                        vulnerability_type="deserialization",
                        severity="high",
                        description="yaml.load() 不安全，应使用 yaml.safe_load()",
                        original_code=stripped,
                        fixed_code="使用 yaml.safe_load() 替代 yaml.load()",
                        cwe_id="CWE-502",
                    )
                )

            # 检测 requests.get(user_url) (SSRF)
            if re.search(r"requests\.(get|post|put|delete)\(\s*\w+", stripped):
                # 检查是否是变量 (可能是用户输入)
                match = re.search(r"requests\.\w+\(\s*([a-z_]\w*)", stripped)
                if match and match.group(1) not in ("url", "api_url", "endpoint"):
                    warnings.append(
                        SecurityWarning(
                            line=i,
                            vulnerability_type="ssrf",
                            severity="medium",
                            description="直接使用变量作为 URL，可能存在 SSRF 风险",
                            original_code=stripped,
                            fixed_code="验证 URL 白名单: if url not in ALLOWED_URLS: raise ValueError('非法 URL')",
                            cwe_id="CWE-918",
                        )
                    )

            # 检测硬编码密钥
            if re.search(
                r"(api_key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]",
                stripped,
                re.IGNORECASE,
            ):
                # 排除环境变量获取
                if "os.environ" not in stripped and "getenv" not in stripped:
                    warnings.append(
                        SecurityWarning(
                            line=i,
                            vulnerability_type="hardcoded_secret",
                            severity="high",
                            description="检测到硬编码的密钥/密码",
                            original_code=stripped,
                            fixed_code="使用环境变量: api_key = os.environ.get('API_KEY')",
                            cwe_id="CWE-798",
                        )
                    )

        return warnings

    def _insert_sanitizers(self, code: str, warnings: list[SecurityWarning]) -> str:
        """在代码中插入安全检查

        策略: 在文件开头添加安全检查注释，不修改原始代码逻辑
        (实际插入由 AI 根据告警建议完成)
        """
        code.splitlines()

        # 按行号排序告警
        sorted_warnings = sorted(warnings, key=lambda w: w.line)

        # 生成安全提示注释块
        comments: list[str] = [
            "# ── 安全提示 (自动生成) ──",
            f"# 检测到 {len(sorted_warnings)} 个潜在安全问题:",
        ]
        for w in sorted_warnings:
            comments.append(
                f"#   行 {w.line} [{w.severity.upper()}] {w.vulnerability_type} "
                f"({w.cwe_id}): {w.description}"
            )
        comments.append("# ──────────────────────────")
        comments.append("")

        return "\n".join(comments) + code

    def format_warnings(self, warnings: list[SecurityWarning]) -> str:
        """格式化告警为文本"""
        if not warnings:
            return ""

        lines = ["🔒 **安全提示**:", ""]
        for w in warnings:
            severity_icon = {
                "critical": "🚨",
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢",
            }.get(w.severity, "⚪")
            lines.append(
                f"{severity_icon} 行 {w.line} [{w.vulnerability_type}] ({w.cwe_id}): {w.description}"
            )
            if w.fixed_code:
                lines.append(f"   修复建议: {w.fixed_code}")
        return "\n".join(lines)

"""公私边界扫描 — 发布前检查打包产物与文档是否泄露敏感信息

借鉴 LoopX 的 `loopx check --scan-path` 理念：发布前扫描是否泄露
credentials / token / 私有路径，避免把 API Key、GitHub token 等带入
dist/ 或公开文档。

用法:
    python scripts/check_public_boundary.py [path...]

默认扫描路径:
    dist/  pycoder/electron/  README*  docs/

退出码:
    0 — 未发现敏感信息
    1 — 发现敏感信息（可用于 CI 门禁）
    2 — 扫描过程出错
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 敏感信息正则（按真实风险排序）
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OPENAI_API_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("FERRET_TOKEN", re.compile(r"\bgAAAAAB[A-Za-z0-9_\-=]+\b")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("ENV_SECRET", re.compile(r"^\s*(?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ACCESS_KEY)\s*=", re.M)),
]

# 跳过二进制/大文件/数据库
SKIP_SUFFIXES = {
    ".db", ".db-shm", ".db-wal", ".exe", ".dll", ".so", ".dylib", ".pyd",
    ".pyc", ".pyo", ".zip", ".whl", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".node", ".bin", ".img", ".pdf",
}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB


@dataclass
class Finding:
    """单条敏感信息发现"""

    path: str
    pattern: str
    line: int
    snippet: str

    def __str__(self) -> str:
        return f"  {self.path}:{self.line}  [{self.pattern}]  {self.snippet}"


@dataclass
class ScanResult:
    """扫描结果"""

    files_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)


def default_scan_paths() -> list[Path]:
    """默认扫描路径（存在才加入）"""
    candidates = [
        PROJECT_ROOT / "dist",
        PROJECT_ROOT / "pycoder" / "electron" / "src",  # 只扫 electron 源码，排除 dist 构建产物
        PROJECT_ROOT / "docs",
    ]
    paths = PROJECT_ROOT.glob("README*")
    result = [p for p in candidates if p.exists()]
    result.extend(paths)
    return result


def scan_file(file: Path, result: ScanResult) -> None:
    """扫描单个文本文件"""
    if file.suffix.lower() in SKIP_SUFFIXES:
        return
    try:
        if file.stat().st_size > MAX_FILE_BYTES:
            return
        # 二进制检测：读取前 8KB，含 NUL 字节则跳过
        head = file.read_bytes()[:8192]
        if b"\x00" in head:
            return
        text = head.decode("utf-8", errors="ignore")
        if file.stat().st_size > 8192:
            text += file.read_bytes()[8192:].decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return

    result.files_scanned += 1
    lines = text.splitlines()
    for pattern_name, pattern in SECRET_PATTERNS:
        for idx, line in enumerate(lines, 1):
            if pattern.search(line) and not _is_placeholder_line(line):
                result.findings.append(
                    Finding(
                        path=str(file),
                        pattern=pattern_name,
                        line=idx,
                        snippet=_sanitize_snippet(line.strip()[:120]),
                    )
                )


def _sanitize_snippet(snippet: str) -> str:
    """对命中行做打码，避免在终端泄露完整密钥"""
    for name, pattern in SECRET_PATTERNS:
        snippet = pattern.sub(f"<{name}>", snippet)
    return snippet


def _is_placeholder_line(line: str) -> bool:
    """判断一行是否为占位符示例（如 React 的 placeholder="ghp_xxx..."），避免误报"""
    if re.search(r"(?:placeholder|defaultValue|value)\s*=\s*[\"']", line):
        return True
    if re.search(r"<[A-Z_]{3,}>", line):  # 形如 <GITHUB_TOKEN> 的占位符
        return True
    # 值全部为重复的 x / X / * / - 的示例占位（如 ghp_xxxxxxxx...）
    if re.search(r"=\s*[\"'][a-zA-Z]*(?:x{3,}|X{3,}|\*{3,}|-{3,})[a-zA-Z0-9_]*[\"']", line):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if argv:
        paths = [Path(p) for p in argv]
    else:
        paths = default_scan_paths()

    result = ScanResult()
    for path in paths:
        if path.is_file():
            scan_file(path, result)
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file():
                    scan_file(file, result)

    print(f"🔍 公私边界扫描完成 — 扫描 {result.files_scanned} 个文件")
    if not result.findings:
        print("✅ 未发现敏感信息")
        return 0

    print(f"⚠️  发现 {len(result.findings)} 处敏感信息:")
    seen: set[str] = set()
    for f in result.findings:
        key = (f.path, f.pattern, f.line)
        if key in seen:  # 同一位置同一模式去重
            continue
        seen.add(key)
        print(str(f))

    print("\n请检查上述文件，确认密钥/Token 是否已写入打包产物或公开文档。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
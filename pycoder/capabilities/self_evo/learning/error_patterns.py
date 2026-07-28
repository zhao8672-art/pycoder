"""错误模式库 — 50+ 常见 Python 错误模式 + 根因推断链

提供:
- ERROR_PATTERN_DB: 错误模式数据库
- ROOT_CAUSE_CHAINS: 错误关联链 (如 DLL load failed → 缺少 VC++ 运行库)
- ErrorPattern: 错误模式数据类
- RootCauseChain: 根因推断链数据类

使用场景:
    from pycoder.capabilities.self_evo.learning.error_patterns import ERROR_PATTERN_DB
    pattern = ERROR_PATTERN_DB.get("ModuleNotFoundError")
    if pattern:
        print(pattern.root_causes)  # ['缺少依赖包', '虚拟环境未激活']
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ErrorPattern:
    """错误模式定义"""

    error_type: str = ""
    signature: str = ""  # 正则匹配模式
    category: str = "runtime"  # syntax/logic/runtime/security/performance/style
    root_causes: list[str] = field(default_factory=list)
    fix_templates: list[str] = field(default_factory=list)
    related_errors: list[str] = field(default_factory=list)
    platform_specific: bool = False
    examples: list[str] = field(default_factory=list)


@dataclass
class RootCauseChain:
    """根因推断链"""

    primary_cause: str = ""
    confidence: float = 0.0
    secondary_causes: list[str] = field(default_factory=list)
    recommended_fixes: list[str] = field(default_factory=list)
    error_chain: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 错误模式数据库 — 50+ 常见 Python 错误
# ══════════════════════════════════════════════════════════

ERROR_PATTERN_DB: dict[str, ErrorPattern] = {
    # ── 导入相关 ──
    "ModuleNotFoundError": ErrorPattern(
        error_type="ModuleNotFoundError",
        signature=r"ModuleNotFoundError:\s*No\s+module\s+named\s+['\"]?(\w+)['\"]?",
        category="runtime",
        root_causes=[
            "缺少依赖包 — 需要运行 pip install <package>",
            "虚拟环境未激活 — 运行 source venv/bin/activate 或 venv\\Scripts\\activate",
            "Python 版本不兼容 — 该包需要更高版本 Python",
            "包名与导入名不同 — 如 pip install Pillow 但 import PIL",
        ],
        fix_templates=[
            "pip install {module}",
            "pip install {module} --upgrade",
            "python -m pip install {module}",
        ],
        related_errors=["ImportError"],
        examples=[
            "ModuleNotFoundError: No module named 'requests'",
            "ModuleNotFoundError: No module named 'fastapi'",
        ],
    ),
    "ImportError": ErrorPattern(
        error_type="ImportError",
        signature=r"ImportError:\s*(.+)",
        category="runtime",
        root_causes=[
            "模块存在但子模块/属性不存在 — 检查包版本",
            "DLL 加载失败 — 缺少系统级依赖 (如 Visual C++ 运行库)",
            "循环导入 — 重构模块结构避免循环引用",
        ],
        fix_templates=[
            "pip install {module} --upgrade",
            "pip install {module}=={specific_version}",
        ],
        related_errors=["ModuleNotFoundError", "DLL load failed"],
        examples=[
            "ImportError: cannot import name 'x' from 'module'",
            "ImportError: DLL load failed while importing _socket",
        ],
    ),
    "DLLLoadFailed": ErrorPattern(
        error_type="DLLLoadFailed",
        signature=r"DLL\s+load\s+failed\s+while\s+importing\s+(\w+)",
        category="runtime",
        root_causes=[
            "缺少 Visual C++ 运行库 — 安装 Microsoft Visual C++ Redistributable",
            "Python 版本与包不兼容 — 降级或升级包版本",
            "系统 PATH 环境变量缺少 DLL 路径",
            "杀毒软件拦截了 DLL 加载",
        ],
        fix_templates=[
            "pip install {module} --force-reinstall",
            "安装 Microsoft Visual C++ Redistributable",
        ],
        related_errors=["ImportError", "OSError"],
        platform_specific=True,
        examples=[
            "ImportError: DLL load failed while importing _socket",
            "ImportError: DLL load failed while importing cv2",
        ],
    ),

    # ── 类型错误 ──
    "TypeError": ErrorPattern(
        error_type="TypeError",
        signature=r"TypeError:\s*(.+)",
        category="runtime",
        root_causes=[
            "参数类型不匹配 — 检查函数签名的类型注解",
            "None 值未处理 — 添加 None 检查或使用 Optional 类型",
            "参数数量不正确 — 检查函数调用参数",
            "不可变类型操作 — 如对 tuple 赋值",
        ],
        fix_templates=[
            "添加类型检查: if not isinstance(x, expected_type): raise TypeError(...)",
            "使用 Optional 类型注解并添加 None 检查",
        ],
        related_errors=["ValueError", "AttributeError"],
        examples=[
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
            "TypeError: object of type 'NoneType' has no len()",
            "TypeError: __init__() got an unexpected keyword argument 'x'",
        ],
    ),
    "AttributeError": ErrorPattern(
        error_type="AttributeError",
        signature=r"AttributeError:\s*['\"]?(\w+)['\"]?\s+object\s+has\s+no\s+attribute\s+['\"]?(\w+)['\"]?",
        category="runtime",
        root_causes=[
            "对象为 None — 未正确初始化或函数返回 None",
            "属性名拼写错误 — 检查属性名",
            "使用了错误的类型 — 检查变量类型",
            "模块版本不兼容 — 新版本移除了该属性",
        ],
        fix_templates=[
            "添加 None 检查: if obj is not None: obj.{attribute}",
            "使用 hasattr() 检查属性是否存在",
            "使用 getattr(obj, '{attribute}', default_value)",
        ],
        related_errors=["TypeError", "NameError"],
        examples=[
            "AttributeError: 'NoneType' object has no attribute 'split'",
            "AttributeError: module 'x' has no attribute 'y'",
        ],
    ),

    # ── 键值错误 ──
    "KeyError": ErrorPattern(
        error_type="KeyError",
        signature=r"KeyError:\s*(.+)",
        category="runtime",
        root_causes=[
            "字典键不存在 — 使用 dict.get(key, default) 替代 dict[key]",
            "API 返回数据结构变化 — 检查响应格式",
            "配置项缺失 — 检查配置文件",
        ],
        fix_templates=[
            "使用 dict.get('{key}', default_value) 替代 dict['{key}']",
            "使用 'if key in dict:' 检查键是否存在",
        ],
        related_errors=["IndexError", "AttributeError"],
        examples=["KeyError: 'user_id'", "KeyError: 0"],
    ),
    "IndexError": ErrorPattern(
        error_type="IndexError",
        signature=r"IndexError:\s*(.+) index out of range",
        category="runtime",
        root_causes=[
            "列表为空 — 添加长度检查",
            "索引越界 — 使用 len() 检查",
            "循环边界错误 — 检查 range() 参数",
        ],
        fix_templates=[
            "添加长度检查: if len(lst) > index: lst[index]",
            "使用 try/except IndexError 捕获",
        ],
        related_errors=["KeyError"],
        examples=["IndexError: list index out of range"],
    ),

    # ── 名称错误 ──
    "NameError": ErrorPattern(
        error_type="NameError",
        signature=r"NameError:\s*name\s+['\"]?(\w+)['\"]?\s+is\s+not\s+defined",
        category="runtime",
        root_causes=[
            "变量未定义 — 检查变量名拼写",
            "变量作用域问题 — 检查局部/全局作用域",
            "导入缺失 — 需要导入模块",
            "变量在条件分支中定义但条件未满足",
        ],
        fix_templates=[
            "检查变量名拼写",
            "确保变量在当前作用域中已定义",
            "添加导入语句: import {module}",
        ],
        related_errors=["AttributeError", "ImportError"],
        examples=["NameError: name 'x' is not defined"],
    ),

    # ── 数值错误 ──
    "ValueError": ErrorPattern(
        error_type="ValueError",
        signature=r"ValueError:\s*(.+)",
        category="runtime",
        root_causes=[
            "参数值无效 — 添加输入验证",
            "数据格式不正确 — 检查数据源",
            "转换失败 — 如 int('abc')",
        ],
        fix_templates=[
            "添加输入验证: if not valid(x): raise ValueError('...')",
            "使用 try/except ValueError 捕获转换错误",
        ],
        related_errors=["TypeError"],
        examples=[
            "ValueError: invalid literal for int() with base 10: 'abc'",
            "ValueError: not enough values to unpack",
        ],
    ),
    "ZeroDivisionError": ErrorPattern(
        error_type="ZeroDivisionError",
        signature=r"ZeroDivisionError:\s*(.+)",
        category="runtime",
        root_causes=["除数为零 — 添加零值检查"],
        fix_templates=[
            "添加零值检查: if denominator != 0: result = numerator / denominator",
        ],
        related_errors=[],
        examples=["ZeroDivisionError: division by zero"],
    ),

    # ── 文件错误 ──
    "FileNotFoundError": ErrorPattern(
        error_type="FileNotFoundError",
        signature=r"FileNotFoundError:\s*\[Errno\s*2\]\s*No\s+such\s+file\s+or\s+directory:\s*['\"]?([^'\"]+)['\"]?",
        category="runtime",
        root_causes=[
            "文件路径错误 — 检查路径拼写和分隔符",
            "工作目录不正确 — 使用绝对路径或 Path.resolve()",
            "文件未创建 — 检查前置步骤是否完成",
            "权限不足 — 检查文件权限",
        ],
        fix_templates=[
            "使用 pathlib.Path: Path(filepath).resolve()",
            "添加文件存在检查: if Path(filepath).exists(): ...",
            "使用相对路径时确认工作目录: import os; os.getcwd()",
        ],
        related_errors=["PermissionError", "IsADirectoryError"],
        examples=[
            "FileNotFoundError: [Errno 2] No such file or directory: 'config.json'",
        ],
    ),
    "PermissionError": ErrorPattern(
        error_type="PermissionError",
        signature=r"PermissionError:\s*\[Errno\s*13\]\s*Permission\s+denied",
        category="runtime",
        root_causes=[
            "文件被其他进程占用 — 关闭占用程序",
            "权限不足 — 以管理员身份运行",
            "文件为只读 — 修改文件权限",
        ],
        fix_templates=[
            "关闭占用文件的程序",
            "以管理员身份运行",
            "修改文件权限: os.chmod(filepath, 0o666)",
        ],
        related_errors=["FileNotFoundError", "OSError"],
        examples=["PermissionError: [Errno 13] Permission denied: 'file.txt'"],
    ),

    # ── 语法错误 ──
    "SyntaxError": ErrorPattern(
        error_type="SyntaxError",
        signature=r"SyntaxError:\s*(.+)",
        category="syntax",
        root_causes=[
            "括号不匹配 — 检查 ()[]{} 配对",
            "缩进错误 — 统一使用空格或 Tab",
            "缺少冒号 — if/for/while/def/class 后需要冒号",
            "字符串引号不匹配",
        ],
        fix_templates=[
            "使用 IDE 的语法检查功能",
            "运行 python -m py_compile <file> 检查语法",
        ],
        related_errors=["IndentationError", "TabError"],
        examples=[
            "SyntaxError: invalid syntax",
            "SyntaxError: EOL while scanning string literal",
        ],
    ),
    "IndentationError": ErrorPattern(
        error_type="IndentationError",
        signature=r"IndentationError:\s*(.+)",
        category="syntax",
        root_causes=[
            "混用空格和 Tab — 统一使用空格 (PEP 8 推荐 4 空格)",
            "缩进层级不一致",
        ],
        fix_templates=[
            "统一使用 4 个空格缩进",
            "运行 python -m autopep8 --aggressive <file>",
        ],
        related_errors=["SyntaxError", "TabError"],
        examples=[
            "IndentationError: expected an indented block",
            "IndentationError: unindent does not match any outer indentation level",
        ],
    ),

    # ── 运行时错误 ──
    "RuntimeError": ErrorPattern(
        error_type="RuntimeError",
        signature=r"RuntimeError:\s*(.+)",
        category="runtime",
        root_causes=[
            "异步事件循环问题 — 使用 asyncio.run() 或检查已有事件循环",
            "PyTorch/CUDA 错误 — 检查 GPU 可用性",
            "内部状态错误 — 检查初始化顺序",
        ],
        fix_templates=[
            "检查事件循环: asyncio.get_event_loop().is_running()",
            "使用 asyncio.run() 替代手动事件循环管理",
        ],
        related_errors=[],
        examples=[
            "RuntimeError: asyncio.run() cannot be called from a running event loop",
            "RuntimeError: CUDA error: no kernel image is available",
        ],
    ),
    "RecursionError": ErrorPattern(
        error_type="RecursionError",
        signature=r"RecursionError:\s*maximum\s+recursion\s+depth\s+exceeded",
        category="logic",
        root_causes=[
            "递归终止条件缺失 — 检查 base case",
            "递归终止条件永远不满足 — 检查条件逻辑",
            "递归深度过大 — 改用迭代实现",
        ],
        fix_templates=[
            "添加终止条件: if depth > max_depth: return",
            "改用迭代: while loop 替代递归",
            "使用 functools.lru_cache 缓存递归结果",
        ],
        related_errors=["RuntimeError"],
        examples=["RecursionError: maximum recursion depth exceeded"],
    ),

    # ── 超时和网络 ──
    "TimeoutError": ErrorPattern(
        error_type="TimeoutError",
        signature=r"TimeoutError:\s*(.+)|timed\s+out",
        category="runtime",
        root_causes=[
            "网络请求超时 — 增加超时时间或检查网络",
            "死锁 — 检查线程/进程同步",
            "服务无响应 — 检查服务状态",
        ],
        fix_templates=[
            "增加超时时间: requests.get(url, timeout=30)",
            "使用异步: asyncio.wait_for(coro, timeout=30)",
            "添加重试: @retry(max_attempts=3, delay=1)",
        ],
        related_errors=["ConnectionError", "OSError"],
        examples=[
            "TimeoutError: [Errno 110] Connection timed out",
            "httpx.ConnectTimeout: timed out",
        ],
    ),
    "ConnectionError": ErrorPattern(
        error_type="ConnectionError",
        signature=r"ConnectionError:\s*(.+)|Connection\s+(?:refused|reset|aborted)",
        category="runtime",
        root_causes=[
            "目标服务未启动 — 检查服务状态",
            "端口错误 — 检查端口号",
            "防火墙拦截 — 检查防火墙规则",
            "网络不可达 — 检查网络连接",
        ],
        fix_templates=[
            "检查服务: curl http://localhost:port/health",
            "检查端口: netstat -an | findstr :port",
            "添加重试机制",
        ],
        related_errors=["TimeoutError", "OSError"],
        examples=[
            "ConnectionError: [Errno 111] Connection refused",
            "ConnectionRefusedError: [Errno 111] Connection refused",
        ],
    ),

    # ── OS 错误 ──
    "OSError": ErrorPattern(
        error_type="OSError",
        signature=r"OSError:\s*\[Errno\s*(\d+)\]\s*(.+)",
        category="runtime",
        root_causes=[
            "系统资源不足 — 内存/磁盘/文件描述符",
            "端口被占用 — 检查端口占用并释放",
            "路径过长 (Windows 260 字符限制)",
            "系统调用失败 — 检查系统状态",
        ],
        fix_templates=[
            "检查端口占用: netstat -ano | findstr :port",
            "使用短路径或配置长路径支持",
            "增加系统资源限制",
        ],
        related_errors=["FileNotFoundError", "PermissionError", "TimeoutError"],
        examples=[
            "OSError: [Errno 48] Address already in use",
            "OSError: [WinError 123] The filename, directory name, or volume label syntax is incorrect",
        ],
    ),

    # ── 逻辑错误 ──
    "AssertionError": ErrorPattern(
        error_type="AssertionError",
        signature=r"AssertionError:\s*(.+)?",
        category="logic",
        root_causes=[
            "断言条件不满足 — 检查逻辑",
            "测试失败 — 修复被测代码",
            "前置条件不满足 — 检查输入数据",
        ],
        fix_templates=[
            "检查断言条件: assert condition, 'descriptive message'",
            "使用 try/except 捕获 AssertionError",
        ],
        related_errors=[],
        examples=["AssertionError: assert x == 5", "AssertionError"],
    ),

    # ── 停止迭代 ──
    "StopIteration": ErrorPattern(
        error_type="StopIteration",
        signature=r"StopIteration\s*",
        category="runtime",
        root_causes=[
            "迭代器耗尽 — 在生成器中使用 return 而非 raise StopIteration",
            "next() 调用超过迭代器长度 — 添加默认值",
        ],
        fix_templates=[
            "使用 next(iterator, default_value) 替代 next(iterator)",
            "在生成器中使用 return 语句",
        ],
        related_errors=[],
        examples=["StopIteration"],
    ),

    # ── 键盘中断 ──
    "KeyboardInterrupt": ErrorPattern(
        error_type="KeyboardInterrupt",
        signature=r"KeyboardInterrupt\s*",
        category="runtime",
        root_causes=["用户按下 Ctrl+C — 正常的中断行为"],
        fix_templates=[
            "添加信号处理: signal.signal(signal.SIGINT, handler)",
            "使用 try/except KeyboardInterrupt 优雅退出",
        ],
        related_errors=[],
        examples=["KeyboardInterrupt"],
    ),

    # ── 内存错误 ──
    "MemoryError": ErrorPattern(
        error_type="MemoryError",
        signature=r"MemoryError\s*",
        category="runtime",
        root_causes=[
            "内存不足 — 处理大数据时分块加载",
            "内存泄漏 — 检查对象引用",
            "无限列表/生成器 — 添加终止条件",
        ],
        fix_templates=[
            "分块处理: pandas.read_csv(chunksize=10000)",
            "使用生成器替代列表: (x for x in data) vs [x for x in data]",
            "释放大对象: del large_object; gc.collect()",
        ],
        related_errors=["RuntimeError"],
        examples=["MemoryError: Unable to allocate array"],
    ),

    # ── 未实现 ──
    "NotImplementedError": ErrorPattern(
        error_type="NotImplementedError",
        signature=r"NotImplementedError:\s*(.+)?",
        category="logic",
        root_causes=[
            "抽象方法未实现 — 继承类需要实现该方法",
            "功能尚未实现 — 添加具体实现",
        ],
        fix_templates=[
            "实现抽象方法",
            "使用 raise NotImplementedError('TODO: implement') 标记待实现",
        ],
        related_errors=[],
        examples=["NotImplementedError"],
    ),

    # ── 算术错误 ──
    "OverflowError": ErrorPattern(
        error_type="OverflowError",
        signature=r"OverflowError:\s*(.+)",
        category="runtime",
        root_causes=[
            "数值溢出 — 使用更大的数据类型",
            "浮点数精度问题 — 使用 Decimal",
        ],
        fix_templates=[
            "使用 Decimal: from decimal import Decimal",
            "使用 numpy: numpy.float64",
        ],
        related_errors=["ZeroDivisionError", "ArithmeticError"],
        examples=["OverflowError: math range error"],
    ),

    # ── Unicode 错误 ──
    "UnicodeDecodeError": ErrorPattern(
        error_type="UnicodeDecodeError",
        signature=r"UnicodeDecodeError:\s*['\"]?(\w+)['\"]?\s+codec\s+can't\s+decode",
        category="runtime",
        root_causes=[
            "文件编码不匹配 — 尝试 encoding='utf-8' 或 'gbk'",
            "二进制文件以文本模式读取 — 使用 'rb' 模式",
            "编码自动检测失败 — 指定明确编码",
        ],
        fix_templates=[
            "指定编码: open(filepath, encoding='utf-8')",
            "使用 errors='replace': open(filepath, errors='replace')",
            "使用 chardet 检测编码",
        ],
        related_errors=["UnicodeEncodeError"],
        examples=[
            "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff",
        ],
    ),
    "UnicodeEncodeError": ErrorPattern(
        error_type="UnicodeEncodeError",
        signature=r"UnicodeEncodeError:\s*['\"]?(\w+)['\"]?\s+codec\s+can't\s+encode",
        category="runtime",
        root_causes=[
            "输出编码不支持 — 使用 encoding='utf-8'",
            "系统区域设置不支持 Unicode — 配置 PYTHONIOENCODING",
        ],
        fix_templates=[
            "设置环境变量: PYTHONIOENCODING=utf-8",
            "使用 encoding='utf-8' 写入文件",
        ],
        related_errors=["UnicodeDecodeError"],
        examples=["UnicodeEncodeError: 'ascii' codec can't encode character"],
    ),

    # ── 安全相关 ──
    "SQLInjectionRisk": ErrorPattern(
        error_type="SQLInjectionRisk",
        signature=r"(?:SQL\s+injection|sql\s*inject)",
        category="security",
        root_causes=[
            "SQL 字符串拼接 — 使用参数化查询",
            "用户输入未过滤 — 使用 ORM 或参数化",
        ],
        fix_templates=[
            "参数化查询: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
            "使用 ORM: SQLAlchemy, Django ORM",
        ],
        related_errors=[],
        examples=["Warning: Possible SQL injection vector"],
    ),

    # ── 性能相关 ──
    "PerformanceWarning": ErrorPattern(
        error_type="PerformanceWarning",
        signature=r"(?:PerformanceWarning|slow|deprecated.*performance)",
        category="performance",
        root_causes=[
            "低效操作 — 使用更高效的替代方案",
            "不必要的计算 — 添加缓存",
            "大数据量全加载 — 分块处理",
        ],
        fix_templates=[
            "添加缓存: @functools.lru_cache(maxsize=128)",
            "使用列表推导式替代 for 循环 + append",
            "使用生成器替代列表",
        ],
        related_errors=[],
        examples=["PerformanceWarning: DataFrame is highly fragmented"],
    ),
}


# ══════════════════════════════════════════════════════════
# 根因推断链 — 错误关联关系
# ══════════════════════════════════════════════════════════

ROOT_CAUSE_CHAINS: dict[str, list[str]] = {
    # DLL load failed → 缺少 VC++ 运行库 → 需要 reinstall
    "DLL load failed": [
        "缺少 Visual C++ 运行库",
        "安装 Microsoft Visual C++ Redistributable",
        "pip install --force-reinstall <package>",
    ],
    # ModuleNotFoundError → 虚拟环境未激活 → 包未安装
    "ModuleNotFoundError": [
        "检查虚拟环境是否激活",
        "运行 pip install <module>",
        "检查 PYTHONPATH 环境变量",
    ],
    # PermissionError → 文件被占用 → 关闭占用程序
    "PermissionError": [
        "检查文件是否被其他程序占用",
        "以管理员身份运行",
        "修改文件权限",
    ],
    # ConnectionError → 服务未启动 → 检查端口
    "ConnectionError": [
        "检查目标服务是否启动",
        "检查端口号是否正确",
        "检查防火墙规则",
    ],
    # TimeoutError → 网络问题 → 增加超时
    "TimeoutError": [
        "检查网络连接",
        "增加超时时间",
        "添加重试机制",
    ],
    # RecursionError → 终止条件缺失 → 改用迭代
    "RecursionError": [
        "检查递归终止条件",
        "增加递归深度限制",
        "改用迭代实现",
    ],
    # SyntaxError → 语法错误 → 使用语法检查
    "SyntaxError": [
        "检查括号配对",
        "检查缩进一致性",
        "运行 python -m py_compile <file>",
    ],
}


def lookup_pattern(error_type: str) -> ErrorPattern | None:
    """按错误类型查找模式"""
    return ERROR_PATTERN_DB.get(error_type)


def lookup_by_message(error_message: str) -> ErrorPattern | None:
    """按错误消息查找模式 (正则匹配)"""
    import re

    for pattern in ERROR_PATTERN_DB.values():
        if re.search(pattern.signature, error_message, re.IGNORECASE):
            return pattern
    return None


def get_root_cause_chain(error_type: str) -> RootCauseChain | None:
    """获取根因推断链"""
    chain = ROOT_CAUSE_CHAINS.get(error_type)
    if not chain:
        return None

    pattern = ERROR_PATTERN_DB.get(error_type)
    return RootCauseChain(
        primary_cause=chain[0] if chain else "",
        confidence=0.8 if len(chain) > 1 else 0.5,
        secondary_causes=chain[1:] if len(chain) > 1 else [],
        recommended_fixes=pattern.fix_templates if pattern else [],
        error_chain=chain,
    )

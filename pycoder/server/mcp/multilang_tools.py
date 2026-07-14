"""
MCP 多语言执行工具集
"""

from __future__ import annotations

from pycoder.python.multilang_executor import LANG_CONFIG, execute_multilang, list_available


def register_all(register_fn):

    async def _handle_multilang(args: dict) -> dict:
        language = args.get("language", "python")
        code = args.get("code", "")
        timeout = args.get("timeout", 30)
        return await execute_multilang(language, code, timeout)

    register_fn(
        name="execute_multilang",
        description="在沙箱中编译并运行多语言代码（Java/Go/Rust/C/C++/JavaScript/TypeScript/Bash）",
        input_schema={
            "type": "object",
            "properties": {
                "language": {"type": "string", "description": "编程语言"},
                "code": {"type": "string", "description": "完整的源代码"},
                "timeout": {"type": "number", "description": "超时秒数", "default": 30},
            },
            "required": ["language", "code"],
        },
        handler=_handle_multilang,
    )

    async def _handle_list_languages(args: dict) -> dict:
        available = list_available()
        return {
            "success": True,
            "languages": available,
            "count": len(available),
            "all_supported": list(LANG_CONFIG.keys()),
        }

    register_fn(
        name="list_languages",
        description="列出系统中所有可用的编程语言运行时",
        input_schema={"type": "object", "properties": {}},
        handler=_handle_list_languages,
    )

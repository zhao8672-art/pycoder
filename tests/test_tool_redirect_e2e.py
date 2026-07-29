"""端到端测试: 模拟 LLM 调用 head/body/file_read 工具名, 验证重定向、白名单、V2 调用全流程"""

import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_e2e")


async def main():
    # 1. 初始化 V2 引擎 (模拟服务器环境)
    from pycoder.server.app import _init_v2_engine

    print("--- Initializing V2 engine ---")
    v2 = await _init_v2_engine()
    if v2 is None:
        print("V2_INIT: FAILED")
        return
    print(f"V2_INIT: OK ({v2.registry.count} capabilities)")

    # 2. 准备测试文件
    test_dir = Path(r"C:\Users\Administrator\Desktop\game")
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "game.js"
    if not test_file.exists():
        test_file.write_text(
            '// test game.js\nconsole.log("hello from game.js");\n', encoding="utf-8"
        )
    print(f"CREATED_FILE: {test_file}")
    print()

    # 3. 通过 V2 引擎直接调用 (这是 mcp_tools 内部用的方式)
    from pycoder.server.mcp_tools import call_builtin_tool

    test_cases = [
        ("head", {"path": "game/game.js"}),
        ("body", {"path": "game/game.js"}),
        ("file_read", {"path": "game/game.js"}),
        ("tools.file.read", {"path": "game/game.js"}),
        ("read_file", {"path": "game/game.js"}),
        ("tail", {"path": "game/game.js"}),
        # HTML head/body 保留
        ("head", {"title": "Test Page"}),
        ("body", {"div": "content"}),
    ]

    results = []
    for tool_name, tool_args in test_cases:
        try:
            r = await call_builtin_tool(tool_name, tool_args)
            status = "PASS" if r.success else "FAIL"
            output_preview = str(r.output)[:120] if r.output else ""
            print(
                f'  {status}: {tool_name}({list(tool_args.keys())}) -> tool={r.tool}, error={r.error or "none"}'
            )
            if r.success and output_preview:
                print(f"         output_preview: {output_preview}")
            results.append((tool_name, tool_args, r.success, r.error))
        except Exception as e:
            print(f"  EXCEPTION: {tool_name} -> {type(e).__name__}: {e}")
            results.append((tool_name, tool_args, False, str(e)))

    print()
    print("=== SUMMARY ===")
    total = len(results)
    passed = sum(1 for _, _, s, _ in results if s)
    print(f"Total: {total}, Passed: {passed}, Failed: {total - passed}")
    print()
    for tool_name, tool_args, success, error in results:
        marker = "PASS" if success else "FAIL"
        print(f"  {marker}: {tool_name}({list(tool_args.keys())})")
        if not success:
            print(f"         error: {error}")

    # 4. 验证白名单状态
    print()
    print("=== Whitelist Status ===")
    from pycoder.safety.tool_whitelist import get_tool_whitelist

    wl = get_tool_whitelist()
    stats = wl.get_stats()
    print(f'  mode: {stats["mode"]}')
    print(f'  allowed_tools_count: {stats["allowed_tools_count"]}')
    print(f'  denied_tools_count: {stats["denied_tools_count"]}')
    print(f'  audit_total: {stats["audit_total"]}')
    print(f'  audit_allowed: {stats["audit_allowed"]}')
    print(f'  audit_denied: {stats["audit_denied"]}')


if __name__ == "__main__":
    asyncio.run(main())

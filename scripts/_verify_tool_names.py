"""验证所有工具名符合 API 要求（无点号）"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYCODER_API_KEY"] = "disabled"

from pycoder.server.mcp_tools import list_builtin_tools
tools = list_builtin_tools()
bad = [t["name"] for t in tools if "." in t["name"]]
print(f"Total tools: {len(tools)}")
print(f"Tools with dots: {len(bad)}")
if bad:
    print(f"BAD: {bad[:10]}")
else:
    print("ALL NAMES VALID - no dots in any tool name")
print(f"Sample: {[t['name'] for t in tools[:5]]}")

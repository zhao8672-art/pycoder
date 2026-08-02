"""单元测试：DSML 回退解析"""
import sys
sys.path.insert(0, r"c:\Users\Administrator\Desktop\pycode")

from pycoder.server.chat_bridge_stream import parse_dsml_tool_calls

# 测试 1: 单个 DSML invoke
text1 = """我来帮您分析项目。
<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="file_list">
<｜｜DSML｜｜parameter name="path" string="true">.</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>
这是扫描结果。"""

cleaned, calls, found = parse_dsml_tool_calls(text1)
print("=== 测试 1: 单个 invoke ===")
print("found:", found)
print("cleaned:")
print(cleaned)
print("calls:")
for c in calls:
    print(f"  - id={c['id']} name={c['function']['name']} args={c['function']['arguments']}")
print()

# 测试 2: 多个 invoke
text2 = """开始扫描：
<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="file_list">
<｜｜DSML｜｜parameter name="path" string="true">pycoder</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="git_status">
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="shell_run">
<｜｜DSML｜｜parameter name="command" string="true">echo PING_OK</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>
完成。"""

cleaned, calls, found = parse_dsml_tool_calls(text2)
print("=== 测试 2: 多个 invoke ===")
print("found:", found)
print("cleaned:")
print(cleaned)
print("calls:")
for c in calls:
    print(f"  - id={c['id']} name={c['function']['name']} args={c['function']['arguments']}")
print()

# 测试 3: 无 DSML
text3 = "这是普通文本，没有 DSML 标签。"
cleaned, calls, found = parse_dsml_tool_calls(text3)
print("=== 测试 3: 无 DSML ===")
print("found:", found)
print("cleaned:", repr(cleaned))
print("calls:", calls)
print()

# 测试 4: 关键字检测
from pycoder.server.chat_bridge import ChatBridge
b = ChatBridge()
test_messages = [
    "重新自查系统的优缺点",
    "分析项目",
    "检查代码",
    "你好",
    "列出文件",
]
print("=== 测试 4: 关键字检测 ===")
for m in test_messages:
    mode, tools, rounds = b._classify_intent(m)
    print(f"  '{m}' → mode={mode} tools={tools} rounds={rounds}")

"""验证 AI 策略重构"""
from pycoder.server.chat_bridge import ChatBridge

print("=== 意图分类测试 ===")
b = ChatBridge()
tests = [
    ("你好", "chat", False),
    ("hello world", "chat", False),
    ("今天天气怎么样", "chat", False),
    ("你能做什么", "chat", False),
    ("Python中装饰器怎么用", "chat", False),
    ("写一个Python脚本读取文件并分析数据", "tool", True),
    ("修改app.py中的第50行代码", "tool", True),
    ("搜索项目中所有TODO注释", "tool", True),
    ("运行测试并修复失败的用例", "tool", True),
    ("帮我创建一个FastAPI项目结构", "tool", True),
]
for msg, exp_mode, exp_tools in tests:
    mode, tools, rounds = b._classify_intent(msg)
    ok = "OK" if mode == exp_mode and tools == exp_tools else "FAIL"
    print(f"  [{ok}] {msg[:40]:40s} -> mode={mode:5s} tools={tools!s:5s} rounds={rounds}")

print("\n=== 所有测试完成 ===")

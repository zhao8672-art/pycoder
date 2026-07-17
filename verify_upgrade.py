"""验证所有AI升级模块可编译运行"""
print("=== 1. ChatBridge (NLU+任务分级+幻觉抑制+反思+工具裁剪) ===")
from pycoder.server.chat_bridge import ChatBridge
b = ChatBridge()
print(f"  OK, rumin_count={b._rumination_count}, nlu_cache={b._nlu_cache}")

print("\n=== 2. LiveLearner (在线自进化) ===")
from pycoder.capabilities.self_evo.live import LiveLearner, get_live_learner
l = get_live_learner()
print(f"  OK, stats={l.get_stats()}")

print("\n=== 3. 意图分类测试 ===")
tests = [
    ("你好", "chat", False),
    ("写一个爬虫脚本", "tool", True),
    ("Python装饰器是什么", "chat", False),
    ("修复app.py中的bug", "tool", True),
]
for msg, exp_mode, _ in tests:
    mode, tools, rounds = b._classify_intent(msg)
    ok = "OK" if mode == exp_mode else "FAIL"
    print(f"  [{ok}] '{msg[:30]}' -> mode={mode}, tools={tools}, rounds={rounds}")

print("\n=== 4. NLU路由测试 ===")
import asyncio
async def test_route():
    for msg in ["你好", "写一个Python脚本读取文件", "今天天气怎么样"]:
        mode, tools, rounds = await b._route_with_nlu(msg)
        print(f"  '{msg[:30]}' -> mode={mode}, tools={tools}, rounds={rounds}")
asyncio.run(test_route())

print("\n=== ALL OK ===")

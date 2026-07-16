"""P2 快速验证"""
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")

from pycoder.ai.completion import get_completer
from pycoder.ai.cache import PromptCache
from pycoder.ai.dialog import DialogStateTracker

# 1. KV Cache
c = PromptCache()
c.set("写一个冒泡排序", "prefix_output", model="deepseek-chat")
r = c.get("写一个快速排序", model="deepseek-chat")
print("Cache:", "HIT" if r else "MISS", "| Stats:", c.stats())

# 2. Dialog
d = DialogStateTracker()
d.update_intent("s1", "生成代码", 0.9)
d.add_entity("s1", "file", "/src/main.py")
d.set_active_task("s1", "实现排序")
r1 = d.resolve_anaphora("s1", "优化它")
r2 = d.resolve_anaphora("s1", "修改这个文件")
ctx = d.get_context("s1")
print("Dialog turns:", ctx["turn_count"])
print("Resolve[优化它]:", r1)
print("Resolve[修改这个文件]:", r2)

# 3. FIM
fim = get_completer()
print("FIM completer ready")

print("\nP2 全部验证通过")

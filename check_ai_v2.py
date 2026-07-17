"""检查 AI 功能 — 详细输出"""
import json
import urllib.request


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


# 健康检查
h = get("http://127.0.0.1:8423/api/health")
print(f"[健康] status={h['status']}")

# 模型
m = get("http://127.0.0.1:8423/api/models")
avail = [x["id"] for x in m["models"] if x["available"]]
print(f"[模型] 推荐={m['recommended_model']} 可用={avail}")

# 测试1: 简单问候（应该是 chat 模式，0 轮工具）
print("\n=== 测试: '你好' (期望: 直接回复, 无工具调用) ===")
r = post("http://127.0.0.1:8423/api/chat", {"message": "你好", "model": "auto"})
reply = r.get("reply", "")
# 检查是否包含旧版标志
has_old = "🔄 第" in reply and "轮工具调用" in reply
print(f"  旧版标志={has_old} model={r.get('model')}")
print(f"  回复前150字: {reply[:150]}")
print(f"  结果: {'❌ 仍有旧版5轮标志' if has_old else '✅ 直接回复'}")

# 测试2: 代码需求（应为 tool 模式）
print("\n=== 测试: '读取README.md并总结' (期望: 使用工具) ===")
r2 = post("http://127.0.0.1:8423/api/chat", {"message": "读取项目根目录的README.md文件并简要总结", "model": "auto"})
reply2 = r2.get("reply", "")
has_tool = "🔧 执行" in reply2 or "read_file" in reply2.lower()
print(f"  使用了工具={has_tool}")
print(f"  回复前200字: {reply2[:200]}")

print("\n✅ 检查完成")


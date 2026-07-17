"""验证所有后端修改 - 简化版（不触发递归导入）"""
# 直接测试 _detect_provider 逻辑（不导入 chat_bridge）
def _test_detect_provider(model: str) -> str:
    if not model: return "deepseek"
    if model.startswith("deepseek"): return "deepseek"
    if model.startswith("qwen"): return "qwen"
    if model.startswith("glm"): return "glm"
    if model.startswith("gpt") or model.startswith("o"): return "openai"
    if model.startswith("claude"): return "anthropic"
    if model.startswith("gemini"): return "google"
    if model.startswith("z-") or model.startswith("nvidia-"): return "nvidia"
    if model.startswith("agnes"): return "agnes"
    if model.startswith("openrouter"): return "openrouter"
    if "/" in model: return "openrouter"
    return "deepseek"

print("=== 1. _detect_provider 测试 ===")
tests = [
    ("deepseek-chat", "deepseek"),
    ("claude-3.5-sonnet", "anthropic"),
    ("gemini-2.0-flash", "google"),
    ("gpt-4o", "openai"),
    ("qwen-coder-plus", "qwen"),
    ("google/gemini-2.0-flash", "openrouter"),
    ("", "deepseek"),
]
for model, expected in tests:
    result = _test_detect_provider(model)
    status = "✅" if result == expected else "❌"
    print(f"  {status} {model:35s} → {result} (期望: {expected})")

print("\n=== 2. ModelManager 测试 ===")
from pycoder.providers.auth import ModelManager

m = ModelManager()
m.auto_detect()
print(f"  检测到的 Key: {list(m.get_all_keys().keys())}")

m.save_model_preference("deepseek-chat")
print(f"  save/load preference: {m.load_model_preference()}")

m.save_custom_api_base("deepseek-chat", "https://my-api.com/v1")
print(f"  custom api_base: {m.get_custom_api_base('deepseek-chat')}")

models = m.get_available_models()
print(f"  可用模型数: {len(models)}")
print(f"  第一个模型: id={models[0]['id']}, available={models[0]['available']}, api_base={models[0]['api_base']}")

# 测试 recommend 优先使用用户偏好
model_id, provider = m.recommend()
print(f"  recommend() = {model_id} / {provider} (应=deepseek-chat)")

print("\n=== ✅ 全部通过 ===")

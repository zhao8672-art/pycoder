"""快速模块完整性检查"""
import sys
modules = [
    "pycoder.providers.auth",
    "pycoder.server.chat_bridge",
    "pycoder.server.chat_handler",
    "pycoder.server.ws_handler",
    "pycoder.server.ws_handler_v2",
    "pycoder.server.routers.config",
    "pycoder.server.routers.chat_routes",
    "pycoder.server.app",
    "pycoder.ai.rumination",
    "pycoder.capabilities.self_evo.live",
    "pycoder.ai.nlu.composite_nlu",
    "pycoder.ai.fusion.engine",
    "pycoder.ai.analysis.composite_analyzer",
    "pycoder.ai.completion.fim_engine",
    "pycoder.server.services.hallucination_guard",
    "pycoder.server.services.task_grader",
]
for m in modules:
    try:
        __import__(m)
        print(f"  ✅ {m}")
    except Exception as e:
        print(f"  ❌ {m}: {str(e)[:80]}")
print(f"\n模块总计: {len(modules)}")

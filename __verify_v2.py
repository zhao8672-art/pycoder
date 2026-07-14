"""V2 演进验证 — 检查所有新增模块导入和集成点"""
import sys
import traceback

modules = [
    # V2 核心
    ("pycoder.v2", "V2 引擎"),
    ("pycoder.brain", "AI 大脑"),
    ("pycoder.bus", "能力总线"),
    ("pycoder.safety", "安全体系"),
    ("pycoder.capabilities", "能力系统"),
    ("pycoder.modules", "动态模块"),
    # V2 桥接
    ("pycoder.server.v2_bridge", "V2 工具桥接"),
    ("pycoder.server.ws_handler_v2", "V2 WebSocket 处理器"),
    # 集成点
    ("pycoder.server.services.team.team_coordinator", "团队协调器 (+V2执行)"),
    ("pycoder.server.app", "应用入口 (+V2端点)"),
]

passed = 0
failed = 0
for mod, desc in modules:
    try:
        __import__(mod)
        print(f"  ✅ {desc} ({mod})")
        passed += 1
    except Exception as e:
        print(f"  ❌ {desc} ({mod}): {e}")
        traceback.print_exc()
        failed += 1


# ── 功能级验证函数 ──


def _check_v2_init():
    from pycoder.v2 import V2Engine, V2EngineConfig
    config = V2EngineConfig()
    engine = V2Engine(config)
    assert engine.registry is not None
    assert engine.permission is not None
    assert engine.consciousness is not None
    assert engine.orchestrator is not None


def _check_tool_bridge():
    from pycoder.server.v2_bridge import bridge_mcp_to_v2
    assert callable(bridge_mcp_to_v2)


def _check_ws_v2():
    from pycoder.server.ws_handler_v2 import websocket_chat_v2
    assert callable(websocket_chat_v2)


def _check_team_v2():
    from pycoder.server.services.team.team_coordinator import execute_with_v2_brain
    assert callable(execute_with_v2_brain)


# ── 功能级验证 ──
checks = [
    ("V2 引擎初始化", lambda: _check_v2_init()),
    ("工具桥接批量注册", lambda: _check_tool_bridge()),
    ("WebSocket V2 端点存在", lambda: _check_ws_v2()),
    ("TeamCoordinator V2 执行路径", lambda: _check_team_v2()),
]

print("\n功能验证:")
for name, fn in checks:
    try:
        fn()
        print(f"  ✅ {name}")
        passed += 1
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        failed += 1

print(f"\n{'=' * 50}")
print(f"Result: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
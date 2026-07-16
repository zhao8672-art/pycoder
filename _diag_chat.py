"""诊断: 测试 ChatBridge.chat_stream 是否正常工作"""
import asyncio
import osos.environ["PYCODER_CLOUD_JWT_SECRET"] = "test-secret-for-diag"

async def main():
    print("=== 测试 ChatBridge.chat_stream ===")
    from pycoder.server.chat_bridge import ChatBridge
    
    bridge = ChatBridge()
    bridge.configure(model="deepseek-chat")
    
    # Check key status
    print(f"bridge.config.api_key: {'SET' if bridge.config.api_key else 'NOT SET'}")
    print(f"bridge.config.model: {bridge.config.model}")
    print(f"bridge.config.api_base: {bridge.config.api_base}")
    
    # Test stream
    count = 0
    try:
        async for ev in bridge.chat_stream("你好，请用一句话介绍你自己"):
            count += 1
            if ev.event_type == "token":
                print(f"[TOKEN] {ev.content[:100]}")
            elif ev.event_type == "error":
                print(f"[ERROR] {ev.content[:200]}")
                break
            elif ev.event_type == "done":
                print(f"[DONE] content_len={len(ev.content)}")
                print(f"[DONE] usage={ev.usage}")
                break
            elif ev.event_type == "reasoning":
                print(f"[REASONING] {ev.content[:100]}")
    except Exception as e:
        print(f"[EXCEPTION] {type(e).__name__}: {e}")
    
    print(f"\nReceived {count} events")
    print("\n=== DONE ===")

asyncio.run(main())

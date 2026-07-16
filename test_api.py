import httpx, asyncio, json

"""测试AI功能"""
async def test():
    api_key = "REDACTED-PYCODER-API-KEY"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    # 1. 测试聊天 API
    print("=== Test 1: Chat API (agnes-2.0-flash) ===")
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "http://127.0.0.1:8423/api/chat",
                headers=headers,
                json={"message": "回复OK即可", "model": "agnes-2.0-flash"}
            )
            print(f"  状态: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"  回复: {json.dumps(data, ensure_ascii=False)[:200]}")
            else:
                print(f"  错误: {r.text[:300]}")
    except Exception as e:
        print(f"  异常: {e}")

    # 2. 测试 config/keys
    print("\n=== Test 2: Config Keys ===")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("http://127.0.0.1:8423/api/config/keys")
            d = r.json()
            print(f"  推荐模型: {d['recommended_model']}")
            print(f"  有Key: {d['has_any_key']}")
    except Exception as e:
        print(f"  异常: {e}")

    # 3. 测试 models
    print("\n=== Test 3: Models API ===")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("http://127.0.0.1:8423/api/models")
            d = r.json()
            models = list(d.keys())[:5]
            print(f"  可用模型: {models}")
    except Exception as e:
        print(f"  异常: {e}")

asyncio.run(test())

"""测试 Key 是否有效"""
import httpx, asyncio

KEY = "sk-REDACTED-DEEPSEEK"

async def test():
    async with httpx.AsyncClient(timeout=15) as c:
        # Test OpenAI
        try:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json={"model": "gpt-4o-mini", "messages": [{"role":"user","content":"回复OK"}], "max_tokens":20}
            )
            print(f"OpenAI: HTTP {r.status_code}")
            if r.status_code == 200:
                print("  ✅ 有效! 回复:", r.json()["choices"][0]["message"]["content"])
            else:
                print("  ❌ 无效:", r.text[:200])
        except Exception as e:
            print(f"  ❌ 异常: {e}")

        # Test DeepSeek
        try:
            r = await c.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json={"model": "deepseek-chat", "messages": [{"role":"user","content":"回复OK"}], "max_tokens":20}
            )
            print(f"DeepSeek: HTTP {r.status_code}")
            if r.status_code == 200:
                print("  ✅ 有效!")
            else:
                print("  ❌ 无效:", r.text[:200])
        except Exception as e:
            print(f"  ❌ 异常: {e}")

asyncio.run(test())

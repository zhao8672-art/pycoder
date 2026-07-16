import httpx, asyncio, json
async def t():
    api_key = "REDACTED-PYCODER-API-KEY"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("http://127.0.0.1:8423/api/chat",
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={"message": "用中文回复一句话就够了", "model": "agnes-2.0-flash"})
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print("OK:", json.dumps(d, ensure_ascii=False)[:300])
        else:
            print("ERR:", r.text[:300])
asyncio.run(t())

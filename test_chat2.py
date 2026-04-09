import asyncio, httpx
async def req():
    async with httpx.AsyncClient() as c:
        r2 = await c.post("http://localhost:8000/chat", json={
            "messages": [
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "hello again"}
            ],
            "selectedName": None,
            "activeScore": None
        })
        print("Chat response:", r2.text)

asyncio.run(req())

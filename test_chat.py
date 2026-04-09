import asyncio, httpx
async def req():
    async with httpx.AsyncClient() as c:
        # 1. get full score for Virginia Tech
        r1 = await c.post("http://localhost:8000/score", json={"university_name": "Virginia Tech"})
        score = r1.json()
        print("Score fetched")
        
        # 2. send chat
        r2 = await c.post("http://localhost:8000/chat", json={
            "messages": [{"role": "user", "content": "What do you think about this specific market right now?"}],
            "selectedName": "Virginia Tech",
            "activeScore": score
        })
        print("Chat response:", r2.text)

asyncio.run(req())

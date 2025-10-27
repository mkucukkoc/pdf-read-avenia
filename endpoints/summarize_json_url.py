import json
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL


@app.post("/summarize-json-url/")
async def summarize_json_from_url(data: dict = Body(...)):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            json_data = await resp.json()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu JSON verisinin ne ifade ettiğini açıkla:"},
            {"role": "user", "content": json.dumps(json_data)[:3000]}
        ],
    )
    return { "full_text": response.choices[0].message.content }

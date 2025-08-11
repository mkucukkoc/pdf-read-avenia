import aiohttp
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL


@app.post("/summarize-html-url/")
async def summarize_html_from_url(data: dict = Body(...)):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu web sayfasının içeriğini özetle:"},
            {"role": "user", "content": text[:3000]}
        ],
    )
    return { "full_text": response.choices[0].message.content }

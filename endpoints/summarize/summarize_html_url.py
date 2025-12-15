import logging
import aiohttp
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_html_url")


@app.post("/summarize-html-url/")
async def summarize_html_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize HTML URL request received", extra={"url": url})
    if not url:
        logger.warning("HTML URL missing")
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    logger.debug("Extracted HTML text", extra={"length": len(text)})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu web sayfasının içeriğini özetle:"},
            {"role": "user", "content": text[:3000]},
        ],
    )
    summary = response.choices[0].message.content
    response_payload = {"full_text": summary}
    logger.info("HTML summary generated", extra={"summary_length": len(summary)})
    logger.debug("Summarize HTML response payload", extra={"response": response_payload})
    return response_payload








import json
import logging
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_json_url")


@app.post("/summarize-json-url/")
async def summarize_json_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize JSON URL request received", extra={"url": url})
    if not url:
        logger.warning("JSON URL missing")
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            json_data = await resp.json()
    logger.debug("JSON data fetched", extra={"keys": list(json_data.keys())[:10]})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu JSON verisinin ne ifade ettiğini açıkla:"},
            {"role": "user", "content": json.dumps(json_data)[:3000]},
        ],
    )
    summary = response.choices[0].message.content
    response_payload = {"full_text": summary}
    logger.info("JSON summary generated", extra={"summary_length": len(summary)})
    logger.debug("Summarize JSON response payload", extra={"response": response_payload})
    return response_payload





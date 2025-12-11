import logging
import pandas as pd
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_csv_url")


@app.post("/summarize-csv-url/")
async def summarize_csv_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize CSV URL request received", extra={"url": url})
    if not url:
        logger.warning("CSV URL missing")
        raise HTTPException(status_code=400, detail="URL not provided")

    df = pd.read_csv(url)
    summary = df.describe(include="all").to_string()
    logger.debug("CSV summary generated", extra={"length": len(summary)})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu CSV dosyasını analiz et ve önemli verileri özetle:"},
            {"role": "user", "content": summary},
        ],
    )
    text = response.choices[0].message.content
    response_payload = {"full_text": text}
    logger.info("CSV summary generated", extra={"summary_length": len(text)})
    logger.debug("Summarize CSV response payload", extra={"response": response_payload})
    return response_payload





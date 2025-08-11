import pandas as pd
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL


@app.post("/summarize-csv-url/")
async def summarize_csv_from_url(data: dict = Body(...)):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    df = pd.read_csv(url)
    summary = df.describe(include='all').to_string()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu CSV dosyasını analiz et ve önemli verileri özetle:"},
            {"role": "user", "content": summary}
        ],
    )
    return { "full_text": response.choices[0].message.content }

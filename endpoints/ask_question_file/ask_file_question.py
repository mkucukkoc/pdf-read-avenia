import logging
from fastapi import Form, HTTPException
from fastapi.responses import JSONResponse
from main import app, client, DEFAULT_MODEL

logger = logging.getLogger("pdf_read_refresh.endpoints.ask_file_question")


@app.post("/ask-question")
async def ask_file_question(
    file_text: str = Form(...),
    question: str = Form(...),
    file_type: str = Form(default="genel")  # örnek: 'PDF', 'Word', 'Excel', 'PPT'
):
    logger.info(
        "Ask file question request received",
        extra={
            "question": question,
            "file_type": file_type,
            "text_length": len(file_text),
        },
    )

    prompt = f"""\nAşağıda bir {file_type.upper()} dosyasının içeriği bulunmaktadır. Kullanıcı bu içeriğe dayanarak bir soru sordu.\n\nLütfen sadece verilen içerikten yararlanarak doğru, detaylı ve anlaşılır bir cevap ver.\n\n📄 Dosya içeriği:\n\"\"\"\n{file_text[:4000]}\n\"\"\"\n\n❓ Soru:\n\"\"\"\n{question}\n\"\"\"\n\n💬 Cevap:\n"""

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Sana bir {file_type} dosyasının metinsel içeriği verildi. Sadece bu içeriğe dayanarak soruları yanıtla. Tahmin yürütme veya içerik dışında yorum yapma."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        answer = response.choices[0].message.content.strip()
        logger.info("Ask file question succeeded", extra={"answer_length": len(answer)})
        response_payload = {"answer": answer}
        logger.debug("Ask file question response payload", extra={"response": response_payload})
        return JSONResponse(content=response_payload)

    except Exception as e:
        logger.exception("Ask file question failed")
        raise HTTPException(status_code=500, detail=str(e))

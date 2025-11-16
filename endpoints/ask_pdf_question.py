import logging
from fastapi import Form, HTTPException
from fastapi.responses import JSONResponse
from main import app, client, DEFAULT_MODEL

logger = logging.getLogger("pdf_read_refresh.endpoints.ask_pdf_question")


@app.post("/ask-question")
async def ask_pdf_question(pdf_text: str = Form(...), question: str = Form(...)):
    logger.info(
        "Ask PDF question request received",
        extra={"question": question, "pdf_text_length": len(pdf_text)},
    )

    prompt = f"""\nSen PDF belgesi içeriğini analiz eden bir asistansın. Kullanıcının sorusu aşağıda. Sadece PDF içeriğine dayanarak cevap ver:\n\n📄 PDF içeriği:\n\"\"\"\n{pdf_text[:4000]}\n\"\"\"\n\n❓ Soru:\n{question}\n\n💬 Cevabın:\n"""

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Sen uzman bir PDF içeriği analistisin, sadece verilen içerikten faydalan."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content.strip()
        logger.info("Ask PDF question succeeded", extra={"answer_length": len(answer)})
        response_payload = {"answer": answer}
        logger.debug("Ask PDF question response payload", extra={"response": response_payload})
        return JSONResponse(content=response_payload)

    except Exception as e:
        logger.exception("Ask PDF question failed")
        raise HTTPException(status_code=500, detail=str(e))

import io
import logging
from fastapi import Body, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from firebase_admin import firestore
from fpdf import FPDF
from main import app

logger = logging.getLogger("pdf_read_refresh.endpoints.export_chat")


@app.post("/export-chat")
async def export_chat(payload: dict = Body(...)):
    logger.info("Export chat request received", extra={"payload": payload})
    try:
        user_id = payload.get("user_id")
        chat_id = payload.get("chat_id")
        logger.info("Export chat parameters", extra={"user_id": user_id, "chat_id": chat_id})

        if not user_id or not chat_id:
            return JSONResponse(status_code=400, content={"error": "user_id and chat_id are required"})

        db = firestore.client()
        messages_ref = (
            db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
            .collection("messages")
            .order_by("timestamp")
        )
        docs = list(messages_ref.stream())
        logger.info("Messages found", extra={"count": len(docs)})
        if not docs:
            return JSONResponse(status_code=404, content={"error": "No messages found"})

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for d in docs:
            data = d.to_dict() or {}
            role = data.get("role", "")
            content = data.get("content", "")
            line = f"{role}: {content}"
            pdf.multi_cell(0, 10, line)

        pdf_bytes = pdf.output(dest="S").encode("latin-1")
        pdf_io = io.BytesIO(pdf_bytes)
        headers = {"Content-Disposition": f"attachment; filename=chat_{chat_id}.pdf"}
        logger.info("PDF generated", extra={"chat_id": chat_id})
        return StreamingResponse(pdf_io, media_type="application/pdf", headers=headers)

    except Exception as e:
        logger.exception("Export chat failed")
        raise HTTPException(status_code=500, detail=str(e))

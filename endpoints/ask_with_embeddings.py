import logging
from fastapi import Form
from main import app, create_embedding, cosine_similarity, client, DEFAULT_MODEL
from firebase_admin import firestore

logger = logging.getLogger("pdf_read_refresh.endpoints.ask_with_embeddings")


@app.post("/ask-with-embeddings/")
async def ask_with_embeddings(
    question: str = Form(...),
    file_id: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...),
):
    db = firestore.client()
    logger.info(
        "Ask with embeddings request received",
        extra={"user_id": user_id, "chat_id": chat_id, "file_id": file_id},
    )

    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    logger.debug("Firestore path built", extra={"path": f"embeddings/{user_id}/{chat_id}"})

    try:
        q_embedding = create_embedding(question)
        logger.debug("Question embedding created", extra={"size": len(q_embedding)})
    except Exception as e:
        logger.exception("Question embedding failed")
        raise

    try:
        docs = base_ref.where("file_id", "==", file_id).stream()
        logger.info("Fetching chunks from Firestore")

        chunks = []
        for doc in docs:
            data = doc.to_dict()
            if data.get("chunk_index", 0) >= 0:
                score = cosine_similarity(q_embedding, data["embedding"])
                chunks.append((score, data["text"]))
                logger.debug(
                    "Chunk score calculated",
                    extra={"score": score, "preview": data["text"][:60]},
                )
    except Exception as e:
        logger.exception("Fetching chunks failed")
        raise

    top_chunks = [text for score, text in sorted(chunks, key=lambda x: x[0], reverse=True)[:3]]
    logger.info("Top chunks selected", extra={"count": len(top_chunks)})
    for i, tc in enumerate(top_chunks):
        logger.debug("Top chunk preview", extra={"index": i + 1, "preview": tc[:100]})

    context = "\n".join(top_chunks)
    prompt = f"""\nBağlama dayanarak soruya yanıt ver. Doğrudan cevap yoksa en yakın bilgiyi özetle:\n{context}\n\nSoru: {question}\n"""
    logger.debug("Submitting GPT prompt", extra={"prompt_preview": prompt[:300]})

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Sen bağlam tabanlı bir asistansın."},
                {"role": "user", "content": prompt},
            ],
        )
        answer = response.choices[0].message.content
        logger.info("Ask with embeddings GPT answer generated", extra={"answer_preview": answer[:200]})
    except Exception as e:
        logger.exception("Ask with embeddings GPT call failed")
        raise

    response_payload = {"answer": answer, "context_used": top_chunks}
    logger.debug("Ask with embeddings response payload", extra={"response": response_payload})
    return response_payload

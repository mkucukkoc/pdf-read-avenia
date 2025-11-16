import logging

from fastapi import Form
from main import app, create_embedding, cosine_similarity
from firebase_admin import firestore

logger = logging.getLogger("pdf_read_refresh.endpoints.search_docs")


@app.post("/search-docs/")
async def search_docs(
    query: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...),
    top_k: int = Form(5),
):
    """Search saved documents using summary embeddings as an index."""
    db = firestore.client()
    logger.info(
        "Search docs request",
        extra={"user_id": user_id, "chat_id": chat_id, "query": query, "top_k": top_k},
    )

    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    logger.debug("Firestore path resolved", extra={"path": f"embeddings/{user_id}/{chat_id}"})

    try:
        q_embedding = create_embedding(query)
        logger.debug("Query embedding created", extra={"size": len(q_embedding)})

        docs = base_ref.where("chunk_index", "==", -1).stream()
        logger.info("Fetching summary embeddings for search")

        index = []
        for doc in docs:
            data = doc.to_dict()
            file_id = data.get("file_id")
            summary_text = data.get("text", "")
            score = cosine_similarity(q_embedding, data["embedding"])
            logger.debug(
                "Appending search candidate",
                extra={"file_id": file_id, "score": score},
            )
            index.append({"file_id": file_id, "score": score, "summary": summary_text})

        index.sort(key=lambda x: x["score"], reverse=True)
        top_results = index[:top_k]
        logger.info(
            "Search docs results ready",
            extra={"returned": len(top_results)},
        )
        return {"results": top_results}
    except Exception as e:
        logger.exception("Search docs failed")
        raise
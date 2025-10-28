from fastapi import Form
from main import app, create_embedding, cosine_similarity
from firebase_admin import firestore

## adamın chatid ve userid ile o chatda ki dokumanlar girdiiğin kelime geçen dökuman bulunuyor bulunuyor.

@app.post("/search-docs/")
async def search_docs(
    query: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...),
    top_k: int = Form(5)
):
    """Search saved documents using summary embeddings as an index."""
    db = firestore.client()

    print("\n[search-docs] 📥 İstek alındı")
    print(f"   → user_id: {user_id}")
    print(f"   → chat_id: {chat_id}")
    print(f"   → query: {query}")

    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    print(f"[search-docs] 🔗 Firestore path: embeddings/{user_id}/{chat_id}")

    try:
        q_embedding = create_embedding(query)
        print(f"[search-docs] 🧠 Sorgu embedding boyutu: {len(q_embedding)}")

        # Use summary embeddings (chunk_index = -1) as document index
        docs = base_ref.where("chunk_index", "==", -1).stream()
        print("[search-docs] 🔎 Özet embedding'ler çekiliyor...")

        index = []
        for doc in docs:
            data = doc.to_dict()
            file_id = data.get("file_id")
            summary_text = data.get("text", "")
            score = cosine_similarity(q_embedding, data["embedding"])
            print(f"   → file_id: {file_id}, skor: {score:.4f}")
            index.append({"file_id": file_id, "score": score, "summary": summary_text})

        index.sort(key=lambda x: x["score"], reverse=True)
        top_results = index[:top_k]
        print(f"[search-docs] 🏆 Top {len(top_results)} sonuç döndürülüyor")
        return {"results": top_results}
    except Exception as e:
        print(f"[search-docs] ❌ Hata: {e}")
        raise
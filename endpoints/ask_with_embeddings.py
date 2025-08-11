from fastapi import Form
from main import app, create_embedding, cosine_similarity, client, DEFAULT_MODEL
from firebase_admin import firestore


@app.post("/ask-with-embeddings/")
async def ask_with_embeddings(
    question: str = Form(...),
    file_id: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...)
):
    from firebase_admin import firestore
    db = firestore.client()

    print("\n[ask-with-embeddings] 📥 İstek alındı")
    print(f"   → user_id: {user_id}")
    print(f"   → chat_id: {chat_id}")
    print(f"   → file_id: {file_id}")
    print(f"   → question: {question}")

    # Firestore Path
    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    print(f"[ask-with-embeddings] 🔗 Firestore path: embeddings/{user_id}/{chat_id}")

    # 1. Soru embedding oluştur
    try:
        q_embedding = create_embedding(question)
        print(f"[ask-with-embeddings] 🧠 Soru embedding boyutu: {len(q_embedding)}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ Soru embedding hatası: {e}")
        raise

    # 2. İlgili chunk'ları çek (meta hariç)
    try:
        docs = base_ref.where("file_id", "==", file_id).stream()
        print("[ask-with-embeddings] 🔄 Firestore'dan chunk'lar çekiliyor...")

        chunks = []
        for doc in docs:
            data = doc.to_dict()
            if data.get("chunk_index", 0) >= 0:  # Python’da filtre
                score = cosine_similarity(q_embedding, data["embedding"])
                chunks.append((score, data["text"]))
                print(f"   → Chunk skor: {score:.4f}, text (ilk 60): {data['text'][:60]}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ Chunk okuma hatası: {e}")
        raise

    # 3. En yakın 3 chunk seç
    top_chunks = [text for score, text in sorted(chunks, key=lambda x: x[0], reverse=True)[:3]]
    print(f"[ask-with-embeddings] 🏆 Seçilen top_chunks (adet: {len(top_chunks)}):")
    for i, tc in enumerate(top_chunks):
        print(f"   {i+1}. {tc[:100]}...")

    # 4. GPT prompt hazırla
    context = "\n".join(top_chunks)
    prompt = f"""\nBağlama dayanarak soruya yanıt ver. Doğrudan cevap yoksa en yakın bilgiyi özetle:\n{context}\n\nSoru: {question}\n"""
    print(f"[ask-with-embeddings] 📝 GPT'ye gönderilen prompt (ilk 300): {prompt[:300]}")

    # 5. GPT çağır ve cevap döndür
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Sen bağlam tabanlı bir asistansın."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content
        print(f"[ask-with-embeddings] ✅ GPT yanıtı (ilk 200): {answer[:200]}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ GPT yanıt hatası: {e}")
        raise

    return {"answer": answer, "context_used": top_chunks}

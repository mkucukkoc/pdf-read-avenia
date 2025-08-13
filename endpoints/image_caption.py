import base64
from fastapi import Body
from fastapi.responses import JSONResponse
from main import app, client, decode_base64_maybe_data_url


@app.post("/image-caption")
def image_caption(payload: dict = Body(...)):
    """Generate a caption for a base64 encoded image.

    Expected body:
    {
        "image_base64": "<base64 or data URL>"
    }
    """
    print("========== [/image-caption] BAŞLADI ==========")
    print("[1] Gelen payload:", payload)

    image_b64 = payload.get("image_base64")
    if not image_b64:
        print("[HATA] image_base64 eksik")
        return JSONResponse(status_code=400, content={"error": "No base64 image data provided"})

    try:
        print("[2] Base64 decode başlatılıyor...")
        image_bytes = decode_base64_maybe_data_url(image_b64)
        print(f"[2.1] Base64 decode başarılı. Byte boyutu: {len(image_bytes)}")
    except Exception as e:
        print("[HATA] Base64 decode başarısız:", e)
        return JSONResponse(status_code=400, content={"error": "Invalid base64 data", "details": str(e)})

    encoded = base64.b64encode(image_bytes).decode("utf-8")

    try:
        print("[3] GPT isteği hazırlanıyor...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Bu görüntüyü Türkçe olarak açıkla."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    ],
                }
            ],
        )
        caption = response.choices[0].message.content.strip()
        print("[3.1] GPT çıktı:", caption)
    except Exception as e:
        print("[HATA] GPT isteği başarısız:", e)
        return JSONResponse(status_code=500, content={"error": "Image caption failed", "details": str(e)})

    print("========== [/image-caption] BİTTİ ==========")
    return {"caption": caption}
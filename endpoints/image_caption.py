import base64, io, requests
import logging
from fastapi import Body
from fastapi.responses import JSONResponse
from main import app, client, decode_base64_maybe_data_url

logger = logging.getLogger("pdf_read_refresh.endpoints.image_caption")


def sniff_image_mime(b: bytes) -> str | None:
    # JPEG
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # PNG
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # GIF
    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
        return "image/gif"
    # WebP (RIFF....WEBP)
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None

@app.post("/analyze-image")
def image_caption(payload: dict = Body(...)):
    """
    Body:
      { "image_base64": "<base64|data URL>" }  veya
      { "image_url": "https://..." }
    """
    logger.info("Image caption request received", extra={"payload": payload})

    image_b64 = payload.get("image_base64")
    image_url = payload.get("image_url")

    if not image_b64 and not image_url:
        logger.warning("No image data provided")
        return JSONResponse(status_code=400, content={"error": "Provide image_base64 or image_url"})

    try:
        if image_url and not image_b64:
            logger.info("Downloading image from URL", extra={"url": image_url})
            r = requests.get(image_url, headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}, timeout=15)
            if r.status_code != 200:
                logger.error("Image URL fetch failed", extra={"status": r.status_code})
                return JSONResponse(status_code=400, content={"error": f"Image URL fetch failed: HTTP {r.status_code}"})
            ct = (r.headers.get("Content-Type") or "").lower()
            if not ct.startswith("image/"):
                logger.warning("Image URL returned non-image content", extra={"content_type": ct})
                return JSONResponse(status_code=400, content={"error": "URL does not return an image (content-type mismatch)"})
            image_bytes = r.content
        else:
            logger.info("Decoding base64 image")
            image_bytes = decode_base64_maybe_data_url(image_b64)
            logger.info("Base64 decode success", extra={"byte_length": len(image_bytes)})
    except Exception as e:
        logger.error("Failed to obtain image data", exc_info=e)
        return JSONResponse(status_code=400, content={"error": "Invalid image data", "details": str(e)})

    # 2) Gerçekten resim mi? + MIME tespiti
    mime = sniff_image_mime(image_bytes)
    if not mime:
        return JSONResponse(status_code=400, content={"error": "Provided data is not a supported image (png/jpeg/gif/webp)"} )

    # 3) Data URL hazırla (gerçek MIME ile)
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{encoded}"

    # 4) OpenAI çağrısı
    try:
        logger.info("Calling GPT for image caption")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Bu görüntüyü Türkçe olarak açıkla."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        )
        caption = response.choices[0].message.content.strip()
        logger.info("GPT caption response", extra={"caption_preview": caption[:200]})
    except Exception as e:
        logger.exception("Image caption GPT call failed")
        return JSONResponse(status_code=500, content={"error": "Image caption failed", "details": str(e)})

    logger.info("Image caption complete")
    return {"caption": caption}

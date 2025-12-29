import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Any, AsyncGenerator, Dict, Generator, Optional, Tuple

import requests
import firebase_admin
from firebase_admin import firestore
from fastapi import HTTPException, Request

from core.language_support import normalize_language
from core.websocket_manager import stream_manager
from core.useChatPersistence import chat_persistence
from errors_response import get_pdf_error_message

logger = logging.getLogger("pdf_read_refresh.files_pdf.utils")


def log_full_payload(logger_obj: logging.Logger, name: str, payload_obj: Any) -> None:
    try:
        payload_dict = getattr(payload_obj, "model_dump", lambda **kwargs: {})(by_alias=True, exclude_none=False)
    except Exception:
        payload_dict = str(payload_obj)
    logger_obj.info("PDF endpoint payload dump", extra={"endpoint": name, "payload": payload_dict})


def extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


def download_file(url: str, max_mb: int, require_pdf: bool = True) -> Tuple[bytes, str]:
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_file_url", "message": get_pdf_error_message("invalid_file_url", None)},
        )
    resp = requests.get(url, timeout=60)
    if not resp.ok or not resp.content:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "file_download_failed", "message": get_pdf_error_message("file_download_failed", None)},
        )
    content = resp.content
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "file_too_large", "message": get_pdf_error_message("file_too_large", None)},
        )
    mime = resp.headers.get("Content-Type", "application/pdf").split(";")[0].strip()
    if require_pdf and "pdf" not in mime:
        mime = "application/pdf"
    return content, mime


def inline_base64(content: bytes) -> str:
    return base64.b64encode(content).decode("utf-8")


def upload_to_gemini_files(content: bytes, mime_type: str, display_name: str, api_key: str) -> str:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    start_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
    start_headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(len(content)),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }
    start_resp = requests.post(start_url, headers=start_headers, json={"file": {"display_name": display_name}}, timeout=30)
    if not start_resp.ok:
        logger.error("Gemini Files start failed", extra={"status": start_resp.status_code, "body": start_resp.text[:500]})
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "upload_failed", "message": get_pdf_error_message("upload_failed", None)},
        )
    upload_url = start_resp.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "upload_failed", "message": get_pdf_error_message("upload_failed", None)},
        )

    upload_headers = {
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Type": mime_type,
        "Content-Length": str(len(content)),
    }
    upload_resp = requests.post(upload_url, headers=upload_headers, data=content, timeout=120)
    if not upload_resp.ok:
        logger.error("Gemini Files upload failed", extra={"status": upload_resp.status_code, "body": upload_resp.text[:500]})
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "upload_failed", "message": get_pdf_error_message("upload_failed", None)},
        )
    data = upload_resp.json()
    file_uri = data.get("file", {}).get("uri") or data.get("uri")
    if not file_uri:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "upload_failed", "message": get_pdf_error_message("upload_failed", None)},
        )
    return file_uri


def _effective_pdf_model(model: Optional[str]) -> str:
    return model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"


def call_gemini_generate(parts: list[Dict[str, Any]], api_key: str, model: Optional[str] = None) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )
    effective_model = _effective_pdf_model(model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:generateContent?key={api_key}"
    payload = {"contents": [{"role": "user", "parts": parts}]}
    resp = requests.post(url, json=payload, timeout=180)
    logger.info("Gemini doc request", extra={"status": resp.status_code})
    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_doc_failed", "message": get_pdf_error_message("gemini_doc_failed", None)},
        )
    return resp.json()


def call_gemini_generate_stream(
    parts: list[Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
) -> Generator[str, None, None]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )
    effective_model = _effective_pdf_model(model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:streamGenerateContent?alt=sse&key={api_key}"
    payload = {"contents": [{"role": "user", "parts": parts}]}
    resp = requests.post(
        url,
        json=payload,
        timeout=180,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )
    resp.encoding = "utf-8"
    logger.info(
        "Gemini doc stream request started status=%s model=%s",
        resp.status_code,
        effective_model,
    )
    if not resp.ok:
        body_preview = (resp.text or "")[:400]
        logger.error(
            "Gemini doc stream failed status=%s body=%s",
            resp.status_code,
            body_preview,
        )
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_doc_failed", "message": get_pdf_error_message("gemini_doc_failed", None)},
        )

    buffer: list[str] = []

    def flush_buffer():
        nonlocal buffer
        if not buffer:
            return
        data_str = "\n".join(buffer).strip()
        buffer.clear()
        if not data_str:
            return
        try:
            obj = json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug("Gemini doc stream non-JSON event preview=%s", data_str[:200])
            return
        candidates = obj.get("candidates") or []
        for candidate in candidates:
            parts = (candidate.get("content") or {}).get("parts") or []
            for part in parts:
                text = part.get("text")
                if isinstance(text, str) and text:
                    yield text

    for raw_line in resp.iter_lines(decode_unicode=True):
        line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore")
        if line is None:
            continue
        line = line.rstrip("\r")
        if not line:
            yield from flush_buffer()
            continue
        if line.startswith("data:"):
            buffer.append(line[len("data:") :].strip())
        elif line.startswith(":"):
            continue
        else:
            buffer.append(line.strip())

    yield from flush_buffer()


def extract_text_response(response_json: Dict[str, Any]) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    texts = []
    for part in parts:
        if "text" in part and isinstance(part["text"], str):
            texts.append(part["text"])
    return "\n".join(texts).strip()


def save_message_to_firestore(
    user_id: str,
    chat_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    if not chat_id:
        logger.warning(
            "Firestore save skipped (missing chatId)",
            extra={"userId": user_id},
        )
        return False
    try:
        chat_persistence.save_assistant_message(
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            metadata=metadata or {},
        )
        return True
    except RuntimeError:
        logger.warning(
            "Firestore save skipped (firebase app not initialized)",
            extra={"chatId": chat_id, "userId": user_id},
        )
        return False
    except Exception as exc:  # pragma: no cover
        logger.exception(
            "Firestore save failed",
            extra={
                "error": str(exc),
                "chatId": chat_id,
                "userId": user_id,
                "status": "error",
            },
        )
        return False


def localize_message(key: str, language: Optional[str]) -> str:
    lang = normalize_language(language)
    return get_pdf_error_message(key, lang)


async def stream_gemini_text(
    parts: list[Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    effective_model = _effective_pdf_model(model)

    def producer():
        try:
            for chunk in call_gemini_generate_stream(parts, api_key, effective_model):
                if chunk:
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Gemini doc stream producer error: %s", exc)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    producer_task = asyncio.create_task(asyncio.to_thread(producer))
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        await producer_task


async def generate_text_with_optional_stream(
    *,
    parts: list[Dict[str, Any]],
    api_key: str,
    stream: bool,
    chat_id: Optional[str],
    tool: str,
    model: Optional[str] = None,
    chunk_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    effective_model = _effective_pdf_model(model)
    if not stream or not chat_id:
        response_json = await asyncio.to_thread(call_gemini_generate, parts, api_key, effective_model)
        candidates = response_json.get("candidates", [])
        if not candidates:
            feedback = response_json.get("promptFeedback", {}) or {}
            usage = response_json.get("usageMetadata", {}) or {}
            logger.error("Gemini generate returned no candidates", extra={"feedback": feedback, "usage": usage})
            raise RuntimeError(
                f"Gemini response empty. Feedback: {feedback.get('blockReason', 'Unknown')}"
            )
        return extract_text_response(response_json), None

    message_id = f"{tool}_{uuid.uuid4().hex}"
    accumulated: list[str] = []
    try:
        async for chunk in stream_gemini_text(parts, api_key, effective_model):
            accumulated.append(chunk)
            payload: Dict[str, Any] = {
                "chatId": chat_id,
                "messageId": message_id,
                "tool": tool,
                "delta": chunk,
                "content": "".join(accumulated),
                "isFinal": False,
            }
            if chunk_metadata:
                payload["metadata"] = chunk_metadata
            await stream_manager.emit_chunk(chat_id, payload)
    except Exception:
        await stream_manager.emit_chunk(
            chat_id,
            {
                "chatId": chat_id,
                "messageId": message_id,
                "tool": tool,
                "isFinal": True,
                "error": "stream_failed",
            },
        )
        raise

    final_text = "".join(accumulated).strip()
    await stream_manager.emit_chunk(
        chat_id,
        {
            "chatId": chat_id,
            "messageId": message_id,
            "tool": tool,
            "content": final_text,
            "delta": None,
            "isFinal": True,
            "metadata": chunk_metadata or {},
        },
    )
    return final_text, message_id


def attach_streaming_payload(
    result: Dict[str, Any],
    *,
    tool: str,
    content: str,
    streaming: bool,
    message_id: Optional[str],
    extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data_payload: Dict[str, Any] = {
        "message": {
            "role": "assistant",
            "content": content,
            "metadata": {"tool": tool},
        },
        "tool": tool,
        "streaming": streaming,
        "messageId": message_id,
    }
    if extra_data:
        for key, value in extra_data.items():
            if value is not None:
                data_payload[key] = value
    result["data"] = data_payload
    result["streaming"] = streaming
    if message_id:
        result["messageId"] = message_id
    return result



import asyncio
import base64
import logging
import re
import json
import os
import uuid
from uuid import uuid4 as _uuid4
from typing import Any, AsyncGenerator, Dict, Generator, Optional, Tuple

import requests
import firebase_admin
from firebase_admin import firestore
from fastapi import HTTPException, Request

from core.language_support import normalize_language
from core.tone_instructions import ToneKey, build_tone_instruction
from core.websocket_manager import stream_manager
from core.useChatPersistence import chat_persistence
from errors_response import get_pdf_error_message
from endpoints.logging.utils_logging import json_pretty, log_request, log_response

logger = logging.getLogger("pdf_read_refresh.files_pdf.utils")


def log_full_payload(logger_obj: logging.Logger, name: str, payload_obj: Any) -> None:
    log_request(logger_obj, name, payload_obj)


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


def _strip_markdown_stars(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\*", "", text)


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
    # Öncelik: param > env > güncel canlı fallback
    return model or os.getenv("GEMINI_PDF_MODEL") or "models/gemini-3-flash-preview"


def _normalize_model_name(model: str) -> str:
    # Beklenen format: models/<model-name>
    if model.startswith("models/"):
        return model
    return f"models/{model}"


def _normalize_parts_for_office(parts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """
    If a part has file_data and only file_uri, leave as is (no forced mime).
    """
    normalized = []
    for part in parts:
        if "file_data" in part:
            fd = part["file_data"]
            # Remove mime_type if empty/None to let Gemini infer
            if fd.get("mime_type") in (None, ""):
                fd = {k: v for k, v in fd.items() if k != "mime_type"}
            normalized.append({"file_data": fd})
        else:
            normalized.append(part)
    return normalized


def call_gemini_generate(
    parts: list[Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )
    effective_model = _normalize_model_name(_effective_pdf_model(model))
    parts = _normalize_parts_for_office(parts)
    # Belirtilen istek: v1beta + models/<name>
    url = f"https://generativelanguage.googleapis.com/v1beta/{effective_model}:generateContent?key={api_key}"
    payload = {"contents": [{"role": "user", "parts": parts}]}
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}
    resp = requests.post(url, json=payload, timeout=180)
    body_preview = (resp.text or "")[:800]
    logger.info("Gemini doc request", extra={"status": resp.status_code, "model": effective_model, "body_preview": body_preview})
    if not resp.ok:
        logger.error(
            "Gemini doc request failed",
            extra={
                "status": resp.status_code,
                "model": effective_model,
                "body": body_preview,
            },
        )
        raise HTTPException(
            status_code=resp.status_code,
            detail={
                "success": False,
                "error": "gemini_doc_failed",
                "message": "Dosya analizi sırasında bir bağlantı sorunu oluştu. Lütfen model isminin güncelliğini kontrol edin veya birazdan tekrar deneyin.",
                "body": body_preview,
                "model": effective_model,
            },
        )
    return resp.json()


def call_gemini_generate_stream(
    parts: list[Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
    system_instruction: Optional[str] = None,
) -> Generator[str, None, None]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )
    effective_model = _effective_pdf_model(model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:streamGenerateContent?alt=sse&key={api_key}"
    payload = {"contents": [{"role": "user", "parts": parts}]}
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}
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
    client_message_id: Optional[str] = None,
    stream_message_id: Optional[str] = None,
) -> bool:
    # Normalize markdown artifacts before persisting
    content = _strip_markdown_stars(content)
    if not chat_id:
        logger.warning(
            "Firestore save skipped (missing chatId)",
            extra={"userId": user_id},
        )
        return False
    # Use a direct uuid4 import to avoid any accidental shadowing of the uuid module
    resolved_client_id = client_message_id or f"msg_{_uuid4().hex}"
    metadata_payload: Dict[str, Any] = dict(metadata or {})
    if stream_message_id:
        metadata_payload["streamMessageId"] = stream_message_id
    try:
        chat_persistence.save_assistant_message(
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            metadata=metadata_payload,
            message_id=resolved_client_id,
            client_message_id=resolved_client_id,
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
    system_instruction: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    effective_model = _effective_pdf_model(model)

    def producer():
        try:
            for chunk in call_gemini_generate_stream(parts, api_key, effective_model, system_instruction):
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
    followup_language: Optional[str] = None,
    tone_key: Optional[ToneKey] = None,
    tone_language: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    # Optionally instruct the model to end with a concise follow-up question in the same language.
    effective_parts = list(parts)
    if followup_language:
        followup_text = (
            f"Always end your response with a concise, relevant follow-up question to the user, in {followup_language}."
        )
        effective_parts.append({"text": followup_text})
    else:
        effective_parts.append(
            {
                "text": "Always end your response with a concise, relevant follow-up question to the user, in the same language as the response.",
            }
        )

    effective_model = _effective_pdf_model(model)
    system_instruction = build_tone_instruction(tone_key, tone_language)
    if not stream or not chat_id:
        response_json = await asyncio.to_thread(
            call_gemini_generate,
            effective_parts,
            api_key,
            effective_model,
            system_instruction,
        )
        candidates = response_json.get("candidates", [])
        if not candidates:
            feedback = response_json.get("promptFeedback", {}) or {}
            usage = response_json.get("usageMetadata", {}) or {}
            logger.error("Gemini generate returned no candidates", extra={"feedback": feedback, "usage": usage})
            raise RuntimeError(
                f"Gemini response empty. Feedback: {feedback.get('blockReason', 'Unknown')}"
            )
        clean_text = _strip_markdown_stars(extract_text_response(response_json))
        return clean_text, None

    # Use dedicated uuid4 import to avoid accidental shadowing
    message_id = f"{tool}_{_uuid4().hex}"
    accumulated: list[str] = []
    try:
        async for chunk in stream_gemini_text(
            effective_parts,
            api_key,
            effective_model,
            system_instruction=system_instruction,
        ):
            clean_chunk = _strip_markdown_stars(chunk)
            accumulated.append(clean_chunk)
            payload: Dict[str, Any] = {
                "chatId": chat_id,
                "messageId": message_id,
                "tool": tool,
                "delta": clean_chunk,
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
    try:
        log_response(logger, f"files_pdf/{tool}", result)
    except Exception:
        logger.warning("files_pdf response logging failed tool=%s", tool)
    return result

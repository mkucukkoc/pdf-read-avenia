import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

import requests
import firebase_admin
from firebase_admin import firestore
from fastapi import HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message

logger = logging.getLogger("pdf_read_refresh.files_pdf.utils")


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


def call_gemini_generate(parts: list[Dict[str, Any]], api_key: str, model: str = "gemini-2.5-flash") -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"role": "user", "parts": parts}]}
    resp = requests.post(url, json=payload, timeout=180)
    logger.info("Gemini doc request", extra={"status": resp.status_code})
    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_doc_failed", "message": get_pdf_error_message("gemini_doc_failed", None)},
        )
    return resp.json()


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
    if not firebase_admin._apps:
        logger.warning(
            "Firestore save skipped (firebase app not initialized)",
            extra={"chatId": chat_id, "userId": user_id},
        )
        return False
    if not chat_id:
        logger.warning(
            "Firestore save skipped (missing chatId)",
            extra={"userId": user_id},
        )
        return False
    db = firestore.client()
    data: Dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "metadata": metadata or {},
    }
    try:
        db.collection("users").document(user_id or "anonymous") \
            .collection("chats").document(chat_id) \
            .collection("messages").add(data)
        logger.info(
            "Firestore message saved",
            extra={"chatId": chat_id, "userId": user_id, "status": "success"},
        )
        return True
    except Exception as exc:  # pragma: no cover
        logger.exception(
            "Firestore save failed",
            extra={"error": str(exc), "chatId": chat_id, "userId": user_id, "status": "error"},
        )
        return False


def localize_message(key: str, language: Optional[str]) -> str:
    lang = normalize_language(language)
    return get_pdf_error_message(key, lang)



from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from google.cloud import firestore as firestore_client

from core.firebase import db
from endpoints.logging.utils_logging import log_request, log_response

logger = logging.getLogger("pdf_read_refresh.chat_settings")

router = APIRouter(prefix="/api/v1/chat/settings", tags=["ChatSettings"])


class ResponseStyleRequest(BaseModel):
    response_style: str = Field(..., alias="responseStyle")

    model_config = ConfigDict(populate_by_name=True)


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


@router.post("/response-style")
async def save_response_style(payload: ResponseStyleRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    log_request(logger, "chat_settings_response_style", payload.model_dump(by_alias=True))
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    if not db:
        raise HTTPException(status_code=500, detail={"success": False, "error": "firebase_unavailable", "message": "Firestore unavailable"})

    response_style = payload.response_style.strip()
    if not response_style:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": "responseStyle is required"})

    try:
        doc_ref = db.collection("users_chat_settings").document(user_id)
        doc_ref.set(
            {
                "settings": {"responseStyle": response_style},
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        resp = {"success": True, "data": {"responseStyle": response_style}}
        log_response(logger, "chat_settings_response_style", resp)
        return resp
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to save response style userId=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "save_failed", "message": str(exc)},
        ) from exc


__all__ = ["router"]

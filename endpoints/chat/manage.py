from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .chat_service import chat_service


logger = logging.getLogger("pdf_read_refresh.chat_manage")

router = APIRouter(prefix="/api/v1/chat", tags=["ChatManage"])


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


class RenameRequest(BaseModel):
    title: str


class FavoriteRequest(BaseModel):
    favorite: bool


@router.post("/{chat_id}/rename")
async def rename_chat(chat_id: str, payload: RenameRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Rename chat request userId=%s chatId=%s", user_id, chat_id)
        result = chat_service.rename_chat(user_id, chat_id, payload.title)
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Rename chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "rename_failed", "message": str(exc)}) from exc


@router.post("/{chat_id}/favorite")
async def set_favorite(chat_id: str, payload: FavoriteRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Favorite chat request userId=%s chatId=%s favorite=%s", user_id, chat_id, payload.favorite)
        result = chat_service.set_favorite(user_id, chat_id, payload.favorite)
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Favorite chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "favorite_failed", "message": str(exc)}) from exc


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Delete chat request userId=%s chatId=%s", user_id, chat_id)
        result = chat_service.delete_chat(user_id, chat_id)
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Delete chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "delete_failed", "message": str(exc)}) from exc


__all__ = ["router"]



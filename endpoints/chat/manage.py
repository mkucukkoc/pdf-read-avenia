from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from endpoints.logging.utils_logging import log_request, log_response

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
    log_request(logger, "chat_rename", {"chatId": chat_id, **payload.model_dump()})
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Rename chat request userId=%s chatId=%s", user_id, chat_id)
        result = chat_service.rename_chat(user_id, chat_id, payload.title)
        resp = {"success": True, "data": result}
        log_response(logger, "chat_rename", resp)
        return resp
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Rename chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "rename_failed", "message": str(exc)}) from exc


@router.post("/{chat_id}/favorite")
async def set_favorite(chat_id: str, payload: FavoriteRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    log_request(logger, "chat_favorite", {"chatId": chat_id, **payload.model_dump()})
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Favorite chat request userId=%s chatId=%s favorite=%s", user_id, chat_id, payload.favorite)
        result = chat_service.set_favorite(user_id, chat_id, payload.favorite)
        resp = {"success": True, "data": result}
        log_response(logger, "chat_favorite", resp)
        return resp
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Favorite chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "favorite_failed", "message": str(exc)}) from exc


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    log_request(logger, "chat_delete", {"chatId": chat_id, "userId": user_id})
    if not user_id:
        raise HTTPException(status_code=401, detail={"success": False, "error": "unauthorized", "message": "Auth required"})
    try:
        logger.info("Delete chat request userId=%s chatId=%s", user_id, chat_id)
        result = chat_service.delete_chat(user_id, chat_id)
        resp = {"success": True, "data": result}
        log_response(logger, "chat_delete", resp)
        return resp
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Delete chat failed userId=%s chatId=%s", user_id, chat_id)
        raise HTTPException(status_code=500, detail={"success": False, "error": "delete_failed", "message": str(exc)}) from exc


__all__ = ["router"]




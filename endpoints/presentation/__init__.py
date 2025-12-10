from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from schemas import PresentationRequest
from .presentation_service import presentation_service

logger = logging.getLogger("pdf_read_refresh.presentation_routes")

router = APIRouter(prefix="/api/v1/presentation", tags=["Presentation"])


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return (
        payload.get("uid")
        or payload.get("userId")
        or payload.get("sub")
        or ""
    )


@router.post("/generate")
async def generate_presentation_endpoint(payload: PresentationRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)

    try:
        presentation = await presentation_service.generate_presentation(payload, user_id)
        return {"success": True, "data": presentation}
    except ValueError as exc:
        logger.warning("Invalid presentation request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "invalid_request",
                "message": str(exc),
            },
        ) from exc
    except RuntimeError as exc:
        logger.error("Presentation generation runtime error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "presentation_generation_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - unexpected failure guard
        logger.exception("Unexpected error while generating presentation")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to generate presentation",
            },
        ) from exc


@router.get("/templates")
async def get_templates_endpoint() -> Dict[str, Any]:
    templates = await presentation_service.get_presentation_templates()
    return {"success": True, "data": templates}


@router.get("/user-presentations")
async def get_user_presentations_endpoint(request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    try:
        presentations = await presentation_service.get_user_presentations(user_id)
        return {
            "success": True,
            "data": presentations,
            "message": "Presentations retrieved successfully",
        }
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to fetch user presentations")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to get user presentations",
            },
        ) from exc


__all__ = ["router", "presentation_service"]




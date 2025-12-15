import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from schemas import AgentDispatchRequest
from .dispatcher import determine_agent_and_run

logger = logging.getLogger("pdf_read_refresh.agent.router")

router = APIRouter(prefix="/api/v1/chat", tags=["Agent"])


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return (
        payload.get("uid")
        or payload.get("userId")
        or payload.get("sub")
        or ""
    )


@router.post("/dispatch_message")
async def dispatch_message(payload: AgentDispatchRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request) or payload.user_id or ""
    if not user_id:
        logger.warning("Agent dispatch unauthorized")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": "unauthorized",
                "message": "Kullanıcı kimliği gerekiyor.",
            },
        )

    logger.info(
        "Agent dispatch request received",
        extra={
            "userId": user_id,
            "chatId": payload.chat_id,
            "language": payload.language,
            "hasPrompt": bool(payload.prompt),
            "conversationLen": len(payload.conversation or []),
        },
    )

    result = await determine_agent_and_run(payload, user_id)
    logger.debug(
        "Agent dispatch response ready",
        extra={"userId": user_id, "chatId": payload.chat_id, "success": result.get("success", True)},
    )
    return result


__all__ = ["router"]


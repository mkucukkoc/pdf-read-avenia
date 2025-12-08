import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from agents.image import (
    execute_edit_image,
    execute_generate_image,
    execute_generate_image_search,
)
from agents import get_agent_by_name
from schemas import AgentExecuteRequest, AgentExecuteResponse, ChatMessagePayload, ChatRequestPayload
from services import chat_service

logger = logging.getLogger("pdf_read_refresh.agent_executor")

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])


async def _dispatch_tool(tool_name: str, arguments: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Map tool names to backend executor functions."""
    tool = get_agent_by_name(tool_name)
    if not tool:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "unknown_tool", "message": f"Tool not found: {tool_name}"},
        )

    args = arguments or {}
    args["user_id"] = user_id

    if tool_name == "generate_image_gemini":
        return await execute_generate_image(
            prompt=args.get("prompt", ""),
            chat_id=args.get("chatId"),
            language=args.get("language"),
            file_name=args.get("fileName"),
            use_google_search=bool(args.get("useGoogleSearch")),
            aspect_ratio=args.get("aspectRatio"),
            model=args.get("model"),
            user_id=user_id,
        )

    if tool_name == "generate_image_gemini_search":
        return await execute_generate_image_search(
            prompt=args.get("prompt", ""),
            chat_id=args.get("chatId"),
            language=args.get("language"),
            file_name=args.get("fileName"),
            aspect_ratio=args.get("aspectRatio"),
            model=args.get("model"),
            user_id=user_id,
        )

    if tool_name == "image_edit_gemini":
        return await execute_edit_image(
            prompt=args.get("prompt", ""),
            image_url=args.get("imageUrl") or args.get("image_url") or "",
            chat_id=args.get("chatId"),
            language=args.get("language"),
            file_name=args.get("fileName"),
            user_id=user_id,
        )

    if tool_name == "chat_agent":
        # Fallback to normal chat text generation via chat_service
        prompt = args.get("prompt") or ""
        chat_id = args.get("chatId") or args.get("chat_id")
        language = args.get("language")
        if not prompt:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
            )
        chat_payload = ChatRequestPayload(
            messages=[ChatMessagePayload(role="user", content=prompt)],
            chat_id=chat_id or f"chat_{user_id}",
            has_image=False,
            image_file_url=None,
            language=language,
            stream=False,
        )
        return await chat_service.send_message(chat_payload, user_id)

    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "unsupported_tool", "message": f"Tool not supported: {tool_name}"},
    )


@router.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(request: Request, payload: AgentExecuteRequest) -> AgentExecuteResponse:
    """Execute backend agent directly (used after /chat/route-gemini)."""
    user_payload = getattr(request.state, "token_payload", {}) or {}
    user_id = user_payload.get("uid") or user_payload.get("sub") or "anonymous"

    logger.info(
        "Agent execution requested",
        extra={
            "tool": payload.tool_name,
            "chatId": payload.chat_id,
            "argKeys": list(payload.arguments.keys()),
            "userId": user_id,
        },
    )

    try:
        result = await _dispatch_tool(payload.tool_name, payload.arguments, user_id)
        return AgentExecuteResponse(success=bool(result.get("success", True)), tool_name=payload.tool_name, result=result)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Agent execution failed", extra={"tool": payload.tool_name, "chatId": payload.chat_id})
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "agent_execution_failed", "message": str(exc)},
        ) from exc



import logging
import os
from typing import Any, Dict, Optional

import socketio
from jose import JWTError, jwt

logger = logging.getLogger("pdf_read_refresh.websocket")

JWT_SECRET = os.getenv("JWT_HS_SECRET", "change_me_in_production")
JWT_ISSUER = os.getenv("JWT_ISS", "chatgbtmini")
JWT_AUDIENCE = os.getenv("JWT_AUD", "chatgbtmini-mobile")

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

ROOM_PREFIX = "chat:"


def _resolve_room(chat_id: Optional[str]) -> Optional[str]:
    if not chat_id:
        return None
    return f"{ROOM_PREFIX}{chat_id}"


def _decode_token(token: Optional[str]) -> Dict[str, Any]:
    if not token:
        return {}
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        return payload or {}
    except JWTError as exc:
        logger.warning("WebSocket token verification failed: %s", exc)
        return {}
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("Unexpected error while decoding WS token: %s", exc)
        return {}


@sio.event
async def connect(sid, environ, auth):
    auth = auth or {}
    payload = _decode_token(auth.get("token"))
    user_id = payload.get("uid") or payload.get("sub")
    await sio.save_session(sid, {"userId": user_id})
    logger.info("WebSocket client connected", {"sid": sid, "userId": user_id})
    await sio.emit("websocket:connected", {"userId": user_id}, to=sid)


@sio.event
async def disconnect(sid):
    session = await sio.get_session(sid) or {}
    logger.info("WebSocket client disconnected", {"sid": sid, "userId": session.get("userId")})


@sio.on("chat:join")
async def handle_chat_join(sid, data):
    chat_id = (data or {}).get("chatId")
    room = _resolve_room(chat_id)
    if not room:
        return
    await sio.enter_room(sid, room)
    logger.debug("WebSocket client joined chat", {"sid": sid, "chatId": chat_id})


@sio.on("chat:leave")
async def handle_chat_leave(sid, data):
    chat_id = (data or {}).get("chatId")
    room = _resolve_room(chat_id)
    if not room:
        return
    await sio.leave_room(sid, room)
    logger.debug("WebSocket client left chat", {"sid": sid, "chatId": chat_id})


class StreamManager:
    @staticmethod
    async def emit_chunk(chat_id: str, payload: Dict[str, Any]) -> None:
        room = _resolve_room(chat_id)
        if not room:
            return
        logger.debug(
            "Emitting stream chunk",
            extra={
                "chatId": chat_id,
                "room": room,
                "messageId": payload.get("messageId"),
                "isFinal": payload.get("isFinal"),
                "error": payload.get("error"),
                "contentPreview": (payload.get("content") or "")[:80],
                "deltaLen": len(payload.get("delta") or ""),
                "contentLen": len(payload.get("content") or ""),
            },
        )
        await sio.emit("chat:stream", payload, room=room)


stream_manager = StreamManager()











import os
from typing import Any, Dict, Optional

from errors_response.api_errors import get_api_error_message
from core.useChatPersistence import chat_persistence


def build_success_error_response(
    *,
    tool: str,
    language: Optional[str],
    chat_id: Optional[str],
    user_id: Optional[str],
    status_code: int,
    detail: Any,
) -> Dict[str, Any]:
    """
    Returns a success-shaped payload carrying a friendly error message,
    and persists it to Firestore if chat_id is present.
    """
    def _map_error_key(code: int) -> str:
        if code == 404:
            return "upstream_404"
        if code == 429:
            return "upstream_429"
        if code in (401, 403):
            return "upstream_401"
        if code == 408:
            return "upstream_timeout"
        if code >= 500:
            return "upstream_500"
        return "unknown_error"

    key = _map_error_key(status_code)
    msg = get_api_error_message(key, language or "tr")
    message_id = f"{tool}_error_{os.urandom(4).hex()}"

    if chat_id and user_id:
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=chat_id,
                content=msg,
                metadata={
                    "tool": tool,
                    "error": key,
                    "detail": str(detail)[:1000],
                    "status": status_code,
                },
                message_id=message_id,
                client_message_id=message_id,
            )
        except Exception:
            # Fail silently; logging is handled at call sites if needed
            pass

    return {
        "success": True,
        "data": {
            "message": {
                "content": msg,
                "id": message_id,
            },
            "streaming": False,
        },
    }


__all__ = ["build_success_error_response"]

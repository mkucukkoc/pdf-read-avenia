from typing import Any, Dict

from starlette.requests import Request


def build_internal_request(user_id: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/internal/agent/dispatch",
        "headers": [],
        "client": ("127.0.0.1", 0),
    }

    async def receive() -> Dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    request.state.token_payload = {"uid": user_id} if user_id else {}
    return request


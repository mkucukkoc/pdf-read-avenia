import logging
import os
from typing import Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt

logger = logging.getLogger("pdf_read_refresh.auth")

JWT_SECRET = os.getenv("JWT_HS_SECRET", "change_me_in_production")
JWT_ISSUER = os.getenv("JWT_ISS", "chatgbtmini")
JWT_AUDIENCE = os.getenv("JWT_AUD", "chatgbtmini-mobile")
PUBLIC_PATHS = {"/health", "/healthz", "/docs", "/openapi.json", "/redoc"}


def _verify_bearer_token(auth_header: Optional[str]) -> Dict:
    if not auth_header:
        logger.warning("Authorization header missing")
        raise HTTPException(
            status_code=401,
            detail={"error": "access_denied", "message": "Access token required"},
        )

    parts = auth_header.strip().split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Invalid authorization header format")
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "message": "Invalid authorization header"},
        )

    token = parts[1]
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        logger.debug("Token verified for subject %s", payload.get("sub"))
        return payload
    except JWTError as exc:
        logger.warning("Token verification failed: %s", exc)
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "message": "Invalid or expired access token"},
        )
    except Exception as exc:  # pragma: no cover - defensive coding
        logger.exception("Unexpected error while verifying token: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "auth_error", "message": "Failed to validate access token"},
        )


def create_auth_middleware():
    async def authenticate_request(request: Request, call_next):
        path = request.url.path
        if path.startswith("/static/") or path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        try:
            payload = _verify_bearer_token(request.headers.get("Authorization"))
            request.state.token_payload = payload
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
            return JSONResponse(status_code=exc.status_code, content=detail)

        return await call_next(request)

    return authenticate_request


__all__ = ["create_auth_middleware", "PUBLIC_PATHS"]


def get_request_user_id(request: Request) -> str:
    """
    Helper to read the authenticated user id from request.state.token_payload.
    Returns empty string if not present.
    """
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""









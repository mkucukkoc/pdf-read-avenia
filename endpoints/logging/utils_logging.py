import json
import logging
from typing import Any


def json_pretty(obj: Any) -> str:
    """
    Safe JSON pretty printer with ensure_ascii=False.
    Falls back to str(obj) if serialization fails.
    """
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


def log_request(logger: logging.Logger, name: str, payload_obj: Any) -> None:
    """
    Log an incoming request payload as pretty JSON.
    Tries pydantic model_dump when available.
    Includes endpoint label if method/path keys exist.
    """
    try:
        if isinstance(payload_obj, dict):
            payload_dict = payload_obj
        else:
            payload_dict = getattr(payload_obj, "model_dump", None)
            if callable(payload_dict):
                payload_dict = payload_dict(by_alias=True, exclude_none=True)
            else:
                payload_dict = payload_obj
    except Exception:
        payload_dict = payload_obj

    method = None
    path = None
    if isinstance(payload_dict, dict):
        method = payload_dict.get("method")
        path = payload_dict.get("path")
    endpoint_label = f"{method} {path}" if method and path else name

    logger.info("%s request JSON (%s):\n%s", name, endpoint_label, json_pretty(payload_dict))


def log_response(logger: logging.Logger, name: str, response_obj: Any) -> None:
    """
    Log an outgoing response payload as pretty JSON.
    If response_obj is a dict containing an 'endpoint', use it in the label.
    """
    endpoint_label = None
    if isinstance(response_obj, dict):
        endpoint_label = response_obj.get("endpoint")

    label = endpoint_label or name
    logger.info("%s response JSON (%s):\n%s", name, label, json_pretty(response_obj))


def log_gemini_request(
    logger: logging.Logger,
    name: str,
    *,
    url: str,
    payload: Any,
    model: str | None = None,
    method: str = "POST",
) -> None:
    log_request(
        logger,
        f"{name}.gemini_request",
        {"method": method, "url": url, "model": model, "payload": payload},
    )


def log_gemini_response(
    logger: logging.Logger,
    name: str,
    *,
    url: str,
    status_code: int,
    response: Any,
) -> None:
    log_response(
        logger,
        f"{name}.gemini_response",
        {"url": url, "status": status_code, "response": response},
    )


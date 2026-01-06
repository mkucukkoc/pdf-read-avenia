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
    """
    try:
        payload_dict = getattr(payload_obj, "model_dump", lambda **kwargs: {})(by_alias=True, exclude_none=True)
    except Exception:
        payload_dict = payload_obj
    logger.info("%s request JSON:\n%s", name, json_pretty(payload_dict))


def log_response(logger: logging.Logger, name: str, response_obj: Any) -> None:
    """
    Log an outgoing response payload as pretty JSON.
    """
    logger.info("%s response JSON:\n%s", name, json_pretty(response_obj))



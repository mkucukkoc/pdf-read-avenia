from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Type

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from .utils import build_internal_request

logger = logging.getLogger("pdf_read_refresh.agent.base")


class BaseAgent(ABC):
    """
    Backend counterpart of the frontend BaseAgent abstraction.
    Each agent exposes a name/description/parameters schema and
    an async execute method that returns a dict response.
    """

    name: str
    description: str
    parameters: Dict[str, Any]

    @abstractmethod
    async def execute(self, args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        ...


class HandlerBackedAgent(BaseAgent):
    """
    Helper agent that wraps an existing FastAPI handler + Pydantic request model.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        request_model: Type[BaseModel],
        handler: Callable[[BaseModel, Any], Awaitable[Dict[str, Any]]],
    ) -> None:
        self.name = name
        self.description = description
        self.request_model = request_model
        self.handler = handler
        schema = request_model.model_json_schema()
        self.parameters = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
            "additionalProperties": False,
        }
        logger.debug(
            "Agent schema prepared",
            extra={"agent": self.name, "params": list(self.parameters["properties"].keys())},
        )

    async def execute(self, args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        logger.info("Executing agent", extra={"agent": self.name, "userId": user_id})
        try:
            request_obj = self.request_model(**args)
        except ValidationError as exc:
            logger.warning("Agent argument validation failed", extra={"agent": self.name, "errors": exc.errors()})
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error": "invalid_agent_args",
                    "message": "Agent parametreleri doğrulanamadı.",
                    "details": exc.errors(),
                },
            ) from exc

        request = build_internal_request(user_id)
        response = await self.handler(request_obj, request)
        logger.info(
            "Agent execution completed",
            extra={"agent": self.name, "userId": user_id, "success": response.get("success", True)},
        )
        return response


def handler_agent(
    *,
    name: str,
    description: str,
    request_model: Type[BaseModel],
    handler: Callable[[BaseModel, Any], Awaitable[Dict[str, Any]]],
) -> HandlerBackedAgent:
    return HandlerBackedAgent(
        name=name,
        description=description,
        request_model=request_model,
        handler=handler,
    )


AgentType = BaseAgent


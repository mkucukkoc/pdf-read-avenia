import logging

from schemas import WebSearchRequest
from endpoints.web_search import run_web_search
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.web_search")


async def _logged_web_search(payload: WebSearchRequest, request):
    user_id = get_request_user_id(request) or payload.user_id or ""
    logger.info(
        "web_search_agent invoked chatId=%s userId=%s promptPreview=%s",
        payload.chat_id,
        user_id,
        (payload.prompt or "")[:120],
    )
    return await run_web_search(payload, user_id, request)


web_search_agent = handler_agent(
    name="web_search_agent",
    description="Güncel web araması yapar ve kaynaklı yanıt döner.",
    request_model=WebSearchRequest,
    handler=_logged_web_search,
)

web_search_agents = [web_search_agent]

__all__ = ["web_search_agents"]


import logging

from schemas import WebSearchRequest
from endpoints.web_link import run_web_link
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.web_link")


async def _logged_web_link(payload: WebSearchRequest, request):
    user_id = get_request_user_id(request) or payload.user_id or ""
    logger.info(
        "web_link_agent invoked chatId=%s userId=%s promptPreview=%s",
        payload.chat_id,
        user_id,
        (payload.prompt or "")[:120],
    )
    return await run_web_link(payload, user_id, request)


web_link_agent = handler_agent(
    name="web_link_agent",
    description="Kullanıcının verdiği web link(ler)i üzerinden arama/özet yanıtı üretir.",
    request_model=WebSearchRequest,
    handler=_logged_web_link,
)

web_link_agents = [web_link_agent]

__all__ = ["web_link_agents"]


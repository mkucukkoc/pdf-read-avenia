import logging

from schemas import DeepResearchRequest
from endpoints.deep_research import run_deep_research
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.deep_research")


async def _logged_deep_research(payload: DeepResearchRequest, request):
    user_id = get_request_user_id(request) or payload.user_id or ""
    logger.info(
        "deep_research_agent invoked chatId=%s userId=%s promptPreview=%s",
        payload.chat_id,
        user_id,
        (payload.prompt or "")[:120],
    )
    return await run_deep_research(payload, user_id)


deep_research_agent = handler_agent(
    name="deep_research_agent",
    description="Çok adımlı derin araştırma yapar, web araması ve okuma ile ayrıntılı cevap döner.",
    request_model=DeepResearchRequest,
    handler=_logged_deep_research,
)

deep_research_agents = [deep_research_agent]

__all__ = ["deep_research_agents"]


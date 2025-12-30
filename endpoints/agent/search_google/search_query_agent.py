import logging

from schemas import SearchQueryRequest
from endpoints.search_google.search_query import generate_search_queries
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.search_google.search_query")


async def _logged_search_query(payload: SearchQueryRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "search_query_agent invoked chatId=%s userId=%s queryPreview=%s",
        payload.chat_id,
        user_id,
        (payload.query or "")[:120],
    )
    return await generate_search_queries(payload, request)


search_query_agent = handler_agent(
    name="search_query_agent",
    description="Doğal dildeki kullanıcı sorusunu Google için optimize edilmiş arama terimlerine dönüştürür.",
    request_model=SearchQueryRequest,
    handler=_logged_search_query,
)

__all__ = ["search_query_agent"]


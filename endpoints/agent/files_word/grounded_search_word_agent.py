import logging

from schemas import DocGroundedSearchRequest
from endpoints.files_word.grounded_search_word import grounded_search_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.grounded_search")


async def _logged_grounded_search_word(payload: DocGroundedSearchRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_grounded_search agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s question=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.question,
    )
    return await grounded_search_word(payload, request)


grounded_search_word_agent = handler_agent(
    name="word_grounded_search",
    description="Word dokümanında grounded search yapar; .docx/.doc içerikler.",
    request_model=DocGroundedSearchRequest,
    handler=_logged_grounded_search_word,
)

__all__ = ["grounded_search_word_agent"]


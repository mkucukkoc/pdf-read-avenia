import logging

from schemas import DocCompareRequest
from endpoints.files_word.compare_word import compare_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.compare")


async def _logged_compare_word(payload: DocCompareRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_compare agent handler invoked chatId=%s userId=%s file1=%s file2=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file1,
        payload.file2,
        payload.file_name,
    )
    return await compare_word(payload, request)


compare_word_agent = handler_agent(
    name="word_compare",
    description="İki Word dokümanını farklarıyla karşılaştırır; .docx/.doc içerikler.",
    request_model=DocCompareRequest,
    handler=_logged_compare_word,
)

__all__ = ["compare_word_agent"]


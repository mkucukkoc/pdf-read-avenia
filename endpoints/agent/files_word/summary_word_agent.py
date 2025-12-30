import logging

from schemas import DocSummaryRequest
from endpoints.files_word.summary_word import summary_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.summary")


async def _logged_summary_word(payload: DocSummaryRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_summary agent handler invoked chatId=%s userId=%s fileUrl=%s summaryLevel=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.summary_level,
    )
    return await summary_word(payload, request)


summary_word_agent = handler_agent(
    name="word_summary",
    description="Word (DOCX/DOC) dosyasından özet çıkarır; .docx/.doc içerikler.",
    request_model=DocSummaryRequest,
    handler=_logged_summary_word,
)

__all__ = ["summary_word_agent"]


import logging

from schemas import DocExtractRequest
from endpoints.files_word.extract_word import extract_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.extract")


async def _logged_extract_word(payload: DocExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await extract_word(payload, request)


extract_word_agent = handler_agent(
    name="word_extract",
    description="Word dokümanından önemli bilgileri çıkarır; .docx/.doc içerikler.",
    request_model=DocExtractRequest,
    handler=_logged_extract_word,
)

__all__ = ["extract_word_agent"]


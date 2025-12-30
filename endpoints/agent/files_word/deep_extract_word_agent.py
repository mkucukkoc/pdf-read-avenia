import logging

from schemas import DocDeepExtractRequest
from endpoints.files_word.deep_extract_word import deep_extract_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.deep_extract")


async def _logged_deep_extract_word(payload: DocDeepExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_deep_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s fields=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.fields,
    )
    return await deep_extract_word(payload, request)


deep_extract_word_agent = handler_agent(
    name="word_deep_extract",
    description="Word dokümanından belirli alanları derinlemesine çıkarır; .docx/.doc içerikler.",
    request_model=DocDeepExtractRequest,
    handler=_logged_deep_extract_word,
)

__all__ = ["deep_extract_word_agent"]


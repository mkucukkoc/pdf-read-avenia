import logging

from schemas import DocTranslateRequest
from endpoints.files_word.translate_word import translate_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.translate")


async def _logged_translate_word(payload: DocTranslateRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_translate agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s target=%s source=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.target_language,
        payload.source_language,
    )
    return await translate_word(payload, request)


translate_word_agent = handler_agent(
    name="word_translate",
    description="Word dokümanını çevirir; .docx/.doc içerikler.",
    request_model=DocTranslateRequest,
    handler=_logged_translate_word,
)

__all__ = ["translate_word_agent"]


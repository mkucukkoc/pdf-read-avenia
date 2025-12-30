import logging

from schemas import DocClassifyRequest
from endpoints.files_word.classify_word import classify_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.classify")


async def _logged_classify_word(payload: DocClassifyRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_classify agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s labels=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.labels,
    )
    return await classify_word(payload, request)


classify_word_agent = handler_agent(
    name="word_classify",
    description="Word dokümanını verilen etiketlere göre sınıflandırır; .docx/.doc içerikler.",
    request_model=DocClassifyRequest,
    handler=_logged_classify_word,
)

__all__ = ["classify_word_agent"]


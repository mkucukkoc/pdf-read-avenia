import logging

from schemas import DocQnaRequest
from endpoints.files_word.qna_word import qna_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.qna")


async def _logged_qna_word(payload: DocQnaRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_qna agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s question=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.question,
    )
    return await qna_word(payload, request)


qna_word_agent = handler_agent(
    name="word_qna",
    description="Word dokümanı üzerinde soru-cevap yapar; .docx/.doc içerikler.",
    request_model=DocQnaRequest,
    handler=_logged_qna_word,
)

__all__ = ["qna_word_agent"]


import logging

from schemas import DocRewriteRequest
from endpoints.files_word.rewrite_word import rewrite_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.rewrite")


async def _logged_rewrite_word(payload: DocRewriteRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_rewrite agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s style=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.style,
    )
    return await rewrite_word(payload, request)


rewrite_word_agent = handler_agent(
    name="word_rewrite",
    description="Word dokümanındaki metni yeniden yazar/düzenler; .docx/.doc içerikler.",
    request_model=DocRewriteRequest,
    handler=_logged_rewrite_word,
)

__all__ = ["rewrite_word_agent"]


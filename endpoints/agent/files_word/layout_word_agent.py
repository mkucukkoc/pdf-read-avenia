import logging

from schemas import DocLayoutRequest
from endpoints.files_word.layout_word import layout_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.layout")


async def _logged_layout_word(payload: DocLayoutRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_layout agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await layout_word(payload, request)


layout_word_agent = handler_agent(
    name="word_layout",
    description="Word dokümanının layout/yapı bilgisini çıkarır; .docx/.doc içerikler.",
    request_model=DocLayoutRequest,
    handler=_logged_layout_word,
)

__all__ = ["layout_word_agent"]


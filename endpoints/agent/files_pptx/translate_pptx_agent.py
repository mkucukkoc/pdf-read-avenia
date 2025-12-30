import logging

from schemas import PptxTranslateRequest
from endpoints.files_pptx.translate_pptx import translate_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.translate")


async def _logged_translate_pptx(payload: PptxTranslateRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_translate agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s target=%s source=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.target_language,
        payload.source_language,
    )
    return await translate_pptx(payload, request)


translate_pptx_agent = handler_agent(
    name="pptx_translate",
    description="PPTX sunumunu hedef dile çevirir; .pptx/.ppt içerikler.",
    request_model=PptxTranslateRequest,
    handler=_logged_translate_pptx,
)

__all__ = ["translate_pptx_agent"]


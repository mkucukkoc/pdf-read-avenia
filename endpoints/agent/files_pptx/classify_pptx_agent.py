import logging

from schemas import PptxClassifyRequest
from endpoints.files_pptx.classify_pptx import classify_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.classify")


async def _logged_classify_pptx(payload: PptxClassifyRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_classify agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s labels=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
        payload.labels,
    )
    return await classify_pptx(payload, request)


classify_pptx_agent = handler_agent(
    name="pptx_classify",
    description="PPTX sunumunu verilen etiketlere göre sınıflandırır; .pptx/.ppt içerikler.",
    request_model=PptxClassifyRequest,
    handler=_logged_classify_pptx,
)

__all__ = ["classify_pptx_agent"]


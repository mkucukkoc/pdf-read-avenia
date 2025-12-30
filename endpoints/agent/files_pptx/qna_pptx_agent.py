import logging

from schemas import PptxQnaRequest
from endpoints.files_pptx.qna_pptx import qna_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.qna")


async def _logged_qna_pptx(payload: PptxQnaRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_qna agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await qna_pptx(payload, request)


qna_pptx_agent = handler_agent(
    name="pptx_qna",
    description="PPTX sunumunda soru-cevap yapar; .pptx/.ppt içerikler.",
    request_model=PptxQnaRequest,
    handler=_logged_qna_pptx,
)

__all__ = ["qna_pptx_agent"]


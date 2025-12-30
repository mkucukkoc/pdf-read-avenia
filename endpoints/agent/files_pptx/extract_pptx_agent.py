import logging

from schemas import PptxExtractRequest
from endpoints.files_pptx.extract_pptx import extract_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.extract")


async def _logged_extract_pptx(payload: PptxExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await extract_pptx(payload, request)


extract_pptx_agent = handler_agent(
    name="pptx_extract",
    description="PPTX sunumundan önemli bilgileri çıkarır; .pptx/.ppt içerikler.",
    request_model=PptxExtractRequest,
    handler=_logged_extract_pptx,
)

__all__ = ["extract_pptx_agent"]


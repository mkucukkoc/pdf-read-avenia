import logging

from schemas import PptxDeepExtractRequest
from endpoints.files_pptx.deep_extract_pptx import deep_extract_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.deep_extract")


async def _logged_deep_extract_pptx(payload: PptxDeepExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_deep_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await deep_extract_pptx(payload, request)


deep_extract_pptx_agent = handler_agent(
    name="pptx_deep_extract",
    description="PPTX sunumundan belirtilen alanları derin çıkarım ile alır; .pptx/.ppt içerikler.",
    request_model=PptxDeepExtractRequest,
    handler=_logged_deep_extract_pptx,
)

__all__ = ["deep_extract_pptx_agent"]


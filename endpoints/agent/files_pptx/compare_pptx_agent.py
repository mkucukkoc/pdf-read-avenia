import logging

from schemas import PptxCompareRequest
from endpoints.files_pptx.compare_pptx import compare_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.compare")


async def _logged_compare_pptx(payload: PptxCompareRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_compare agent handler invoked chatId=%s userId=%s file1=%s file2=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file1,
        payload.file2,
        payload.file_name,
    )
    return await compare_pptx(payload, request)


compare_pptx_agent = handler_agent(
    name="pptx_compare",
    description="İki PPTX sunumu karşılaştırır; .pptx/.ppt içerikler.",
    request_model=PptxCompareRequest,
    handler=_logged_compare_pptx,
)

__all__ = ["compare_pptx_agent"]


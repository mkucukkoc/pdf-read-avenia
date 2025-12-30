import logging

from schemas import PptxSummaryRequest
from endpoints.files_pptx.summary_pptx import summary_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.summary")


async def _logged_summary_pptx(payload: PptxSummaryRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_summary agent handler invoked chatId=%s userId=%s fileUrl=%s summaryLevel=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.summary_level,
    )
    return await summary_pptx(payload, request)


summary_pptx_agent = handler_agent(
    name="pptx_summary",
    description="PPTX sunumundan özet çıkarır; .pptx/.ppt içerikler.",
    request_model=PptxSummaryRequest,
    handler=_logged_summary_pptx,
)

__all__ = ["summary_pptx_agent"]


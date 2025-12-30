import logging

from schemas import PptxAnalyzeRequest
from endpoints.files_pptx.analyze_pptx import analyze_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.analyze")


async def _logged_analyze_pptx(payload: PptxAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_analyze agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await analyze_pptx(payload, request)


analyze_pptx_agent = handler_agent(
    name="pptx_analyze",
    description="PPTX sunumunu analiz eder; .pptx/.ppt içerikler.",
    request_model=PptxAnalyzeRequest,
    handler=_logged_analyze_pptx,
)

__all__ = ["analyze_pptx_agent"]


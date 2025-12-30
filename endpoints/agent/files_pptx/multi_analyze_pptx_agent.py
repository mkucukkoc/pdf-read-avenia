import logging

from schemas import PptxMultiAnalyzeRequest
from endpoints.files_pptx.multi_analyze_pptx import multi_analyze_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.multi_analyze")


async def _logged_multi_analyze_pptx(payload: PptxMultiAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_multi_analyze agent handler invoked chatId=%s userId=%s fileCount=%s",
        payload.chat_id,
        user_id,
        len(payload.file_urls or []),
    )
    return await multi_analyze_pptx(payload, request)


multi_analyze_pptx_agent = handler_agent(
    name="pptx_multi_analyze",
    description="Birden fazla PPTX sunumunu birlikte analiz eder; .pptx/.ppt içerikler.",
    request_model=PptxMultiAnalyzeRequest,
    handler=_logged_multi_analyze_pptx,
)

__all__ = ["multi_analyze_pptx_agent"]


import logging

from schemas import PptxGroundedSearchRequest
from endpoints.files_pptx.grounded_search_pptx import grounded_search_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.grounded_search")


async def _logged_grounded_search_pptx(payload: PptxGroundedSearchRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_grounded_search agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await grounded_search_pptx(payload, request)


grounded_search_pptx_agent = handler_agent(
    name="pptx_grounded_search",
    description="PPTX sunumu üzerinden grounded search / soru-cevap yapar; .pptx/.ppt içerikler.",
    request_model=PptxGroundedSearchRequest,
    handler=_logged_grounded_search_pptx,
)

__all__ = ["grounded_search_pptx_agent"]


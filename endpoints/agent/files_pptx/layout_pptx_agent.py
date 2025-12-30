import logging

from schemas import PptxLayoutRequest
from endpoints.files_pptx.layout_pptx import layout_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.layout")


async def _logged_layout_pptx(payload: PptxLayoutRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_layout agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await layout_pptx(payload, request)


layout_pptx_agent = handler_agent(
    name="pptx_layout",
    description="PPTX sunumunun layout/yapı bilgisini çıkarır; .pptx/.ppt içerikler.",
    request_model=PptxLayoutRequest,
    handler=_logged_layout_pptx,
)

__all__ = ["layout_pptx_agent"]


import logging

from schemas import PptxRewriteRequest
from endpoints.files_pptx.rewrite_pptx import rewrite_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.rewrite")


async def _logged_rewrite_pptx(payload: PptxRewriteRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_rewrite agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await rewrite_pptx(payload, request)


rewrite_pptx_agent = handler_agent(
    name="pptx_rewrite",
    description="PPTX sunumunun metnini yeniden yazar/düzenler; .pptx/.ppt içerikler.",
    request_model=PptxRewriteRequest,
    handler=_logged_rewrite_pptx,
)

__all__ = ["rewrite_pptx_agent"]


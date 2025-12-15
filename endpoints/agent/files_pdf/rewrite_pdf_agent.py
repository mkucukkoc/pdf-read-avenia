import logging

from schemas import PdfRewriteRequest
from endpoints.files_pdf.rewrite_pdf import rewrite_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.rewrite")


async def _logged_rewrite_pdf(payload: PdfRewriteRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_rewrite agent handler invoked chatId=%s userId=%s fileUrl=%s style=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.style,
    )
    return await rewrite_pdf(payload, request)


rewrite_pdf_agent = handler_agent(
    name="pdf_rewrite",
    description="PDF içerisindeki metinleri yeniden yazar veya düzenler.",
    request_model=PdfRewriteRequest,
    handler=_logged_rewrite_pdf,
)

__all__ = ["rewrite_pdf_agent"]


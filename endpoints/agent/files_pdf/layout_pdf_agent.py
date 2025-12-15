import logging

from schemas import PdfLayoutRequest
from endpoints.files_pdf.layout_pdf import layout_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.layout")


async def _logged_layout_pdf(payload: PdfLayoutRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_layout agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await layout_pdf(payload, request)


layout_pdf_agent = handler_agent(
    name="pdf_layout",
    description="PDF'in layout ve yapısal detaylarını çıkarır.",
    request_model=PdfLayoutRequest,
    handler=_logged_layout_pdf,
)

__all__ = ["layout_pdf_agent"]


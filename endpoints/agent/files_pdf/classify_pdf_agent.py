import logging

from schemas import PdfClassifyRequest
from endpoints.files_pdf.classify_pdf import classify_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.classify")


async def _logged_classify_pdf(payload: PdfClassifyRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_classify agent handler invoked chatId=%s userId=%s labels=%s fileUrl=%s",
        payload.chat_id,
        user_id,
        payload.labels,
        payload.file_url,
    )
    return await classify_pdf(payload, request)


classify_pdf_agent = handler_agent(
    name="pdf_classify",
    description="PDF içeriğini belirtilen kriterlere göre sınıflandırır.",
    request_model=PdfClassifyRequest,
    handler=_logged_classify_pdf,
)

__all__ = ["classify_pdf_agent"]


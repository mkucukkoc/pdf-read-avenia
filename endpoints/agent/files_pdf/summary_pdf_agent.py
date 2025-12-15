import logging

from schemas import PdfSummaryRequest
from endpoints.files_pdf.summary_pdf import summary_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.summary")


async def _logged_summary_pdf(payload: PdfSummaryRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_summary agent handler invoked chatId=%s userId=%s fileUrl=%s summaryLevel=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.summary_level,
    )
    return await summary_pdf(payload, request)


summary_pdf_agent = handler_agent(
    name="pdf_summary",
    description="PDF içerisinden özet çıkarır.",
    request_model=PdfSummaryRequest,
    handler=_logged_summary_pdf,
)

__all__ = ["summary_pdf_agent"]


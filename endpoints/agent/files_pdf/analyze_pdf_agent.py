import logging

from schemas import PdfAnalyzeRequest
from endpoints.files_pdf.analyze_pdf import analyze_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.analyze")


async def _logged_analyze_pdf(payload: PdfAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_analyze agent handler invoked chatId=%s userId=%s fileName=%s fileUrl=%s",
        payload.chat_id,
        user_id,
        payload.file_name,
        payload.file_url,
    )
    return await analyze_pdf(payload, request)


analyze_pdf_agent = handler_agent(
    name="pdf_analyze",
    description="PDF dosyalarını detaylı analiz eder.",
    request_model=PdfAnalyzeRequest,
    handler=_logged_analyze_pdf,
)

__all__ = ["analyze_pdf_agent"]


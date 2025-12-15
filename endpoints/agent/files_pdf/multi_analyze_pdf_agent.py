import logging

from schemas import PdfMultiAnalyzeRequest
from endpoints.files_pdf.multianalyze_pdf import multianalyze_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.multi_analyze")


async def _logged_multi_analyze_pdf(payload: PdfMultiAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_multianalyze agent handler invoked chatId=%s userId=%s fileCount=%s",
        payload.chat_id,
        user_id,
        len(payload.file_urls or []),
    )
    return await multianalyze_pdf(payload, request)


multi_analyze_pdf_agent = handler_agent(
    name="pdf_multianalyze",
    description="Birden fazla PDF dosyasını birlikte analiz eder.",
    request_model=PdfMultiAnalyzeRequest,
    handler=_logged_multi_analyze_pdf,
)

__all__ = ["multi_analyze_pdf_agent"]


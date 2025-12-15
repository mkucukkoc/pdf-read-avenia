import logging

from schemas import PdfCompareRequest
from endpoints.files_pdf.compare_pdf import compare_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.compare")


async def _logged_compare_pdf(payload: PdfCompareRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_compare agent handler invoked chatId=%s userId=%s file1=%s file2=%s",
        payload.chat_id,
        user_id,
        payload.file1,
        payload.file2,
    )
    return await compare_pdf(payload, request)


compare_pdf_agent = handler_agent(
    name="pdf_compare",
    description="İki PDF dosyasını farklarını belirleyerek karşılaştırır.",
    request_model=PdfCompareRequest,
    handler=_logged_compare_pdf,
)

__all__ = ["compare_pdf_agent"]


import logging

from schemas import PdfExtractRequest
from endpoints.files_pdf.extract_pdf import extract_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.extract")


async def _logged_extract_pdf(payload: PdfExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await extract_pdf(payload, request)


extract_pdf_agent = handler_agent(
    name="pdf_extract",
    description="PDF içerisindeki önemli bilgileri çıkarır.",
    request_model=PdfExtractRequest,
    handler=_logged_extract_pdf,
)

__all__ = ["extract_pdf_agent"]


import logging

from schemas import PdfDeepExtractRequest
from endpoints.files_pdf.deepextract_pdf import deepextract_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.deep_extract")


async def _logged_deep_extract_pdf(payload: PdfDeepExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_deepextract agent handler invoked chatId=%s userId=%s fileUrl=%s fields=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.fields,
    )
    return await deepextract_pdf(payload, request)


deep_extract_pdf_agent = handler_agent(
    name="pdf_deepextract",
    description="PDF içerisindeki belirli alanları derinlemesine çıkarır.",
    request_model=PdfDeepExtractRequest,
    handler=_logged_deep_extract_pdf,
)

__all__ = ["deep_extract_pdf_agent"]


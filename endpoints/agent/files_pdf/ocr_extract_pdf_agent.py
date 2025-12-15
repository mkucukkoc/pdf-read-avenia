import logging

from schemas import PdfOcrExtractRequest
from endpoints.files_pdf.ocr_extract_pdf import ocr_extract_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.ocr_extract")


async def _logged_ocr_extract_pdf(payload: PdfOcrExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_ocr_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await ocr_extract_pdf(payload, request)


ocr_extract_pdf_agent = handler_agent(
    name="pdf_ocr_extract",
    description="PDF içerisindeki metni OCR ile çıkarır.",
    request_model=PdfOcrExtractRequest,
    handler=_logged_ocr_extract_pdf,
)

__all__ = ["ocr_extract_pdf_agent"]


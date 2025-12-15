import logging

from schemas import PdfTranslateRequest
from endpoints.files_pdf.translate_pdf import translate_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.translate")


async def _logged_translate_pdf(payload: PdfTranslateRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_translate agent handler invoked chatId=%s userId=%s fileUrl=%s targetLanguage=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.target_language,
    )
    return await translate_pdf(payload, request)


translate_pdf_agent = handler_agent(
    name="pdf_translate",
    description="PDF içeriğini hedef dile çevirir.",
    request_model=PdfTranslateRequest,
    handler=_logged_translate_pdf,
)

__all__ = ["translate_pdf_agent"]


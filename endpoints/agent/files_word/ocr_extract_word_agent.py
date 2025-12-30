import logging

from schemas import DocOcrExtractRequest
from endpoints.files_word.ocr_extract_word import ocr_extract_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.ocr_extract")


async def _logged_ocr_extract_word(payload: DocOcrExtractRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_ocr_extract agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await ocr_extract_word(payload, request)


ocr_extract_word_agent = handler_agent(
    name="word_ocr_extract",
    description="Word dokümanından metni (gerekirse OCR ile) çıkarır; .docx/.doc içerikler.",
    request_model=DocOcrExtractRequest,
    handler=_logged_ocr_extract_word,
)

__all__ = ["ocr_extract_word_agent"]


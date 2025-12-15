import logging

from schemas import PdfQnaRequest
from endpoints.files_pdf.qna_pdf import qna_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.qna")


async def _logged_qna_pdf(payload: PdfQnaRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_qna agent handler invoked chatId=%s userId=%s question=%s fileUrl=%s fileId=%s",
        payload.chat_id,
        user_id,
        payload.question,
        payload.file_url,
        payload.file_id,
    )
    return await qna_pdf(payload, request)


qna_pdf_agent = handler_agent(
    name="pdf_qna",
    description="PDF üzerinde soru-cevap işlemleri yapar.",
    request_model=PdfQnaRequest,
    handler=_logged_qna_pdf,
)

__all__ = ["qna_pdf_agent"]


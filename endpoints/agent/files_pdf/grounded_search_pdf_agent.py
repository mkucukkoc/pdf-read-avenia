import logging

from schemas import PdfGroundedSearchRequest
from endpoints.files_pdf.grounded_search_pdf import grounded_search_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.grounded_search")


async def _logged_grounded_search_pdf(payload: PdfGroundedSearchRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_grounded_search agent handler invoked chatId=%s userId=%s question=%s fileUrl=%s",
        payload.chat_id,
        user_id,
        payload.question,
        payload.file_url,
    )
    return await grounded_search_pdf(payload, request)


grounded_search_pdf_agent = handler_agent(
    name="pdf_grounded_search",
    description="PDF içerisinde grounded search yapar.",
    request_model=PdfGroundedSearchRequest,
    handler=_logged_grounded_search_pdf,
)

__all__ = ["grounded_search_pdf_agent"]


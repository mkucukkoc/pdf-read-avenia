import logging

from schemas import DocRequest
from endpoints.generate_doffice.generate_pdf import generate_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.generate_pdf")


async def _logged_generate_pdf(payload: DocRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "generate_pdf agent invoked chatId=%s userId=%s prompt_len=%s",
        getattr(payload, "chat_id", None),
        user_id,
        len(payload.prompt or ""),
    )
    return await generate_pdf(payload)


generate_pdf_agent = handler_agent(
    name="generate_pdf",
    description="Kullanıcı promptuna göre raporu JSON olarak kurgular, PDF üretir ve link döner.",
    request_model=DocRequest,
    handler=_logged_generate_pdf,
)

__all__ = ["generate_pdf_agent"]


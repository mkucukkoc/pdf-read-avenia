import logging

from schemas import DocRequest
from endpoints.generate_doffice.generate_ppt import generate_ppt
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.generate_ppt")


async def _logged_generate_ppt(payload: DocRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "generate_ppt agent invoked chatId=%s userId=%s prompt_len=%s",
        getattr(payload, "chat_id", None),
        user_id,
        len(payload.prompt or ""),
    )
    return await generate_ppt(payload)


generate_ppt_agent = handler_agent(
    name="generate_ppt",
    description="Kullanıcı promptuna göre slaytları JSON olarak kurgular, PPT üretir ve link döner.",
    request_model=DocRequest,
    handler=_logged_generate_ppt,
)

__all__ = ["generate_ppt_agent"]


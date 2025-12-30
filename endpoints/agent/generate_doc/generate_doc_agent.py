import logging

from schemas import DocRequest
from endpoints.generate_doffice.generate_doc import generate_doc
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.generate_doc")


async def _logged_generate_doc(payload: DocRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "generate_doc agent invoked chatId=%s userId=%s prompt_len=%s",
        getattr(payload, "chat_id", None),
        user_id,
        len(payload.prompt or ""),
    )
    return await generate_doc(payload)


generate_doc_agent = handler_agent(
    name="generate_doc",
    description="Kullanıcı promptuna göre Word dokümanı üretir ve link döner.",
    request_model=DocRequest,
    handler=_logged_generate_doc,
)

__all__ = ["generate_doc_agent"]


import logging

from schemas import DocStructureExportRequest
from endpoints.files_word.structure_export_word import structure_export_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.structure_export")


async def _logged_structure_export_word(payload: DocStructureExportRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_structure_export agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await structure_export_word(payload, request)


structure_export_word_agent = handler_agent(
    name="word_structure_export",
    description="Word dokümanı yapısını dışa aktarır; .docx/.doc içerikler.",
    request_model=DocStructureExportRequest,
    handler=_logged_structure_export_word,
)

__all__ = ["structure_export_word_agent"]


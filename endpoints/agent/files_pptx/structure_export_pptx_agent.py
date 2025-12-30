import logging

from schemas import PptxStructureExportRequest
from endpoints.files_pptx.structure_export_pptx import structure_export_pptx
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pptx.structure_export")


async def _logged_structure_export_pptx(payload: PptxStructureExportRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pptx_structure_export agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await structure_export_pptx(payload, request)


structure_export_pptx_agent = handler_agent(
    name="pptx_structure_export",
    description="PPTX sunumunun yapısını dışa aktarır; .pptx/.ppt içerikler.",
    request_model=PptxStructureExportRequest,
    handler=_logged_structure_export_pptx,
)

__all__ = ["structure_export_pptx_agent"]


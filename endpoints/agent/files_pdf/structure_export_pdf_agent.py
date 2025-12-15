import logging

from schemas import PdfStructureExportRequest
from endpoints.files_pdf.structure_export_pdf import structure_export_pdf
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_pdf.structure_export")


async def _logged_structure_export_pdf(payload: PdfStructureExportRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "pdf_structure_export agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await structure_export_pdf(payload, request)


structure_export_pdf_agent = handler_agent(
    name="pdf_structure_export",
    description="PDF yapısını dışa aktarır.",
    request_model=PdfStructureExportRequest,
    handler=_logged_structure_export_pdf,
)

__all__ = ["structure_export_pdf_agent"]


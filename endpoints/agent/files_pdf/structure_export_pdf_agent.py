from schemas import PdfStructureExportRequest
from endpoints.files_pdf.structure_export_pdf import structure_export_pdf
from endpoints.agent.baseAgent import handler_agent

structure_export_pdf_agent = handler_agent(
    name="pdf_structure_export",
    description="PDF yapısını dışa aktarır.",
    request_model=PdfStructureExportRequest,
    handler=structure_export_pdf,
)

__all__ = ["structure_export_pdf_agent"]


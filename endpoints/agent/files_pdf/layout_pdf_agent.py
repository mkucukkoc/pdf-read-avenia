from schemas import PdfLayoutRequest
from endpoints.files_pdf.layout_pdf import layout_pdf
from endpoints.agent.baseAgent import handler_agent

layout_pdf_agent = handler_agent(
    name="pdf_layout",
    description="PDF'in layout ve yapısal detaylarını çıkarır.",
    request_model=PdfLayoutRequest,
    handler=layout_pdf,
)

__all__ = ["layout_pdf_agent"]


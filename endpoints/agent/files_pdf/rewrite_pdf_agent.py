from schemas import PdfRewriteRequest
from endpoints.files_pdf.rewrite_pdf import rewrite_pdf
from endpoints.agent.baseAgent import handler_agent

rewrite_pdf_agent = handler_agent(
    name="pdf_rewrite",
    description="PDF içerisindeki metinleri yeniden yazar veya düzenler.",
    request_model=PdfRewriteRequest,
    handler=rewrite_pdf,
)

__all__ = ["rewrite_pdf_agent"]

